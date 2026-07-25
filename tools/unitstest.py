"""Verify the baked startup.blend carries METRIC/MILLIMETERS scene units
(so interactive transforms read out in mm).  Writes unitstest_result.txt
and self-quits.
"""

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\unitstest_result.txt"


def _run():
    units = bpy.context.scene.unit_settings
    ok = units.system == "METRIC" and units.length_unit == "MILLIMETERS"
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write(
            f"system={units.system}\n"
            f"length_unit={units.length_unit}\n"
            f"scale_length={units.scale_length}\n"
            f"PASS={ok}"
        )
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=1.5)
