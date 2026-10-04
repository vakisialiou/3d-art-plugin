"""This computer's device tokens, one per server, in one file outside
Blender's folders and never in a .blend: they survive restarts, File → New,
other .blend files and Blender upgrades. Keyed by server URL so a dev and a
production server coexist. ART3D_TOKEN (headless/CI) is used instead of the
file and never written to disk.

No bpy here: the connection worker thread reads and writes it too.
"""

import json
import os
import sys
import tempfile
import threading
from typing import Optional

_ENV_TOKEN = "ART3D_TOKEN"
_FOLDER = "art3d"
_FILE_NAME = "credentials.json"

_lock = threading.Lock()
# Set once the server rejected ART3D_TOKEN: the process stops offering it.
_env_rejected = False


def path() -> str:
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", "")
        if not os.path.isabs(base):
            base = os.path.join(home, ".config")
    return os.path.join(base, _FOLDER, _FILE_NAME)


def load(server_url: str) -> Optional[dict]:
    """The device entry for `server_url` — {deviceToken, deviceId,
    deviceName, email, source: 'env' | 'file'} — or None.
    """
    env_token = os.environ.get(_ENV_TOKEN, "").strip()
    if env_token and not _env_rejected:
        return {"deviceToken": env_token, "deviceId": "", "deviceName": "", "email": "", "source": "env"}
    with _lock:
        stored = _read().get(server_url)
    if not isinstance(stored, dict) or not isinstance(stored.get("deviceToken"), str) or not stored["deviceToken"]:
        return None
    return {
        "deviceToken": stored["deviceToken"],
        "deviceId": str(stored.get("deviceId") or ""),
        "deviceName": str(stored.get("deviceName") or ""),
        "email": str(stored.get("email") or ""),
        "source": "file",
    }


def from_grant(token: str, device: object) -> dict:
    """A file-sourced entry for a freshly issued token and its `device` {id, name}."""
    device = device if isinstance(device, dict) else {}
    return {
        "deviceToken": token,
        "deviceId": str(device.get("id") or ""),
        "deviceName": str(device.get("name") or ""),
        "email": "",
        "source": "file",
    }


def save(server_url: str, entry: dict) -> None:
    """Stores a file-sourced entry; an env-sourced one is never written."""
    if entry.get("source") != "file":
        return
    with _lock:
        servers = _read()
        servers[server_url] = {key: entry.get(key, "") for key in ("deviceToken", "deviceId", "deviceName", "email")}
        _write(servers)


def update(server_url: str, token: str, **fields: str) -> None:
    """Refreshes display fields (email, deviceName) of the entry still holding `token`."""
    with _lock:
        servers = _read()
        stored = servers.get(server_url)
        if not isinstance(stored, dict) or stored.get("deviceToken") != token:
            return
        if all(stored.get(key) == value for key, value in fields.items()):
            return
        stored.update(fields)
        _write(servers)


def forget(server_url: str, entry: dict) -> None:
    """Drops a revoked or disconnected entry. The file entry goes only if it
    still holds this token — another Blender may have connected anew since.
    """
    global _env_rejected
    if entry.get("source") == "env":
        _env_rejected = True
        return
    with _lock:
        servers = _read()
        stored = servers.get(server_url)
        if isinstance(stored, dict) and stored.get("deviceToken") == entry.get("deviceToken"):
            del servers[server_url]
            _write(servers)


def mtime() -> Optional[float]:
    try:
        return os.stat(path()).st_mtime
    except OSError:
        return None


def _read() -> dict:
    try:
        with open(path(), encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        print(f"3D Art: ignoring unreadable {path()}: {error}")
        return {}
    servers = data.get("servers") if isinstance(data, dict) else None
    return servers if isinstance(servers, dict) else {}


def _write(servers: dict) -> None:
    """Atomic: a temp file in the same folder, then os.replace."""
    target = path()
    folder = os.path.dirname(target)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(prefix=".credentials-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump({"servers": servers}, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        if os.name == "posix":
            os.chmod(temp_path, 0o600)
        os.replace(temp_path, target)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
