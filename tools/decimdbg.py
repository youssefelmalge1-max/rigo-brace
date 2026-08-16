"""#49d: classify the single dual-confirmed inverted face on the decim065
commit (import_decim065.validity inv=1).  Evidence only."""

import importlib
import math
import traceback

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_OUT = r"C:\Projects\Blender Add-on Braces\decimdbg_result.txt"
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
    lib = importlib.import_module(
        "bl_ext.user_default.rigo_brace.core.region_library"
    )
    settings = bpy.context.scene.rigo_brace
    try:
        # The style the battery saved persistently.
        # Author the style exactly as the battery does.
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        src = bpy.context.active_object
        settings.scan_object = src
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        bpy.context.scene.cursor.location = (
            src.matrix_world @ src.data.vertices[9000].co
        )
        settings.region_radius = 30.0
        settings.region_magnitude = 15.0
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        bpy.ops.rigo.region_apply()
        bpy.ops.rigo.region_style_save(style_name="DBG Decim Style")
        style_id = settings.region_style
        bpy.data.objects.remove(src, do_unlink=True)
        _mark(f"style={style_id}")

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        cursor = obj.matrix_world @ obj.data.vertices[9000].co
        mod = obj.modifiers.new("QA_DEC", "DECIMATE")
        mod.ratio = 0.65
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        me = obj.data

        settings.region_style = style_id
        bpy.context.scene.cursor.location = cursor
        st = bpy.ops.rigo.region_style_import()
        _mark(f"import={st}")
        region = obj.rigo_regions[obj.rigo_region_index]
        n_orig = len(me.vertices)
        before = {v.index: v.co.copy() for v in me.vertices}
        before_n = {v.index: v.normal.copy() for v in me.vertices}
        pre_polys = [tuple(p.vertices) for p in me.polygons]
        st = bpy.ops.rigo.region_apply()
        _mark(f"commit={st} refined_added={region.refined_added} "
              f"verts {n_orig} -> {len(me.vertices)}")

        wpost = {}
        vg = obj.vertex_groups.get(region.surface_mask)
        for v in me.vertices:
            for g in v.groups:
                if g.group == vg.index:
                    wpost[v.index] = g.weight
                    break
        fp = {i for i, w in wpost.items() if w > 1e-5}
        pre_verts = [before[i] for i in range(len(before))]
        surf = BVHTree.FromPolygons(pre_verts, pre_polys, all_triangles=True)
        faces_q = [
            p for p in me.polygons if any(vi in fp for vi in p.vertices)
        ]
        nbr = {}
        for p in faces_q:
            vs = p.vertices
            for k in range(len(vs)):
                a, b = vs[k], vs[(k + 1) % len(vs)]
                key = (a, b) if a < b else (b, a)
                nbr.setdefault(key, []).append(p.index)
        for p in faces_q:
            reference = Vector()
            for vi in p.vertices:
                n = before_n.get(vi)
                if n is not None:
                    reference += n
            center = Vector()
            for vi in p.vertices:
                center += me.vertices[vi].co
            center /= len(p.vertices)
            _loc, nor, _i, _d = surf.find_nearest(center)
            by_verts = (reference.length >= 1.5
                        and p.normal.dot(reference.normalized()) < 0.0)
            by_surf = nor is not None and p.normal.dot(nor) < 0.0
            flagged = False
            path = ""
            if reference.length >= 1.5 and nor is not None:
                flagged = by_verts and by_surf
                path = "dual"
            elif reference.length < 1e-9 and by_surf:
                vs = p.vertices
                for k in range(len(vs)):
                    a, b = vs[k], vs[(k + 1) % len(vs)]
                    key = (a, b) if a < b else (b, a)
                    for q in nbr.get(key, ()):
                        if q != p.index and me.polygons[q].normal.dot(
                                p.normal) < -0.5:
                            flagged = True
                path = "allnew+fold"
            elif by_verts:
                flagged = True
                path = "verts-only"
            if flagged:
                vs = list(p.vertices)
                newv = [vi >= n_orig for vi in vs]
                ws = [round(wpost.get(vi, 0.0), 3) for vi in vs]
                els = [round((me.vertices[vs[k]].co
                              - me.vertices[vs[(k + 1) % len(vs)]].co
                              ).length * 1000.0, 2)
                       for k in range(len(vs))]
                dots = []
                for k in range(len(vs)):
                    a, b = vs[k], vs[(k + 1) % len(vs)]
                    key = (a, b) if a < b else (b, a)
                    for q in nbr.get(key, ()):
                        if q != p.index:
                            dots.append(round(me.polygons[q].normal.dot(
                                p.normal), 2))
                _mark(f"INVERTED f{p.index} path={path} new={newv} w={ws} "
                      f"edges_mm={els} area={p.area:.2e} "
                      f"nbr_dots={dots} "
                      f"ref_dot={p.normal.dot(reference.normalized()) if reference.length > 1e-9 else 999:.2f} "
                      f"surf_dot={p.normal.dot(nor):.2f}")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
