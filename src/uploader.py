"""A Send's network side, on its own daemon thread (no bpy here): asks which
blobs the open browsers lack, uploads the missing ones raw, and posts the
sync messages that name them — strictly in the order the job queued them, so
a blob always lands before the message naming it. Consecutive object entries
go out as one `blender-sync` message.

The main thread only queues work and reads results (thread-safe); a failed
request stops the send and keeps the first error for the panel.
"""

import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from . import api_client, status
from .connection import INSTANCE_ID

_JSON_TIMEOUT_S = 60.0
_BLOB_TIMEOUT_S = 600.0
# One blender-sync message carries at most this many object entries.
_BATCH = 64


@dataclass
class Answer:
    """A request the main thread waits on: `done`, then `value` or `error`."""

    done: bool = False
    value: Any = None
    error: str = ""


@dataclass
class _Task:
    kind: str  # "missing" | "sync" | "blob" | "object"
    tag: str = ""
    keys: list = field(default_factory=list)
    answer: Optional[Answer] = None
    event: str = ""
    payload: Any = None
    entry: Optional[dict] = None
    glb_key: str = ""
    pack: Any = None  # resource_pack.Pack, or None when the browser has the glb


class Uploader:
    def __init__(self, connection, session, project_id: str):
        self._connection = connection
        self._session = session
        self._project_id = project_id
        self._tasks: deque = deque()
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._stopped = False
        self._busy = False
        self._uploaded: set = set()  # blob keys sent during this Send
        self._sent_tags: list = []  # tags whose message reached the server, in order
        self.bytes_sent = 0
        self.error = ""
        self._thread = threading.Thread(target=self._run, name="skyray-upload", daemon=True)
        self._thread.start()

    # ── Main thread ──────────────────────────────────────────────────

    def missing(self, keys: list) -> Answer:
        answer = Answer()
        self._push(_Task("missing", keys=list(keys), answer=answer))
        return answer

    def sync(self, event: str, payload: dict, tag: str) -> None:
        self._push(_Task("sync", tag=tag, event=event, payload=payload))

    def blob(self, key: str, kind: str, mime: str, data: bytes, tag: str, encoding: str = "") -> None:
        """One blob on its own (an HDRI, a set's placements), uploaded unless sent already this Send."""
        self._push(_Task("blob", tag=tag, glb_key=key, event=kind, payload=(mime, data, encoding)))

    def object(self, entry: dict, tag: str, glb_key: str = "", pack=None) -> None:
        """One object entry; with `pack`, its textures (those the browser lacks) and glb go first."""
        self._push(_Task("object", tag=tag, entry=entry, glb_key=glb_key, pack=pack))

    def idle(self) -> bool:
        with self._lock:
            return self.error != "" or (not self._tasks and not self._busy)

    def take_sent(self) -> list:
        with self._lock:
            sent, self._sent_tags = self._sent_tags, []
            return sent

    def close(self) -> None:
        """Drops the queue; a request already in flight still finishes."""
        with self._lock:
            self._stopped = True
            self._tasks.clear()
            self._wake.notify()

    def _push(self, task: _Task) -> None:
        with self._lock:
            if self._stopped or self.error:
                if task.answer is not None:
                    task.answer.error = self.error or "Send stopped"
                    task.answer.done = True
                return
            self._tasks.append(task)
            self._wake.notify()

    # ── Worker ───────────────────────────────────────────────────────

    def _run(self) -> None:
        while True:
            with self._lock:
                while not self._tasks and not self._stopped:
                    self._wake.wait()
                if self._stopped:
                    return
                batch = [self._tasks.popleft()]
                if batch[0].kind == "object":
                    while self._tasks and self._tasks[0].kind == "object" and len(batch) < _BATCH:
                        batch.append(self._tasks.popleft())
                self._busy = True
            try:
                self._handle(batch)
            except _Failure as failure:
                self._fail(failure.message, batch)
            except Exception as error:  # noqa: BLE001 — a bug must not hang the send
                traceback.print_exc()
                self._fail(f"Upload failed: {error}", batch)
            finally:
                with self._lock:
                    self._busy = False

    def _fail(self, message: str, batch: list) -> None:
        with self._lock:
            if not self.error:
                self.error = message
            pending = batch + list(self._tasks)
            self._tasks.clear()
        for task in pending:
            if task.answer is not None and not task.answer.done:
                task.answer.error = message
                task.answer.done = True

    def _handle(self, batch: list) -> None:
        first = batch[0]
        if first.kind == "missing":
            first.answer.value = self._ask(first.keys)
            first.answer.done = True
            return
        if first.kind == "sync":
            self._post_sync(first.event, first.payload)
            self._sent(first.tag)
            return
        if first.kind == "blob":
            if first.glb_key not in self._uploaded:
                mime, data, encoding = first.payload
                self._post_blob(first.glb_key, first.event, mime, data, encoding=encoding)
                self._uploaded.add(first.glb_key)
            return
        for task in batch:
            if task.pack is not None:
                self._upload_pack(task.glb_key, task.pack)
        self._post_sync(
            "blender-sync",
            {"blenderVersion": 0, "timestamp": int(time.time() * 1000), "objects": [task.entry for task in batch]},
        )
        for task in batch:
            self._sent(task.tag)

    def _sent(self, tag: str) -> None:
        with self._lock:
            self._sent_tags.append(tag)

    def _upload_pack(self, glb_key: str, pack) -> None:
        fresh = [texture for texture in pack.textures if texture.key not in self._uploaded]
        lacking = set(self._ask([texture.key for texture in fresh])) if fresh else set()
        for texture in fresh:
            if texture.key in lacking:
                self._post_blob(texture.key, "texture", texture.mime, texture.data)
            self._uploaded.add(texture.key)
        if glb_key not in self._uploaded:
            self._post_blob(glb_key, "glb", "model/gltf-binary", pack.glb, encoding="gzip", refs=pack.refs)
            self._uploaded.add(glb_key)

    # ── Requests ─────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self._session.server_url}/api/editor/{path}"

    def _ask(self, keys: list) -> list:
        if not keys:
            return []
        body = {"projectId": self._project_id, "instanceId": INSTANCE_ID, "keys": keys}
        code, data = self._call(lambda: api_client.request(
            "POST", self._url("missing"), token=self._session.token, body=body, timeout=_JSON_TIMEOUT_S
        ))
        missing = data.get("missing") if isinstance(data, dict) else None
        if not isinstance(missing, list):
            raise _Failure("The server's answer about missing data was unreadable")
        return [key for key in missing if isinstance(key, str)]

    def _post_sync(self, event: str, payload: dict) -> None:
        body = {"projectId": self._project_id, "instanceId": INSTANCE_ID, "event": event, "payload": payload}
        self._call(lambda: api_client.request(
            "POST", self._url("sync"), token=self._session.token, body=body, timeout=_JSON_TIMEOUT_S
        ))

    def _post_blob(self, key: str, kind: str, mime: str, data: bytes, encoding: str = "", refs=()) -> None:
        headers = {
            "x-skyray-project": self._project_id,
            "x-skyray-instance": INSTANCE_ID,
            "x-skyray-key": key,
            "x-skyray-kind": kind,
            "x-skyray-mime": mime,
        }
        if encoding:
            headers["x-skyray-encoding"] = encoding
        if refs:
            headers["x-skyray-refs"] = ",".join(refs)
        self._call(lambda: api_client.request_bytes(
            "POST", self._url("resource"), token=self._session.token, data=data, headers=headers,
            timeout=_BLOB_TIMEOUT_S,
        ))
        with self._lock:
            self.bytes_sent += len(data)

    def _call(self, send) -> tuple:
        try:
            code, data = send()
        except api_client.TransportError as error:
            self._connection.request_beat()
            raise _Failure(f"Can't reach Skyray: {error}") from error
        if api_client.ok(code):
            viewers = data.get("viewers") if isinstance(data, dict) else None
            if isinstance(viewers, int):
                self._connection.note_viewers(self._session.generation, viewers)
            return code, data
        if code == 401:
            self._connection.revoked(self._session.generation)
            raise _Failure(status.REVOKED_TEXT)
        self._connection.request_beat()
        if code == 409 and api_client.error_code(data) == "no_viewers":
            self._connection.note_viewers(self._session.generation, 0)
            raise _Failure(status.NO_VIEWERS_TEXT)
        if code == 426:
            raise _Failure(status.OUTDATED_TEXT)
        raise _Failure(api_client.error_message(code, data))


class _Failure(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
