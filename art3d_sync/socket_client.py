"""Minimal Engine.IO v4 / Socket.IO v5 polling client.

Uses only the Python standard library (urllib) so the addon works with
Blender's bundled Python and needs no pip install. Good enough for a
single fire-and-forget emit per button press; not a persistent connection.
"""

import json
import urllib.error
import urllib.request
from typing import Optional


class SocketIOEmitError(RuntimeError):
    pass


def emit_once(
    base_url: str,
    event: str,
    payload: dict,
    timeout: float = 300.0,
    auth: Optional[dict] = None,
) -> None:
    handshake_url = f"{base_url}/socket.io/?EIO=4&transport=polling"
    try:
        handshake_raw = _http_get(handshake_url, timeout)
    except (urllib.error.URLError, TimeoutError) as error:
        raise SocketIOEmitError(f"Cannot reach {base_url}: {error}") from error

    sid = _parse_handshake_sid(handshake_raw)
    poll_url = f"{base_url}/socket.io/?EIO=4&transport=polling&sid={sid}"

    # CONNECT (default namespace) — the auth object, if any, rides as this
    # packet's JSON body (Socket.IO's own handshake.auth on the server side),
    # same as socket.io-client's `io(url, { auth })` — see
    # blender-sync.gateway.ts's handleConnection for what reads it.
    connect_packet = "40" + (json.dumps(auth) if auth else "")
    try:
        _http_post(poll_url, connect_packet, timeout)
        _http_post(poll_url, "42" + json.dumps([event, payload]), timeout)  # EVENT
    except (urllib.error.URLError, TimeoutError) as error:
        raise SocketIOEmitError(f"Failed sending to {base_url}: {error}") from error


def _parse_handshake_sid(handshake_raw: str) -> str:
    packet = handshake_raw.split("\x1e", 1)[0]
    if not packet.startswith("0"):
        raise SocketIOEmitError(f"Unexpected handshake response: {handshake_raw!r}")
    return json.loads(packet[1:])["sid"]


def _http_get(url: str, timeout: float) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _http_post(url: str, body: str, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={"Content-Type": "text/plain;charset=UTF-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")
