"""Small layout helpers the 3D Art panel, popover and header share: wrapped
helper text (Blender labels never wrap), secondary notes, the blue primary
button, alerts, spinners."""

import blf

# What a label in a box loses to the sidebar's tabs and the panel and box margins; a leading icon takes _ICON more.
_INSET = 64
_ICON = 26


def lines(context, text: str, inset: float) -> list[str]:
    """Text split at spaces into lines that fit the region, measured in the UI font."""
    preferences = context.preferences
    scale = preferences.system.ui_scale or preferences.view.ui_scale
    width = context.region.width if context.region else 300 * scale
    room = width - inset * scale
    blf.size(0, preferences.ui_styles[0].widget.points * scale)
    result: list[str] = []
    for word in text.split():
        joined = f"{result[-1]} {word}" if result else word
        if result and blf.dimensions(0, joined)[0] <= room:
            result[-1] = joined
        else:
            result.append(word)
    return result


def wrap(layout, context, text: str, icon: str = "NONE", active: bool = False) -> None:
    column = layout.column(align=True)
    column.active = active
    inset = _INSET + (_ICON if icon != "NONE" else 0)
    for index, line in enumerate(lines(context, text, inset)):
        line_icon = icon if index == 0 else ("BLANK1" if icon != "NONE" else "NONE")
        column.label(text=line, icon=line_icon)


def note(layout, text: str, icon: str = "NONE", icon_value: int = 0):
    row = layout.row()
    row.active = False
    if icon_value:
        row.label(text=text, icon_value=icon_value)
    else:
        row.label(text=text, icon=icon)
    return row


def primary(layout, operator: str, text: str, icon: str, enabled: bool = True, scale: float = 1.5):
    """The panel's one main button: big, and blue while it can run."""
    row = layout.row()
    row.scale_y = scale
    row.enabled = enabled
    return row.operator(operator, text=text, icon=icon, depress=enabled)


def alert(layout, text: str, icon: str = "ERROR"):
    row = layout.row()
    row.alert = True
    row.label(text=text, icon=icon)
    return row


def ring(layout, text: str, factor: float = 0.3):
    layout.row().progress(factor=factor, type="RING", text=text)


def ago(timestamp: float, now: float) -> str:
    seconds = max(0, int(now - timestamp))
    if seconds < 45:
        return "just now"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours = round(minutes / 60)
    return f"{hours} h ago"


def duration(seconds: float) -> str:
    whole = int(round(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def megabytes(count: int) -> str:
    value = count / 1e6
    return f"{value:.1f} MB" if value < 100 else f"{value:.0f} MB"


def thousands(count: int) -> str:
    return f"{count / 1000:.0f}k" if count >= 10000 else f"{count:,}"
