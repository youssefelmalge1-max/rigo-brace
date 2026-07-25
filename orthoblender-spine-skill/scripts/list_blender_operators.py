"""List registered rigo. operators + Rigo panels at runtime (inside Blender).

Run (GUI Blender, add-on enabled):
  & "<blender>" --app-template rigo_brace --python orthoblender-spine-skill/scripts/list_blender_operators.py
Writes operators_runtime.txt to the repo root and quits.
"""

import os
import bpy

_OUT = os.path.join(
    r"C:\Projects\Blender Add-on Braces", "operators_runtime.txt"
)


def _go():
    if not hasattr(bpy.types, "RIGO_PT_main"):
        return 0.2
    lines = ["# Registered rigo. operators"]
    for idname in sorted(dir(bpy.ops.rigo)):
        if idname.startswith("_"):
            continue
        lines.append(f"rigo.{idname}")
    lines.append("\n# Rigo panels")
    for t in sorted(dir(bpy.types)):
        if t.startswith("RIGO_PT_"):
            lines.append(t)
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_go, first_interval=0.5)
