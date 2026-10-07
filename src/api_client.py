"""JSON (and raw blobs) over HTTP to the Skyray server, stdlib only (Blender's Python has no
requests/socketio). No bpy here: the connection worker thread calls it.
"""

import http.client
import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Optional

from .constants import PLUGIN_VERSION

_USER_AGENT = f"skyray-blender/{PLUGIN_VERSION}"

_ssl_context: Optional[ssl.SSLContext] = None


class TransportError(Exception):
    """The server couldn't be reached or didn't answer with JSON."""


def request(
    method: str,
    url: str,
    *,
    token: Optional[str] = None,
    body: Any = None,
    timeout: float = 10.0,
) -> tuple[int, Any]:
    """(HTTP status, parsed JSON body or None) for any answer, error statuses
    included; raises TransportError when there is no usable answer.
    """
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    prepared = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(prepared, timeout=timeout, context=_context()) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        with error:
            raw = error.read()
        return error.code, _lenient_json(raw)
    except urllib.error.URLError as error:
        raise TransportError(str(error.reason)) from error
    except (OSError, http.client.HTTPException, ValueError) as error:
        # OSError: timeouts and resets; ValueError: a malformed URL or a
        # non-JSON success body (e.g. a proxy's HTML page).
        raise TransportError(str(error) or type(error).__name__) from error


def request_bytes(
    method: str,
    url: str,
    *,
    token: Optional[str],
    data: bytes,
    headers: dict,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    """Like request(), but the body is raw bytes (application/octet-stream)
    with extra `headers`; the answer is still JSON."""
    all_headers = {
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
        "Content-Type": "application/octet-stream",
        **headers,
    }
    if token:
        all_headers["Authorization"] = f"Bearer {token}"
    prepared = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(prepared, timeout=timeout, context=_context()) as response:
            raw = response.read()
            return response.status, _lenient_json(raw)
    except urllib.error.HTTPError as error:
        with error:
            raw = error.read()
        return error.code, _lenient_json(raw)
    except urllib.error.URLError as error:
        raise TransportError(str(error.reason)) from error
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise TransportError(str(error) or type(error).__name__) from error


def ok(status: int) -> bool:
    return 200 <= status < 300


def error_message(status: int, data: Any) -> str:
    """The server's own message for a failed request."""
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, list):
            message = "; ".join(str(part) for part in message)
        if isinstance(message, str) and message:
            return message
    return f"The server answered HTTP {status}"


def error_code(data: Any) -> str:
    """The machine-readable `error` field (e.g. 'no_viewers', 'slow_down')."""
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return data["error"]
    return ""


def _lenient_json(raw: bytes) -> Any:
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _context() -> ssl.SSLContext:
    global _ssl_context
    if _ssl_context is None:
        try:
            import certifi

            _ssl_context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            _ssl_context = ssl.create_default_context()
    return _ssl_context
