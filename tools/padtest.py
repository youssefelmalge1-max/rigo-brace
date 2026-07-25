"""Functional test for the outline-shape pad system.

Select a library entry (favourites must pre-fill), place it at a surface point
(must drape onto the scan), apply (surface inside dents inward, far side
untouched).  Writes padtest_result.txt then quits.  GUI only.
"""

import bpy
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\padtest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()

        # ---- selecting a library entry pre-fills its favourites ---- #
        settings.pad_depth = 1.0   # scramble first
        settings.pad_type = "BLANK_ROUNDED_RECTANGLE"
        prefill_ok = (
            settings.pad_kind == "PRESSURE"
            and settings.pad_depth > 1.0
        )
        _mark(f"phase=prefill kind={settings.pad_kind} depth={settings.pad_depth} "
              f"prefill_ok={prefill_ok}")

        # ---- place at the max +X surface point ---- #
        settings.pad_depth = 10.0
        settings.pad_size = 90.0
        mw = scan.matrix_world
        verts = [mw @ v.co for v in scan.data.vertices]
        idx = max(range(len(verts)), key=lambda i: verts[i].x)
        before = verts[idx].copy()
        idx_far = min(range(len(verts)), key=lambda i: verts[i].x)
        far_before = verts[idx_far].copy()
        centroid = sum(verts, Vector()) / len(verts)

        bpy.ops.rigo.add_pad(location=before, use_location=True)
        pad = settings.active_pad
        placed_ok = pad is not None and pad.type == "CURVE" and pad.get("rigo_pad_id")
        n_points = len(pad.data.splines[0].bezier_points) if placed_ok else 0

        # Every control point must be draped onto the surface (<= 4 mm away).
        deps = bpy.context.evaluated_depsgraph_get()
        inv = scan.matrix_world.inverted()
        max_gap = 0.0
        for spline in pad.data.splines:
            for bp in spline.bezier_points:
                world = pad.matrix_world @ bp.co
                ok, loc, _n, _i = scan.closest_point_on_mesh(
                    inv @ world, depsgraph=deps
                )
                if ok:
                    gap = (scan.matrix_world @ loc - world).length
                    max_gap = max(max_gap, gap)
        drape_ok = placed_ok and n_points >= 4 and max_gap < 0.004
        _mark(f"phase=placed points={n_points} max_gap={max_gap*1000:.2f}mm "
              f"drape_ok={drape_ok}")

        # ---- apply: dent inside, no effect on the far wall ---- #
        bpy.ops.rigo.apply_pads()
        after = mw @ scan.data.vertices[idx].co
        far_after = mw @ scan.data.vertices[idx_far].co
        moved = (after - before).length * 1000.0
        far_moved = (far_after - far_before).length * 1000.0
        inward = (after - centroid).length < (before - centroid).length
        apply_ok = moved > 0.5 and inward and far_moved < 0.05
        _mark(f"phase=applied moved={moved:.2f}mm inward={inward} "
              f"far_moved={far_moved:.3f}mm apply_ok={apply_ok}")

        _mark(f"PASS={prefill_ok and drape_ok and apply_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
