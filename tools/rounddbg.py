"""#49g: instrument _round_selection_outline itself — is the field being
built, blurred and thresholded at all?"""

import importlib
import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\rounddbg_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    so = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.select_ops"
    )
    settings = bpy.context.scene.rigo_brace
    try:
        bpy.ops.wm.stl_import(filepath=A_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        me = obj.data
        cos = [obj.matrix_world @ v.co for v in me.vertices]
        z_min, z_max = min(c.z for c in cos), max(c.z for c in cos)
        y_min, y_max = min(c.y for c in cos), max(c.y for c in cos)
        x_min, x_max = min(c.x for c in cos), max(c.x for c in cos)
        kd = kdtree.KDTree(len(me.vertices))
        for v in me.vertices:
            kd.insert(obj.matrix_world @ v.co, v.index)
        kd.balance()
        _co, seed, _d = kd.find(Vector((
            (x_min + x_max) * 0.5,
            y_min + 0.10 * (y_max - y_min),
            z_min + 0.45 * (z_max - z_min),
        )))
        centre = me.vertices[seed].co.copy()

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()
        for f in bm.faces:
            if (f.calc_center_median() - centre).length < 0.059:
                f.select = True
        bmesh.update_edit_mesh(me)

        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        sel0 = {f.index for f in bm.faces if f.select}
        _mark(f"painted faces={len(sel0)} total={len(bm.faces)}")

        # replicate the internals with instrumentation
        centres = {f.index: f.calc_center_median() for f in bm.faces}
        neighbours = {}
        for face in bm.faces:
            near = []
            for e in face.edges:
                for other in e.link_faces:
                    if other is not face:
                        near.append(other.index)
            neighbours[face.index] = near
        border = [
            i for i in neighbours
            if any((n in sel0) != (i in sel0) for n in neighbours[i])
        ]
        spacing_all = []
        for i in border[:400]:
            for n in neighbours[i]:
                spacing_all.append((centres[i] - centres[n]).length)
        _mark(
            f"border faces={len(border)} mean dual spacing="
            f"{sum(spacing_all)/max(1,len(spacing_all))*1000:.2f}mm"
        )

        for mm in (4.0, 6.0, 10.0):
            bpy.ops.object.mode_set(mode="EDIT")
            bm2 = bmesh.from_edit_mesh(me)
            bm2.faces.ensure_lookup_table()
            for f in bm2.faces:
                f.select = f.index in sel0
            bm2.select_flush_mode()
            bmesh.update_edit_mesh(me)
            bm2 = bmesh.from_edit_mesh(me)
            bm2.faces.ensure_lookup_table()
            added, removed = so._round_selection_outline(bm2, mm * 0.001)
            after = {f.index for f in bm2.faces if f.select}
            _mark(
                f"radius={mm:>4.0f}mm -> added={added} removed={removed} "
                f"faces {len(sel0)} -> {len(after)} "
                f"symmetric_diff={len(after ^ sel0)}"
            )
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
