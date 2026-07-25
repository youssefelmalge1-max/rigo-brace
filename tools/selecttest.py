"""Functional test for the Edit-Mode native paint-select system.

A script can't mouse-drag, so we select a ring of faces programmatically with
BMesh, then exercise each region action and confirm the geometry changed.
Writes selecttest_result.txt and self-quits.
"""

import bmesh
import bpy
from mathutils import Vector

_OUT    = r"C:\Projects\Blender Add-on Braces\selecttest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES  = {"n": 0}
_log    = []


def _mark(msg):
    _log.append(msg)
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _select_ring(obj, center, radius):
    """Select faces whose median centre is within radius of center.
    Automatically selects incident vertices/edges for transform ops."""
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    n = 0
    for face in bm.faces:
        if (face.calc_center_median() - center).length < radius:
            face.select = True
            n += 1
        else:
            face.select = False
    for vert in bm.verts:
        vert.select = any(f.select for f in vert.link_faces)
    for edge in bm.edges:
        edge.select = all(v.select for v in edge.verts)
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return n, bm


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        # ---- import scan ---- #
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        bpy.context.scene.rigo_brace.scan_object = scan
        bpy.context.scene.rigo_brace.select_depth = 8.0
        bpy.context.scene.rigo_brace.select_thickness = 6.0
        bpy.context.view_layer.objects.active = scan

        # ---- derive a ring centre on the mesh surface ---- #
        bb     = [Vector(c) for c in scan.bound_box]
        size   = (bb[6] - bb[0]).length
        radius = size * 0.10

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.select_all(action="DESELECT")

        bm_tmp = bmesh.from_edit_mesh(scan.data)
        bm_tmp.faces.ensure_lookup_table()
        # Use face with largest X as the ring centre (side of the torso).
        target_face = max(bm_tmp.faces, key=lambda f: f.calc_center_median().x)
        center      = target_face.calc_center_median().copy()
        sidx        = target_face.verts[0].index   # a representative vertex

        n_sel, bm = _select_ring(scan, center, radius)
        _mark(f"phase=selected faces={n_sel} center_x={center.x:.3f}")

        # ---- Push Out (execute path: BMesh fallback inside the op) ---- #
        vpos_before = bm.verts[sidx].co.copy()
        bpy.ops.rigo.push_selection(direction="OUT")
        bm2 = bmesh.from_edit_mesh(scan.data)
        bm2.verts.ensure_lookup_table()
        vpos_after = bm2.verts[sidx].co.copy()
        moved = (vpos_after - vpos_before).length
        _mark(f"phase=pushed moved={moved:.5f}")

        # ---- Thicken: count faces before and after ---- #
        bpy.ops.object.mode_set(mode="OBJECT")
        faces_before = len(scan.data.polygons)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.select_all(action="DESELECT")
        _select_ring(scan, center, radius)
        bpy.ops.rigo.thicken_selection()
        bpy.ops.object.mode_set(mode="OBJECT")
        faces_after = len(scan.data.polygons)
        _mark(f"phase=thickened before={faces_before} after={faces_after}")

        # ---- Delete: faces should drop ---- #
        fb = len(scan.data.polygons)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.select_all(action="DESELECT")
        _select_ring(scan, center, radius)
        bpy.ops.rigo.delete_selection()
        bpy.ops.object.mode_set(mode="OBJECT")
        fa = len(scan.data.polygons)
        _mark(f"phase=deleted before={fb} after={fa}")

        ok = (
            n_sel > 0
            and moved > 1e-4
            and faces_after > faces_before
            and fa < fb
        )
        _mark(f"PASS={ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
