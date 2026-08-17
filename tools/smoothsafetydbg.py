"""#49l — why does 'Smooth Vertices' collapse the patient mesh?

The orthotist drove Blender's native Mesh > Smooth Vertices to factor 1.9146
and the corrected pad exploded into spikes.  Blender's operator is a plain
Laplacian step per pass:

    p  <-  p + factor * (mean(neighbours) - p)

which is a contraction only for 0 < factor < 1.  At factor = 1 a vertex jumps
exactly onto its neighbours' centroid (all detail gone in one pass); above 1 it
OVERSHOOTS past the centroid, and the overshoot is amplified every pass — the
classic divergent Jacobi iteration.  This probe measures that on the real
committed pad instead of asserting it, and measures our own Smooth Area at its
maximum settings for comparison.

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/smoothsafetydbg.py
"""

import math
import os
import statistics
import traceback

import bpy
import bmesh
from mathutils import Vector

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "smoothsafetydbg_result.txt")
_A_SCAN = os.path.join(_ROOT, "A type model.stl")
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def _import_scan():
    bpy.ops.wm.stl_import(filepath=_A_SCAN)
    obj = bpy.context.active_object
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    return obj


def _waist_seed(obj):
    me = obj.data
    zs = [v.co.z for v in me.vertices]
    zmin, zmax = min(zs), max(zs)
    target_z = zmin + 0.45 * (zmax - zmin)
    band = [v for v in me.vertices if abs(v.co.z - target_z) < 0.01]
    if not band:
        band = list(me.vertices)
    return max(band, key=lambda v: v.co.x).index


def _paint_radius(obj, seed_index, radius_m):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    origin = bm.verts[seed_index].co.copy()
    for face in bm.faces:
        if (face.calc_center_median() - origin).length <= radius_m:
            face.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def _group_weights(obj, mask):
    vg = obj.vertex_groups.get(mask)
    if vg is None:
        return {}
    gi = vg.index
    out = {}
    for vertex in obj.data.vertices:
        for group in vertex.groups:
            if group.group == gi:
                out[vertex.index] = group.weight
                break
    return out


def _select_footprint(obj, weights):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    for face in bm.faces:
        if all(weights.get(v.index, 0.0) > 0.05 for v in face.verts):
            face.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def _health(obj, before):
    """Damage report against the pre-smoothing coordinates."""
    me = obj.data
    moved = [
        (me.vertices[i].co - co).length * 1000.0
        for i, co in before.items()
        if i < len(me.vertices)
    ]
    bm = bmesh.new()
    bm.from_mesh(me)
    edges = [e.calc_length() * 1000.0 for e in bm.edges]
    areas = [f.calc_area() for f in bm.faces]
    spikes = 0
    for face in bm.faces:
        lengths = [e.calc_length() for e in face.edges]
        if not lengths or min(lengths) <= 1e-12:
            spikes += 1
            continue
        if max(lengths) / min(lengths) > 20.0:
            spikes += 1
    bm.free()
    return {
        "max_move_mm": max(moved) if moved else 0.0,
        "mean_move_mm": statistics.fmean(moved) if moved else 0.0,
        "max_edge_mm": max(edges) if edges else 0.0,
        "min_area": min(areas) if areas else 0.0,
        "slivers": spikes,
    }


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    try:
        def build():
            _clear()
            obj = _import_scan()
            seed = _waist_seed(obj)
            settings = bpy.context.scene.rigo_brace
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 20.0
            settings.region_feather = 10.0
            settings.region_falloff = "SMOOTH"
            _paint_radius(obj, seed, 0.030)
            bpy.ops.rigo.region_add()
            bpy.ops.object.mode_set(mode="OBJECT")
            region = obj.rigo_regions[obj.rigo_region_index]
            bpy.ops.rigo.region_apply()
            weights = _group_weights(obj, region.surface_mask)
            _select_footprint(obj, weights)
            before = {v.index: v.co.copy() for v in obj.data.vertices}
            return obj, weights, before

        _mark("=== Blender's native Mesh > Smooth Vertices ===")
        _mark("    p <- p + factor * (mean(neighbours) - p),  5 passes")
        _mark("")
        for factor in (0.5, 0.9, 1.0, 1.5, 1.9146):
            obj, weights, before = build()
            bpy.ops.mesh.select_all(action="DESELECT")
            _select_footprint(obj, weights)
            try:
                bpy.ops.mesh.vertices_smooth(factor=factor, repeat=5)
            except Exception as exc:  # noqa: BLE001
                _mark(f"  factor={factor}: raised {exc!r}")
                continue
            bpy.ops.object.mode_set(mode="OBJECT")
            health = _health(obj, before)
            verdict = (
                "COLLAPSED" if health["slivers"] > 20
                or health["max_move_mm"] > 50.0 else "bounded"
            )
            _mark(
                f"  factor={factor:<7} max_move={health['max_move_mm']:8.2f}mm "
                f"mean_move={health['mean_move_mm']:6.2f}mm "
                f"max_edge={health['max_edge_mm']:8.2f}mm "
                f"slivers={health['slivers']:5d}  -> {verdict}"
            )

        _mark("")
        _mark("=== our Smooth Area, at the maximum the UI allows ===")
        for factor, iters in ((0.5, 5), (1.0, 5), (1.0, 50)):
            obj, weights, before = build()
            settings = bpy.context.scene.rigo_brace
            settings.select_smooth_factor = factor
            settings.select_smooth_iters = iters
            bpy.ops.mesh.select_all(action="DESELECT")
            _select_footprint(obj, weights)
            res = bpy.ops.rigo.smooth_selection()
            bpy.ops.object.mode_set(mode="OBJECT")
            health = _health(obj, before)
            verdict = (
                "COLLAPSED" if health["slivers"] > 20
                or health["max_move_mm"] > 50.0 else "bounded"
            )
            _mark(
                f"  strength={factor} passes={iters:<3} "
                f"max_move={health['max_move_mm']:8.2f}mm "
                f"mean_move={health['mean_move_mm']:6.2f}mm "
                f"max_edge={health['max_edge_mm']:8.2f}mm "
                f"slivers={health['slivers']:5d}  -> {verdict} {res}"
            )
        _mark("")
        _mark("  (UI caps Smooth Strength at 1.0 and Passes at 50 —"
              " core/__init__.py)")

        # The orthotist's scan is QUAD-REMESHED and much finer than the raw
        # STL.  Divergence per pass is a fixed RATIO, so on a fine mesh the
        # overshoot is large compared with the edge length — the shredding
        # should get dramatically worse with density and with passes.
        _mark("")
        _mark("=== does density / pass count amplify it? (factor 1.9146) ===")
        for repeat in (1, 5, 10, 20):
            obj, weights, before = build()
            bpy.ops.mesh.select_all(action="DESELECT")
            _select_footprint(obj, weights)
            bpy.ops.mesh.vertices_smooth(factor=1.9146, repeat=repeat)
            bpy.ops.object.mode_set(mode="OBJECT")
            health = _health(obj, before)
            verdict = (
                "COLLAPSED" if health["slivers"] > 20
                or health["max_move_mm"] > 50.0 else "bounded"
            )
            _mark(
                f"  coarse STL  repeat={repeat:<3} "
                f"max_move={health['max_move_mm']:9.2f}mm "
                f"max_edge={health['max_edge_mm']:9.2f}mm "
                f"slivers={health['slivers']:5d}  -> {verdict}"
            )

        for repeat in (5, 10):
            _clear()
            obj = _import_scan()
            settings = bpy.context.scene.rigo_brace
            try:
                settings.remesh_voxel = 2.0
            except Exception:  # noqa: BLE001
                pass
            res = bpy.ops.rigo.remesh()
            obj = bpy.context.scene.rigo_brace.scan_object
            faces_after = len(obj.data.polygons)
            seed = _waist_seed(obj)
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 20.0
            settings.region_feather = 10.0
            settings.region_falloff = "SMOOTH"
            _paint_radius(obj, seed, 0.030)
            bpy.ops.rigo.region_add()
            bpy.ops.object.mode_set(mode="OBJECT")
            region = obj.rigo_regions[obj.rigo_region_index]
            bpy.ops.rigo.region_apply()
            weights = _group_weights(obj, region.surface_mask)
            _select_footprint(obj, weights)
            before = {v.index: v.co.copy() for v in obj.data.vertices}
            bpy.ops.mesh.vertices_smooth(factor=1.9146, repeat=repeat)
            bpy.ops.object.mode_set(mode="OBJECT")
            health = _health(obj, before)
            verdict = (
                "COLLAPSED" if health["slivers"] > 20
                or health["max_move_mm"] > 50.0 else "bounded"
            )
            _mark(
                f"  REMESHED ({faces_after} faces) repeat={repeat:<3} "
                f"max_move={health['max_move_mm']:9.2f}mm "
                f"max_edge={health['max_edge_mm']:9.2f}mm "
                f"slivers={health['slivers']:5d}  -> {verdict} remesh={res}"
            )
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
