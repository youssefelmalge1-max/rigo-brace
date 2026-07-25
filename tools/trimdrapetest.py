"""Installed-copy regression for transformed scans and shoulder-ray fallback."""

import os
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import A_SCAN, _fixture_landmarks, _place  # noqa: E402


OUT = r"C:\Projects\Blender Add-on Braces\trimdrapetest_result.txt"
TRIES = {"count": 0}


def _raw_surface_distances_mm(scan, curve):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(scan, depsgraph)
    inverse = scan.matrix_world.inverted()
    distances = []
    for spline in curve.data.splines:
        for point in spline.bezier_points:
            world = curve.matrix_world @ point.co
            nearest = bvh.find_nearest(inverse @ world)
            if nearest[0] is not None:
                hit_world = scan.matrix_world @ nearest[0]
                distances.append((world - hit_world).length * 1000.0)
    return distances


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "auto_trimline") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        bpy.ops.wm.stl_import(filepath=A_SCAN)
        scan = bpy.context.object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        scan.scale = (0.85, 1.15, 1.05)
        scan.rotation_euler.z = 0.12
        bpy.context.view_layer.update()
        for landmark, local in _fixture_landmarks(scan).items():
            _place(settings, landmark, scan.matrix_world @ Vector(local))
        settings.trim_type = "RIGO_CHENEAU"
        settings.opening_width = 25.0
        transformed_result = bpy.ops.rigo.auto_trimline()

        top_z = max((scan.matrix_world @ vertex.co).z for vertex in scan.data.vertices)
        for name in ("LM_ACROMION_L", "LM_ACROMION_R"):
            bpy.data.objects[name].location.z = top_z + 0.012
        fallback_result = bpy.ops.rigo.auto_trimline()
        curve = bpy.data.objects.get("Rigo Trim Perimeter")
        point_count = len(curve.data.splines[0].bezier_points) if curve else 0
        fallback_count = int(curve.get("rigo_trim_fallback_points", 0)) if curve else 0
        distances = _raw_surface_distances_mm(scan, curve) if curve else []
        maximum = max(distances) if distances else 999.0
        passed = (
            transformed_result == {"FINISHED"}
            and fallback_result == {"FINISHED"}
            and point_count == 42
            and fallback_count > 0
            and maximum <= 1.60
        )
        lines.extend(
            (
                f"transformed_result={transformed_result}",
                f"fallback_result={fallback_result}",
                f"points={point_count}",
                f"fallback_points={fallback_count}",
                f"raw_max_mm={maximum:.3f}",
                f"PASS={passed}",
            )
        )
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
