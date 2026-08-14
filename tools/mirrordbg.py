"""Diagnose the Wave 2 mirror placement gap on the painted-patch case."""

import importlib
import json
import traceback

import bpy
import bmesh
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\mirrordbg_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
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
    ro = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )
    try:
        settings = bpy.context.scene.rigo_brace
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings.scan_object = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        xs = [v.co.x for v in scan.data.vertices]
        _mark(f"scan x range: [{min(xs):.3f}, {max(xs):.3f}] "
              f"mid={(min(xs) + max(xs)) * 0.5:.3f} "
              f"matrix_world={[list(r) for r in scan.matrix_world]}")

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(scan.data)
        bm.verts.ensure_lookup_table()
        frontier = [bm.verts[9000].link_faces[0]]
        selected = set(frontier)
        while len(selected) < 300 and frontier:
            nxt = []
            for f in frontier:
                for e in f.edges:
                    for lf in e.link_faces:
                        if lf not in selected:
                            selected.add(lf)
                            nxt.append(lf)
            frontier = nxt
        for f in selected:
            f.select = True
        bmesh.update_edit_mesh(scan.data)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 7.0
        settings.region_feather = 10.0
        bpy.ops.rigo.region_add()
        src = scan.rigo_regions[scan.rigo_region_index]
        snap = json.loads(scan["rigo_style_src_" + src.surface_mask])
        anchor = Vector(snap["anchor_world"])
        _mark(f"src.center={tuple(round(c, 4) for c in src.center)} "
              f"anchor_world={tuple(round(c, 4) for c in anchor)} "
              f"max_geodesic={snap.get('max_geodesic_mm')}")
        mirrored = Vector((-anchor.x, anchor.y, anchor.z))
        target, normal = ro._target_surface(scan, mirrored)
        _mark(f"reflected={tuple(round(c, 4) for c in mirrored)} "
              f"projected={tuple(round(c, 4) for c in target)} "
              f"projection_gap={(target - mirrored).length * 1000.0:.1f}mm")
        bpy.ops.rigo.region_apply()
        bpy.ops.rigo.region_mirror()
        mir = scan.rigo_regions[scan.rigo_region_index]

        def centroid(mask):
            vg = scan.vertex_groups.get(mask)
            acc = Vector()
            n = 0
            for v in scan.data.vertices:
                for g in v.groups:
                    if g.group == vg.index and g.weight > 0.3:
                        acc += v.co
                        n += 1
                        break
            return acc / n, n

        c_s, n_s = centroid(src.surface_mask)
        c_m, n_m = centroid(mir.surface_mask)
        _mark(f"src strong centroid={tuple(round(c, 4) for c in c_s)} n={n_s}")
        _mark(f"mir strong centroid={tuple(round(c, 4) for c in c_m)} n={n_m}")
        _mark(f"footprint gap={(Vector((-c_s.x, c_s.y, c_s.z)) - c_m).length * 1000.0:.1f}mm")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
