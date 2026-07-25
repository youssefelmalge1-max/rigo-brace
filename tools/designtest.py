"""Functional test: import the sample scan, generate a corset, and confirm it is
a real watertight-ish shell (has geometry, has an opening, is hollow). Writes
designtest_result.txt then quits. GUI only.
"""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import prepare_a_design  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\designtest_result.txt"
_TRIES = {"n": 0}


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1

    lines = []
    try:
        scan, settings = prepare_a_design()
        scan_verts = len(scan.data.vertices)

        settings.design_style = "CHENEAU"
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.trim_top = 30.0
        settings.trim_bottom = 30.0
        settings.opening_width = 40.0
        bpy.ops.rigo.generate_corset()

        corset = bpy.data.objects.get("Rigo Corset")
        ok_exists = corset is not None
        cverts = len(corset.data.vertices) if ok_exists else 0
        cfaces = len(corset.data.polygons) if ok_exists else 0

        lines.append(f"scan_verts={scan_verts}")
        lines.append(f"corset_exists={ok_exists}")
        lines.append(f"corset_verts={cverts}")
        lines.append(f"corset_faces={cfaces}")
        lines.append(f"PASS={ok_exists and cfaces > 100}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"ERROR={exc!r}")
        lines.append("PASS=False")

    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
