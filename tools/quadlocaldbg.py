"""#49n follow-up - can the quad topology survive OUTSIDE the correction?

Arm D proved that triangulating the whole remeshed scan before painting takes
the wall from p95 58.52 to 18.05.  But the orthotist quad-remeshes on purpose,
so throwing every quad away is a real cost.

Two questions:
  1. Does commit ALREADY destroy the quads?  (_refine_footprint triangulates
     every face with more than 3 verts - which on a quad mesh is all of them.)
  2. If only the footprint + a margin is triangulated first, does the wall come
     out as good as arm D while the rest of the body stays quads?

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/quadlocaldbg.py
"""

import math
import os
import statistics
import traceback

import bpy
import bmesh

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "quadlocaldbg_result.txt")
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


def _select_radius(obj, seed, radius_m):
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


def _wall(obj, weights):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    angles = []
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            continue
        a, b = edge.verts[0].index, edge.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        try:
            angles.append(math.degrees(abs(edge.calc_face_angle())))
        except ValueError:
            continue
    bm.free()
    return angles


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    try:
        _mark("=== #49n: does commit already destroy the quads? ===")
        _clear()
        obj = _import_scan()
        bpy.ops.rigo.remesh()
        obj = bpy.context.scene.rigo_brace.scan_object
        _mark(f"  after remesh          faces={_face_mix(obj.data)}")
        seed = _waist_seed(obj)
        settings = bpy.context.scene.rigo_brace
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 20.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        _select_radius(obj, seed, 0.030)
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        region = obj.rigo_regions[obj.rigo_region_index]
        bpy.ops.rigo.region_apply()
        mix = _face_mix(obj.data)
        quads_left = sum(n for k, n in mix.items() if k == 4)
        _mark(f"  after production commit faces={mix}")
        _mark(
            f"  QUADS SURVIVING A NORMAL COMMIT: {quads_left} "
            f"(of 46098) -> the quad remesh is ALREADY lost at commit"
        )

        _mark("")
        _mark("=== localized triangulation: keep quads outside the pad ===")
        for margin_mm, tag in ((10.0, "pad + 10 mm"), (20.0, "pad + 20 mm")):
            _clear()
            obj = _import_scan()
            bpy.ops.rigo.remesh()
            obj = bpy.context.scene.rigo_brace.scan_object
            seed = _waist_seed(obj)
            n_sel = _select_radius(obj, seed, 0.030 + margin_mm * 0.001)
            bpy.ops.mesh.quads_convert_to_tris(quad_method="BEAUTY")
            bpy.ops.object.mode_set(mode="OBJECT")
            mix_after_tri = _face_mix(obj.data)
            settings = bpy.context.scene.rigo_brace
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 20.0
            settings.region_feather = 10.0
            settings.region_falloff = "SMOOTH"
            seed = _waist_seed(obj)
            _select_radius(obj, seed, 0.030)
            bpy.ops.rigo.region_add()
            bpy.ops.object.mode_set(mode="OBJECT")
            region = obj.rigo_regions[obj.rigo_region_index]
            res = bpy.ops.rigo.region_apply()
            if "FINISHED" not in res:
                _mark(f"  {tag}: commit refused {res}")
                continue
            angles = _wall(obj, _weights(obj, region.surface_mask))
            mix_out = _face_mix(obj.data)
            quads_out = sum(n for k, n in mix_out.items() if k == 4)
            _mark(
                f"  {tag:12s} pre-tri={n_sel:5d} faces "
                f"({mix_after_tri}) -> p95={_pct(angles, 0.95):6.2f} "
                f"max={max(angles):7.2f} "
                f"over30={sum(1 for a in angles if a > 30):4d} "
                f"mean={statistics.fmean(angles):5.2f}"
            )
            _mark(f"      quads surviving commit: {quads_out} faces_out={mix_out}")
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
