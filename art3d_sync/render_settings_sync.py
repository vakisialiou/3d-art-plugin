"""Reads scene-level render/color-management settings into a plain-dict
payload. Only fields this app's own browser-side engine actually applies and
that actually affect the rendered result belong here — see CLAUDE.md's
"Settings Display Model": the plugin should never send a field just because
Blender has it. `viewTransform` rides alongside `exposure` now that the
browser side has a real AgX port (ported from Blender's own OCIO config, the
same way the Nishita sky was) — sent verbatim, since Blender's own enum is
much larger than what the browser implements ('Standard'/'AgX' only; any
other value falls back to 'Standard' on arrival, a disclosed simplification).
`look`/`engine` still aren't sent — no Look-curve/engine concept exists on
the browser side to apply them to.
"""

import bpy


def build_render_settings_sync(context: bpy.types.Context) -> dict:
    return {
        "exposure": context.scene.view_settings.exposure,
        "viewTransform": context.scene.view_settings.view_transform,
    }
