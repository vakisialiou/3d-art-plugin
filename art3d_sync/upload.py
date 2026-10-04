"""The Send path every sync operator shares. poll() passes only in READY for
the operator's own scene; a send announces itself with a heartbeat (so the
server keeps this editor listed while the main thread is busy exporting),
builds its payload, then POSTs it to /api/editor/sync — the server relays it
to the project's open browsers and keeps nothing.
"""

from typing import Callable, Optional

from . import api_client, project, runtime, status
from .connection import INSTANCE_ID

_SYNC_TIMEOUT_S = 300.0  # textures go out at original resolution


def can_send(operator_class, context) -> bool:
    current = status.current()
    if current.state != status.READY:
        operator_class.poll_message_set(current.message)
        return False
    if project.get_project_id(context) != current.project_id:
        operator_class.poll_message_set(status.CHECKING_TEXT)
        return False
    return True


def send(operator, context, channel: str, build: Callable, total: int = 1) -> Optional[dict]:
    """Runs one send: `build(progress)` returns the payload and may call
    `progress(done)` (out of `total`) while it works. Returns the payload
    once the server accepted it; otherwise reports why on `operator` and
    returns None.
    """
    connection = runtime.connection()
    project_id = project.get_project_id(context)
    payload = None
    try:
        error = connection.begin_sending(channel, total)
        if not error:
            payload = build(connection.set_progress)
            connection.set_progress(total)  # built; the upload itself takes the rest
            error = _upload(connection, project_id, channel, payload) if payload else "Nothing to send"
    finally:
        connection.end_sending()
        runtime.refresh()
    if error:
        operator.report({"ERROR"}, error)
        return None
    return payload


def _upload(connection, project_id: str, channel: str, payload: dict) -> str:
    """Empty once the server relayed the sync, else why not."""
    session = connection.session()
    if session is None:
        return status.NOT_CONNECTED_TEXT
    body = {"projectId": project_id, "instanceId": INSTANCE_ID, "event": channel, "payload": payload}
    try:
        code, data = api_client.request(
            "POST", f"{session.server_url}/api/editor/sync", token=session.token, body=body, timeout=_SYNC_TIMEOUT_S
        )
    except api_client.TransportError as error:
        connection.request_beat()
        return f"Can't reach the server: {error}"
    if api_client.ok(code):
        viewers = data.get("viewers") if isinstance(data, dict) else None
        if isinstance(viewers, int):
            connection.note_viewers(session.generation, viewers)
        return ""
    if code == 401:
        connection.revoked(session.generation)
        return status.REVOKED_TEXT
    connection.request_beat()
    if code == 409 and api_client.error_code(data) == "no_viewers":
        connection.note_viewers(session.generation, 0)
        return status.NO_VIEWERS_TEXT
    return api_client.error_message(code, data)
