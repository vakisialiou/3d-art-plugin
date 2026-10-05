"""The link to the 3D Art server. A daemon worker thread does the device
pairing, the heartbeat every few seconds and the project-list fetch. Send
announces itself with beat_now() on the main thread; the other one-off calls
(the sync upload, New project, the dev token) borrow the token via session().

The worker never touches bpy. The main thread (runtime.py) hands it the
active scene's context and reads its results through one lock; a wake event
makes it beat at once when the context or a send's progress changed.
"""

import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from . import api_client, credentials, pairing, status
from .constants import CLIENT_KIND, PLUGIN_VERSION, PROTOCOL_VERSION

# One per Blender process: two windows on one device stay apart in the
# browser's editor list.
INSTANCE_ID = uuid.uuid4().hex

_BACKOFF_S = (1.0, 2.0, 5.0, 10.0, 30.0)  # retries while the server is unreachable
_HEARTBEAT_S = 3.0  # until the server names its own interval
_OUTDATED_RETRY_S = 60.0
_PROJECTS_MAX_AGE_S = 60.0
_PROJECTS_RETRY_S = 10.0
_DEV_RETRY_S = 30.0
_IDLE_S = 5.0
_PROGRESS_BEAT_S = 1.0  # at most one extra heartbeat per second for a send's progress
_TIMEOUT_S = 10.0
_ANNOUNCE_TIMEOUT_S = 5.0
_LEAVE_TIMEOUT_S = 2.0
_TEXT_MAX = 200  # the server's limit for file and scene names
_ID_MAX = 64

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_local(server_url: str) -> bool:
    try:
        return urlsplit(server_url).hostname in _LOCAL_HOSTS
    except ValueError:
        return False


@dataclass(frozen=True)
class Snapshot:
    """The worker's results, copied out for status.evaluate()."""

    server_url: str
    connected: bool
    email: str
    device_name: str
    pairing: bool
    user_code: str
    verification_url: str
    notice: str  # why the device is not connected, if there is a reason
    reachable: Optional[bool]  # None until the first heartbeat answered
    error: str  # the server's message when it answered with an error
    outdated: bool
    beat: Optional[dict]  # the last heartbeat answer
    beat_project_id: Optional[str]  # the projectId that heartbeat carried
    dev_available: bool
    revision: int


@dataclass(frozen=True)
class Session:
    server_url: str
    token: str
    generation: int  # pass back to revoked()/note_viewers() so a stale answer is dropped


class _Attempt:
    """One Connect click; replaced, never reused, by Cancel or a new Connect."""

    def __init__(self, name: str):
        self.name = name
        self.grant: Optional[pairing.Grant] = None
        self.next_poll = 0.0
        self.failures = 0


class Connection:
    def __init__(self, app_version: str):
        self._app_version = app_version[:40]
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stop: Optional[threading.Event] = None
        # Inputs from the main thread.
        self._server_url = ""
        self._online = False
        self._context = {"projectId": None, "file": "Untitled", "scene": ""}
        self._sending: Optional[dict] = None
        self._progress_beat_at = 0.0
        # The device token in use (a credentials entry) and its generation:
        # a result computed under an older generation is dropped.
        self._entry: Optional[dict] = None
        self._generation = 0
        # Pending work.
        self._attempt: Optional[_Attempt] = None
        self._revocations: list = []
        self._beat_requested = False
        self._beat_due = 0.0
        self._failures = 0
        self._projects_wanted = False
        self._projects_retry_at = 0.0
        self._dev_wanted = False
        self._dev_retry_at = 0.0
        # Results.
        self._notice = ""
        self._reachable: Optional[bool] = None
        self._error = ""
        self._outdated = False
        self._beat: Optional[dict] = None
        self._beat_project_id: Optional[str] = None
        self._projects: Optional[tuple] = None
        self._projects_at = 0.0
        self._dev_available: Optional[bool] = None
        self._revision = 0

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,), name="art3d-connection", daemon=True)
            self._thread.start()

    def stop(self, leave: bool) -> None:
        """Stops the worker; `leave` tells the server this editor is gone (≤2 s)."""
        with self._lock:
            thread, stop = self._thread, self._stop
            self._thread = self._stop = None
            server, token, online = self._server_url, self._token(), self._online
        if stop is not None:
            stop.set()
            self._wake.set()
        if leave and token and online:
            self._leave(server, token)
        if thread is not None:
            thread.join(timeout=0.5)

    def needs_thread(self) -> bool:
        with self._lock:
            return bool(
                self._entry
                or self._attempt
                or self._revocations
                or self._projects_wanted
                or self._dev_wanted
            )

    # ── Inputs (main thread) ─────────────────────────────────────────

    def configure(self, server_url: str, entry: Optional[dict]) -> None:
        """The server to use and its stored device entry (credentials.load)."""
        with self._lock:
            same_server = server_url == self._server_url
            if same_server and _token_of(entry) == self._token():
                return
            self._server_url = server_url
            self._entry = entry
            self._reset_results()
            if not same_server:
                self._attempt = None
                self._notice = ""
                self._dev_available = None
                self._dev_retry_at = 0.0
        self._kick()

    def set_online(self, online: bool) -> None:
        with self._lock:
            if online == self._online:
                return
            self._online = online
            self._beat_requested = True
        self._wake.set()

    def set_context(self, project_id: Optional[str], file: str, scene: str) -> None:
        context = {
            "projectId": project_id[:_ID_MAX] if project_id else None,
            "file": file[:_TEXT_MAX],
            "scene": scene[:_TEXT_MAX],
        }
        with self._lock:
            if context == self._context:
                return
            self._context = context
            self._beat_requested = True
        self._wake.set()

    def request_beat(self) -> None:
        with self._lock:
            self._beat_requested = True
        self._wake.set()

    def want_projects(self, force: bool = False) -> None:
        """Asks the worker for the project list when it's missing or stale (or `force`)."""
        with self._lock:
            if self._entry is None or self._projects_wanted:
                return
            now = time.monotonic()
            stale = self._projects is None or now - self._projects_at > _PROJECTS_MAX_AGE_S
            if not force and not (stale and now >= self._projects_retry_at):
                return
            self._projects_wanted = True
        self._kick()

    def want_dev_check(self) -> None:
        """Asks a local server whether it offers the dev shortcut (once per server)."""
        with self._lock:
            if self._entry is not None or self._dev_available is not None or self._dev_wanted:
                return
            if not is_local(self._server_url) or time.monotonic() < self._dev_retry_at:
                return
            self._dev_wanted = True
        self._kick()

    def start_pairing(self, name: str) -> None:
        with self._lock:
            if self._entry is not None:
                return
            self._attempt = _Attempt(name)
            self._notice = ""
        self._kick()

    def cancel_pairing(self) -> None:
        with self._lock:
            self._attempt = None

    def disconnect(self) -> None:
        """Forgets the device locally now; the worker revokes it server-side."""
        with self._lock:
            entry, server = self._entry, self._server_url
            self._attempt = None
            if entry is None:
                return
            self._revocations.append((server, entry["deviceToken"]))
            self._entry = None
            self._notice = ""
            self._reset_results()
            _store(credentials.forget, server, entry)
        self._kick()

    def adopt(self, entry: dict) -> None:
        """Uses a freshly issued device token (dev shortcut) and stores it."""
        with self._lock:
            _store(credentials.save, self._server_url, entry)
            self._attempt = None
            self._entry = entry
            self._notice = ""
            self._reset_results()
        self._kick()

    # ── Results (main thread) ────────────────────────────────────────

    def snapshot(self) -> Snapshot:
        with self._lock:
            entry = self._entry or {}
            beat = self._beat or {}
            grant = self._attempt.grant if self._attempt else None
            return Snapshot(
                server_url=self._server_url,
                connected=self._entry is not None,
                email=_field(beat, "user", "email") or entry.get("email", ""),
                device_name=_field(beat, "device", "name") or entry.get("deviceName", ""),
                pairing=self._attempt is not None,
                user_code=grant.user_code if grant else "",
                verification_url=grant.verification_url if grant else "",
                notice=self._notice,
                reachable=self._reachable,
                error=self._error,
                outdated=self._outdated,
                beat=self._beat,
                beat_project_id=self._beat_project_id,
                dev_available=bool(self._dev_available),
                revision=self._revision,
            )

    def connected(self) -> bool:
        with self._lock:
            return self._entry is not None

    def pairing(self) -> bool:
        with self._lock:
            return self._attempt is not None

    def projects(self) -> tuple:
        """((id, name), …) from the last fetch, newest first; () before one."""
        with self._lock:
            return self._projects or ()

    # ── Calls on the main thread ─────────────────────────────────────

    def begin_sending(self, channel: str, total: int) -> str:
        """Marks a send in progress and announces it with one synchronous
        heartbeat, so the server keeps listing this editor while the main
        thread is busy exporting. "" when it went through, else why not.
        """
        with self._lock:
            self._sending = {"channel": channel, "done": 0, "total": max(0, int(total))}
        return self.beat_now(_ANNOUNCE_TIMEOUT_S)

    def set_progress(self, done: int) -> None:
        """A send's progress, handed to the worker at most once a second."""
        with self._lock:
            if self._sending is None:
                return
            self._sending = {**self._sending, "done": max(0, int(done))}
            now = time.monotonic()
            if now - self._progress_beat_at < _PROGRESS_BEAT_S:
                return
            self._progress_beat_at = now
            self._beat_requested = True
        self._wake.set()

    def mark_sending(self, channel: str, done: int, total: int) -> None:
        """A Send's progress without a synchronous heartbeat: the worker
        announces it (at once when it starts, then at most once a second)."""
        with self._lock:
            starting = self._sending is None
            self._sending = {"channel": channel, "done": max(0, int(done)), "total": max(0, int(total))}
            now = time.monotonic()
            if not starting and now - self._progress_beat_at < _PROGRESS_BEAT_S:
                return
            self._progress_beat_at = now
            self._beat_requested = True
        self._wake.set()

    def end_sending(self) -> None:
        with self._lock:
            if self._sending is None:
                return
            self._sending = None
            self._beat_requested = True
        self._wake.set()

    def beat_now(self, timeout: float = _TIMEOUT_S) -> str:
        """One heartbeat on the calling thread; "" when it succeeded, else why not."""
        with self._lock:
            server, token, generation, online = self._server_url, self._token(), self._generation, self._online
        if token is None:
            return status.NOT_CONNECTED_TEXT
        if not online:
            return status.ONLINE_OFF_TEXT
        code, data = self._heartbeat(server, token, generation, timeout)
        if code is None:
            return f"Can't reach the server: {data}"
        if api_client.ok(code):
            return ""
        if code == 401:
            return status.REVOKED_TEXT
        if code == 426:
            return status.OUTDATED_TEXT
        return api_client.error_message(code, data)

    def session(self) -> Optional["Session"]:
        """The device token in use, for a call made outside the worker; None when not connected."""
        with self._lock:
            token = self._token()
            return Session(self._server_url, token, self._generation) if token else None

    def server_url(self) -> str:
        with self._lock:
            return self._server_url

    def revoked(self, generation: int) -> None:
        """Any 401: the device was disconnected in the browser (or is unknown)."""
        with self._lock:
            if generation != self._generation or self._entry is None:
                return
            _store(credentials.forget, self._server_url, self._entry)
            self._entry = None
            self._notice = status.REVOKED_TEXT
            self._reset_results()

    def note_viewers(self, generation: int, viewers: int) -> None:
        """A sync answer's viewer count, shown before the next heartbeat."""
        with self._lock:
            if generation == self._generation and self._beat is not None:
                self._beat = {**self._beat, "viewers": viewers}

    def add_project(self, generation: int, project_id: str, name: str) -> None:
        """A project created here goes first in the list without a refetch."""
        with self._lock:
            if generation != self._generation:
                return
            listed = tuple(item for item in (self._projects or ()) if item[0] != project_id)
            self._projects = ((project_id, name),) + listed
            self._revision += 1

    # ── Worker ───────────────────────────────────────────────────────

    def _run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                delay = self._step()
            except Exception:
                traceback.print_exc()
                delay = _IDLE_S
            self._wake.wait(delay)
            self._wake.clear()

    def _step(self) -> float:
        """One pass over the pending work; returns the seconds until the next."""
        now = time.monotonic()
        with self._lock:
            if not self._online:
                # Online access is off: no network at all, pending revocations included.
                self._revocations = []
                return _IDLE_S
            server = self._server_url
            revocations, self._revocations = self._revocations, []
            attempt = self._attempt
            token, generation = self._token(), self._generation
            beat = token is not None and (self._beat_requested or now >= self._beat_due)
            if beat:
                self._beat_requested = False
            projects = token is not None and self._projects_wanted
            dev_check = token is None and self._dev_wanted
            self._projects_wanted = self._projects_wanted and not projects
            self._dev_wanted = self._dev_wanted and not dev_check

        for revoked_server, revoked_token in revocations:
            self._revoke_remotely(revoked_server, revoked_token)
        delays = [_IDLE_S]
        if attempt is not None:
            delays.append(self._pair(attempt, server))
        if beat:
            self._heartbeat(server, token, generation, _TIMEOUT_S)
        if projects:
            self._fetch_projects(server, token, generation)
        if dev_check:
            self._check_dev(server)
        with self._lock:
            if self._token() is not None:
                delays.append(self._beat_due - time.monotonic())
        return max(0.05, min(delays))

    def _pair(self, attempt: _Attempt, server: str) -> float:
        if attempt.grant is None:
            try:
                grant = pairing.request_code(server, attempt.name, self._app_version)
            except pairing.PairingError as error:
                self._end_attempt(attempt, str(error))
                return _IDLE_S
            with self._lock:
                if self._attempt is attempt:
                    attempt.grant = grant
                    attempt.next_poll = time.monotonic() + grant.interval
            return grant.interval

        now = time.monotonic()
        if now >= attempt.grant.expires_at:
            self._end_attempt(attempt, pairing.EXPIRED)
            return _IDLE_S
        if now < attempt.next_poll:
            return attempt.next_poll - now

        result = pairing.poll_token(server, attempt.grant, _backoff(attempt.failures + 1))
        if result.error:
            self._end_attempt(attempt, result.error)
            return _IDLE_S
        if not result.token:
            attempt.failures = attempt.failures + 1 if result.offline else 0
            attempt.next_poll = time.monotonic() + result.wait
            return result.wait

        entry = credentials.from_grant(result.token, result.device)
        with self._lock:
            current = self._attempt is attempt and server == self._server_url
            if current:
                _store(credentials.save, server, entry)
                self._attempt = None
                self._entry = entry
                self._notice = ""
                self._reset_results()
        if not current:
            # Cancelled while the browser approved: don't leave a stray device behind.
            self._revoke_remotely(server, result.token)
        return 0.05

    def _end_attempt(self, attempt: _Attempt, notice: str) -> None:
        with self._lock:
            if self._attempt is attempt:
                self._attempt = None
                self._notice = notice

    def _heartbeat(self, server: str, token: str, generation: int, timeout: float) -> tuple:
        """(HTTP status, body), or (None, the transport error) — results applied under the lock."""
        with self._lock:
            context, sending = dict(self._context), self._sending
        body = {
            "protocol": PROTOCOL_VERSION,
            "client": {
                "kind": CLIENT_KIND,
                "instanceId": INSTANCE_ID,
                "appVersion": self._app_version,
                "pluginVersion": PLUGIN_VERSION,
            },
            "context": context,
            "sending": sending,
        }
        try:
            code, data = api_client.request(
                "POST", f"{server}/api/editor/heartbeat", token=token, body=body, timeout=timeout
            )
        except api_client.TransportError as error:
            self._unreachable(generation, "")
            return None, str(error)

        if code == 401:
            self.revoked(generation)
            return code, data
        if code == 426:
            with self._lock:
                if generation == self._generation:
                    self._reachable, self._error, self._outdated = True, "", True
                    self._beat = None
                    self._beat_due = time.monotonic() + _OUTDATED_RETRY_S
            return code, data
        if not api_client.ok(code) or not isinstance(data, dict):
            self._unreachable(generation, api_client.error_message(code, data))
            return code, data
        with self._lock:
            if generation != self._generation:
                return code, data
            self._reachable, self._error, self._outdated, self._failures = True, "", False, 0
            self._beat, self._beat_project_id = data, context["projectId"]
            self._beat_due = time.monotonic() + _interval(data.get("heartbeatInterval"))
            refreshed = self._refreshed_entry(data)
        if refreshed is not None:
            _store(credentials.update, server, token, email=refreshed["email"], deviceName=refreshed["deviceName"])
        return code, data

    def _refreshed_entry(self, beat: dict) -> Optional[dict]:
        """The entry with the account email/device name the server reported, when they changed."""
        email, name = _field(beat, "user", "email"), _field(beat, "device", "name")
        entry = self._entry
        if entry is None or (entry.get("email") == email and entry.get("deviceName") == name):
            return None
        self._entry = {**entry, "email": email, "deviceName": name}
        return self._entry

    def _unreachable(self, generation: int, error: str) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._reachable, self._error = False, error
            self._failures += 1
            self._beat_due = time.monotonic() + _backoff(self._failures)

    def _fetch_projects(self, server: str, token: str, generation: int) -> None:
        try:
            code, data = api_client.request("GET", f"{server}/api/projects?summary=1", token=token, timeout=_TIMEOUT_S)
        except api_client.TransportError:
            code, data = None, None
        if code == 401:
            self.revoked(generation)
            return
        with self._lock:
            if generation != self._generation:
                return
            if code is None or not api_client.ok(code) or not isinstance(data, list):
                self._projects_retry_at = time.monotonic() + _PROJECTS_RETRY_S
                return
            self._projects = tuple(
                (item["id"], str(item.get("name") or "Untitled"))
                for item in data
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            )
            self._projects_at = time.monotonic()
            self._revision += 1

    def _check_dev(self, server: str) -> None:
        if not is_local(server):
            return
        try:
            code, data = api_client.request("GET", f"{server}/api/auth/methods", timeout=_TIMEOUT_S)
        except api_client.TransportError:
            with self._lock:
                self._dev_retry_at = time.monotonic() + _DEV_RETRY_S
            return
        with self._lock:
            if server == self._server_url:
                self._dev_available = api_client.ok(code) and isinstance(data, dict) and data.get("dev") is True

    def _revoke_remotely(self, server: str, token: str) -> None:
        """Best effort: leave the editor list, then revoke the token server-side."""
        self._leave(server, token)
        try:
            api_client.request("DELETE", f"{server}/api/devices/me", token=token, timeout=_ANNOUNCE_TIMEOUT_S)
        except api_client.TransportError:
            pass

    def _leave(self, server: str, token: str) -> None:
        try:
            api_client.request(
                "POST",
                f"{server}/api/editor/leave",
                token=token,
                body={"instanceId": INSTANCE_ID},
                timeout=_LEAVE_TIMEOUT_S,
            )
        except api_client.TransportError:
            pass

    # ── Helpers (lock held) ──────────────────────────────────────────

    def _token(self) -> Optional[str]:
        return _token_of(self._entry)

    def _reset_results(self) -> None:
        """A new token (or none): everything learned with the old one is void."""
        self._generation += 1
        self._reachable = None
        self._error = ""
        self._outdated = False
        self._beat = None
        self._beat_project_id = None
        self._failures = 0
        self._beat_requested = True
        self._projects = None
        self._projects_wanted = False
        self._projects_retry_at = 0.0
        self._revision += 1

    def _kick(self) -> None:
        """Wakes the worker, starting it first if there's work (call without the lock)."""
        if self.needs_thread():
            self.start()
        self._wake.set()


def _store(write, *args, **kwargs) -> None:
    """A credentials-file write; a failure is logged, the in-memory token stays usable."""
    try:
        write(*args, **kwargs)
    except OSError as error:
        print(f"3D Art: couldn't update {credentials.path()}: {error}")


def _token_of(entry: Optional[dict]) -> Optional[str]:
    return entry["deviceToken"] if entry else None


def _field(data: dict, group: str, key: str) -> str:
    value = data.get(group)
    value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, str) else ""


def _interval(value: object) -> float:
    if isinstance(value, (int, float)) and 1 <= value <= 60:
        return float(value)
    return _HEARTBEAT_S


def _backoff(failures: int) -> float:
    return _BACKOFF_S[min(max(failures, 1), len(_BACKOFF_S)) - 1]
