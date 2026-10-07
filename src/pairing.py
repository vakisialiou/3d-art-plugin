"""Device pairing (RFC 8628 device-code flow): the server issues a code,
Blender shows it and opens the browser, the signed-in user approves it there,
and Blender's poll collects a long-lived device token. The token never passes
through the browser or the clipboard. No bpy here: the worker thread runs it.
"""

import time
from dataclasses import dataclass
from typing import Optional

from . import api_client
from .constants import CLIENT_KIND, PLUGIN_VERSION

EXPIRED = "The code expired — start connecting again"
DENIED = "The connection was denied in the browser"

# RFC 8628 §3.5: every slow_down answer adds 5 s to the polling interval.
_SLOW_DOWN_S = 5.0
_TIMEOUT_S = 10.0


class PairingError(Exception):
    """The server didn't issue a code; the message says why."""


@dataclass
class Grant:
    device_code: str
    user_code: str
    verification_url: str
    interval: float
    expires_at: float  # time.monotonic() clock


@dataclass(frozen=True)
class PollResult:
    token: str = ""
    device: Optional[dict] = None
    wait: float = 0.0  # poll again after this many seconds
    offline: bool = False  # `wait` came from a transport error
    error: str = ""  # the attempt is over


def request_code(server_url: str, name: str, app_version: str) -> Grant:
    body = {"kind": CLIENT_KIND, "name": name, "appVersion": app_version, "pluginVersion": PLUGIN_VERSION}
    try:
        status, data = api_client.request("POST", f"{server_url}/api/devices/code", body=body, timeout=_TIMEOUT_S)
    except api_client.TransportError as error:
        print(f"Skyray: can't reach {server_url}: {error}")
        raise PairingError("Can't reach the server") from error
    if not api_client.ok(status) or not isinstance(data, dict) or not isinstance(data.get("deviceCode"), str):
        raise PairingError(api_client.error_message(status, data))
    return Grant(
        device_code=data["deviceCode"],
        user_code=str(data.get("userCode") or ""),
        verification_url=str(data.get("verificationUriComplete") or data.get("verificationUri") or ""),
        interval=max(1.0, float(data.get("interval") or 5)),
        expires_at=time.monotonic() + float(data.get("expiresIn") or 600),
    )


def poll_token(server_url: str, grant: Grant, retry_s: float) -> PollResult:
    """One poll; `retry_s` is the wait after a transport error."""
    try:
        status, data = api_client.request(
            "POST", f"{server_url}/api/devices/token", body={"deviceCode": grant.device_code}, timeout=_TIMEOUT_S
        )
    except api_client.TransportError:
        return PollResult(wait=retry_s, offline=True)
    if api_client.ok(status) and isinstance(data, dict) and isinstance(data.get("deviceToken"), str):
        device = data.get("device")
        return PollResult(token=data["deviceToken"], device=device if isinstance(device, dict) else {})
    error = api_client.error_code(data)
    if error == "authorization_pending":
        return PollResult(wait=grant.interval)
    if error == "slow_down" or status == 429:
        grant.interval += _SLOW_DOWN_S
        return PollResult(wait=grant.interval)
    if error == "access_denied":
        return PollResult(error=_message(data, DENIED))
    if error == "expired_token":
        return PollResult(error=_message(data, EXPIRED))
    if status >= 500:
        return PollResult(wait=retry_s, offline=True)
    return PollResult(error=api_client.error_message(status, data))


def _message(data: object, fallback: str) -> str:
    message = data.get("message") if isinstance(data, dict) else None
    return message if isinstance(message, str) and message else fallback
