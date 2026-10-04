"""The main-thread side of the connection. A 0.5 s timer (plus the file
load/save handlers) hands the active scene's project, the file and the scene
name to the worker, turns the worker's results into status.current(), and
redraws the UI only when what it shows changed. It also opens the browser
for a pairing code and caches the verified project's name on the scene.
"""

import time
import traceback
from typing import Optional

import bpy
from bpy.app.handlers import persistent

from . import credentials, preferences, project, status
from .connection import Connection, is_local

_TICK_S = 0.5
_CREDENTIALS_CHECK_S = 2.0  # while not connected: another Blender may connect this computer
_ID_MAX = 64  # the server's limit for a project id

_connection: Optional[Connection] = None
_server_url: Optional[str] = None
_credentials_mtime: Optional[float] = None
_credentials_checked = 0.0
_opened_code = ""
_shown: Optional[tuple] = None


def connection() -> Connection:
    return _connection


def register() -> None:
    global _connection, _server_url, _credentials_mtime, _credentials_checked, _opened_code, _shown
    _connection = Connection(bpy.app.version_string)
    _server_url, _credentials_mtime, _credentials_checked, _opened_code, _shown = None, None, 0.0, "", None
    status.set_current(status.Status())
    bpy.types.WindowManager.art3d_redraw = bpy.props.IntProperty(options={"HIDDEN"}, update=_redrawn)
    for handlers, handler in _handlers():
        handlers.append(handler)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=_TICK_S, persistent=True)


def unregister() -> None:
    global _connection
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for handlers, handler in _handlers():
        if handler in handlers:
            handlers.remove(handler)
    if _connection is not None:
        _connection.stop(leave=True)
        _connection = None
    del bpy.types.WindowManager.art3d_redraw


def refresh() -> None:
    """The timer's work, run now: after a click, and in headless scripts where no timers run."""
    try:
        _update()
    except Exception:
        traceback.print_exc()


def network_allowed(server_url: str) -> bool:
    """A local server is always reachable; any other needs Blender's Online Access."""
    return is_local(server_url) or bpy.app.online_access


def open_url(url: str) -> None:
    if bpy.app.background:
        print(f"3D Art: open {url}")
        return
    try:
        bpy.ops.wm.url_open(url=url)
    except RuntimeError as error:
        print(f"3D Art: couldn't open {url}: {error}")


def _tick() -> float:
    refresh()
    return _TICK_S


def _update() -> None:
    if _connection is None:
        return
    server_url = preferences.server_url()
    _load_credentials(server_url)
    online = network_allowed(server_url)
    _connection.set_online(online)

    scene = bpy.context.scene
    bound_id = project.scene_project_id(scene)[:_ID_MAX] if scene else ""
    file_name = bpy.path.basename(bpy.data.filepath) or "Untitled"
    _connection.set_context(bound_id or None, file_name, scene.name if scene else "")
    if _connection.needs_thread():
        _connection.start()

    current = status.evaluate(
        _connection.snapshot(), online, bound_id, scene.art3d_project_name if scene else ""
    )
    status.set_current(current)
    _open_pairing_link(current)
    _cache_project_name(scene, current)
    _redraw_if_changed(current)


def _load_credentials(server_url: str) -> None:
    """Hands the worker this server's stored token: at start, when the server
    changes, and — while not connected — when the credentials file changed.
    """
    global _server_url, _credentials_mtime, _credentials_checked
    if server_url != _server_url:
        _server_url = server_url
        _credentials_mtime = credentials.mtime()
        _connection.configure(server_url, credentials.load(server_url))
        return
    if _connection.connected() or _connection.pairing():
        return
    now = time.monotonic()
    if now - _credentials_checked < _CREDENTIALS_CHECK_S:
        return
    _credentials_checked = now
    mtime = credentials.mtime()
    if mtime == _credentials_mtime:
        return
    _credentials_mtime = mtime
    entry = credentials.load(server_url)
    if entry is not None:
        _connection.configure(server_url, entry)


def _open_pairing_link(current: status.Status) -> None:
    """Opens the approval page once per issued code."""
    global _opened_code
    if current.state != status.WAITING_APPROVAL or not current.verification_url:
        return
    if current.user_code == _opened_code:
        return
    _opened_code = current.user_code
    open_url(current.verification_url)


def _cache_project_name(scene: Optional[bpy.types.Scene], current: status.Status) -> None:
    if scene is None or not current.project_id or not current.project_name:
        return
    if scene.art3d_project_name == current.project_name:
        return
    if project.scene_project_id(scene)[:_ID_MAX] != current.project_id:
        return
    try:
        scene.art3d_project_name = current.project_name
    except (AttributeError, RuntimeError, TypeError):
        pass  # a linked scene is read-only


def _redraw_if_changed(current: status.Status) -> None:
    """The status bar is a global area Python can't reach, and a timer has no
    region to tag; writing an ID property that has an update callback sends
    NC_WINDOW, which redraws every region — the status bar and the 3D Art
    panel included. Only when what the UI shows changed.
    """
    global _shown
    key = current.key()
    if key == _shown:
        return
    _shown = key
    window_manager = bpy.context.window_manager
    if window_manager is not None:
        window_manager.art3d_redraw = (window_manager.art3d_redraw + 1) % 1_000_000


def _redrawn(_self, _context) -> None:
    pass


@persistent
def _on_file_change(*_args) -> None:
    if _connection is not None:
        _connection.request_beat()
    refresh()


@persistent
def _on_exit(*_args) -> None:
    if _connection is not None:
        _connection.stop(leave=True)


def _handlers() -> tuple:
    return (
        (bpy.app.handlers.load_post, _on_file_change),
        (bpy.app.handlers.save_post, _on_file_change),
        (bpy.app.handlers.exit_pre, _on_exit),
    )
