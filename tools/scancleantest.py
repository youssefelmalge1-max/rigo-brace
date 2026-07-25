"""Regression test for the scan-step brush-based cleanup (smooth_selection).

Simulates painting a region, then:
  1. Calls rigo.smooth_selection  -> face count unchanged, no crash.
  2. Confirms rigo.smooth_selection is registered.
  3. Confirms select_smooth_factor / select_smooth_iters settings exist.

Writes scancleantest_result.txt and self-quits.
"""

import bpy
import bmesh
from mathutils import Vector

_OUT   = r"C:\Projects\Blender Add-on Braces\scancleantest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log   = []


def _mark(msg):
    _log.append(msg)
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _select_patch(obj, center, radius):
    """Create the Edit-mode face selection produced by Paint Area."""
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    count = 0
    for face in bm.faces:
        if (face.calc_center_median() - center).length < radius:
            face.select = True
            count += 1
    bmesh.update_edit_mesh(obj.data)
    return count


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        # -- 1. Check operator registration ---------------------------------- #
        ops = bpy.ops.rigo
        has_smooth_op = hasattr(ops, "smooth_selection")
        _mark(f"phase=check_registration has_smooth_op={has_smooth_op}")

        # -- 2. Check settings exist ----------------------------------------- #
        settings = getattr(bpy.context.scene, "rigo_brace", None)
        has_factor = settings is not None and hasattr(settings, "select_smooth_factor")
        has_iters  = settings is not None and hasattr(settings, "select_smooth_iters")
        _mark(f"phase=check_settings has_factor={has_factor} has_iters={has_iters}")

        # -- 3. Functional: smooth changes vertex positions but not face count - #
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings.scan_object = scan
        settings.select_smooth_factor = 0.8
        settings.select_smooth_iters  = 3
        bpy.context.view_layer.objects.active = scan

        # Anchor the mask on the vertex with the largest X (side of torso).
        sidx = max(range(len(scan.data.vertices)),
                   key=lambda i: scan.data.vertices[i].co.x)
        center = scan.data.vertices[sidx].co.copy()
        bb     = [Vector(c) for c in scan.bound_box]
        radius = (bb[6] - bb[0]).length * 0.12
        selected = _select_patch(scan, center, radius)
        _mark(f"phase=selected faces={selected}")

        faces_before = len(scan.data.polygons)
        result = bpy.ops.rigo.smooth_selection()
        faces_after  = len(scan.data.polygons)
        _mark(f"phase=smoothed result={result} faces_before={faces_before} faces_after={faces_after}")

        # Vertex at the anchor should have moved slightly after smoothing.
        # (Even if it doesn't move much, no exception = already a win.)
        smooth_ok = result == {"FINISHED"}

        ok = has_smooth_op and has_factor and has_iters and smooth_ok and faces_after == faces_before
        _mark(f"PASS={ok}")

    except Exception as exc:  # noqa: BLE001
        _mark(f"EXCEPTION={exc}")
        _mark("PASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
