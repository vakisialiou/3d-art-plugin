"""Reads scene-level render/color-management settings into a plain-dict
payload. Only fields this app's own browser-side engine actually applies and
that actually affect the rendered result belong here — see CLAUDE.md's
"Settings Display Model": the plugin should never send a field just because
Blender has it. `viewTransform`/`look`/`engine` used to be sent alongside
`exposure` as "informational" fields, but this app's display pipeline is a
real ACES port, not Blender's own OCIO/AgX — there is no AgX, no Look curve,
and no engine concept anywhere in it, so those three fields did nothing on
arrival and were removed. (A real AgX port, ported from Blender's own OCIO
config the same way the Nishita sky was, is possible future work — if that
ever happens, `viewTransform`/`look` come back here, with a real destination
this time.)
"""

import bpy


def build_render_settings_sync(context: bpy.types.Context) -> dict:
    return {
        "exposure": context.scene.view_settings.exposure,
    }
