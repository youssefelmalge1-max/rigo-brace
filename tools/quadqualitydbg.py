"""#49n - why is the QUAD (remeshed) route's committed wall so much worse?

Measured after the #49m crash fix: remesh -> paint -> commit gives wall
p95 59.61 / max 134.59 / 86 edges over 30 deg, against 17.57 / 38.76 / 8 on the
raw triangle scan.  The orthotist works on quad-remeshed scans, so this is the
route that matters most.

Arms, all on the same body and the same painted footprint:
  A raw triangle scan (reference)
  B remeshed quad scan, production
  C remeshed quad scan, refinement disabled
  D remeshed quad scan, triangulated BEFORE painting

Also localises the damage: are the bad dihedrals on REFINEMENT-BORN edges or on
edges that already existed?

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/quadqualitydbg.py
"""

import math
import os
import statistics
import traceback

import bpy
import bmesh

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "quadqualitydbg_result.txt")
_A_SCAN = os.path.join(_ROOT, "A type model.stl")
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _pct(values, fraction):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * fraction))]


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
    band = [v for v in me.vertices
            if abs(v.co.z - (zmin + 0.45 * (zmax - zmin))) < 0.01]
    return max(band or list(me.vertices), key=lambda v: v.co.x).index


def _face_mix(me):
    mix = {}
    for poly in me.polygons:
        mix[len(poly.vertices)] = mix.get(len(poly.vertices), 0) + 1
    return mix


def _paint(obj, seed, radius_m):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    origin = bm.verts[seed].co.copy()
    n = 0
    for face in bm.faces:
        if (face.calc_center_median() - origin).length <= radius_m:
            face.select = True
            n += 1
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    return n


def _weights(obj, mask):
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


def _wall(obj, weights, n_orig):
    """Wall dihedrals, split by whether the edge is refinement-born."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    allang, newang, oldang = [], [], []
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            continue
        a, b = edge.verts[0].index, edge.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        try:
            ang = math.degrees(abs(edge.calc_face_angle()))
        except ValueError:
            continue
        allang.append(ang)
        if a >= n_orig or b >= n_orig:
            newang.append(ang)
        else:
            oldang.append(ang)
    bm.free()
    return allang, newang, oldang


def _report(tag, obj, weights, n_orig, extra=""):
    allang, newang, oldang = _wall(obj, weights, n_orig)
    if not allang:
        _mark(f"  {tag}: no wall edges {extra}")
        return
    _mark(
        f"  {tag:34s} n={len(allang):4d} p95={_pct(allang, 0.95):6.2f} "
        f"max={max(allang):7.2f} over30={sum(1 for a in allang if a > 30):4d} "
        f"mean={statistics.fmean(allang):5.2f} {extra}"
    )
    if newang and oldang:
        _mark(
            f"      refinement-born edges n={len(newang):4d} "
            f"p95={_pct(newang, 0.95):6.2f} max={max(newang):7.2f}  |  "
            f"pre-existing edges n={len(oldang):4d} "
            f"p95={_pct(oldang, 0.95):6.2f} max={max(oldang):7.2f}"
        )


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    try:
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops")
        real_refine = ro._refine_footprint

        def build(remesh, triangulate, no_refine, tag):
            _clear()
            obj = _import_scan()
            if remesh:
                bpy.ops.rigo.remesh()
                obj = bpy.context.scene.rigo_brace.scan_object
            if triangulate:
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.mesh.quads_convert_to_tris(quad_method="BEAUTY")
                bpy.ops.object.mode_set(mode="OBJECT")
            mix = _face_mix(obj.data)
            seed = _waist_seed(obj)
            settings = bpy.context.scene.rigo_brace
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 20.0
            settings.region_feather = 10.0
            settings.region_falloff = "SMOOTH"
            painted = _paint(obj, seed, 0.030)
            bpy.ops.rigo.region_add()
            bpy.ops.object.mode_set(mode="OBJECT")
            region = obj.rigo_regions[obj.rigo_region_index]
            n_orig = len(obj.data.vertices)
            if no_refine:
                def stub(*a, **k):
                    return 0, 0.0
                ro._refine_footprint = stub
            try:
                res = bpy.ops.rigo.region_apply()
            finally:
                ro._refine_footprint = real_refine
            if "FINISHED" not in res:
                _mark(f"  {tag}: commit refused {res}")
                return
            added = len(obj.data.vertices) - n_orig
            _report(
                tag, obj, _weights(obj, region.surface_mask), n_orig,
                extra=f"faces_in={mix} painted={painted} added={added}",
            )
            _mark(f"      faces_out={_face_mix(obj.data)}")

        _mark("=== #49n quad-route quality ablation (A-model waist, 20/10) ===")
        build(False, False, False, "A raw triangles, production")
        build(True, False, False, "B remeshed quads, production")
        build(True, False, True, "C remeshed quads, no refinement")
        build(True, True, False, "D remeshed+triangulated, production")
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
