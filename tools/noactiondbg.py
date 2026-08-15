"""#49c field report repro: big painted 20/10 pressure on the A model —
orthotist reports "no action at all".  Times every stage.  Evidence only."""

import os
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\noactiondbg_result.txt"
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
    settings = bpy.context.scene.rigo_brace
    try:
        t0 = time.perf_counter()
        bpy.ops.wm.stl_import(filepath=A_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        _mark(f"import+units {time.perf_counter() - t0:.1f}s "
              f"verts={len(obj.data.vertices)}")

        # ~59 mm painted patch at the front waist (screenshot config).
        cos = [obj.matrix_world @ v.co for v in obj.data.vertices]
        z_min = min(c.z for c in cos)
        z_max = max(c.z for c in cos)
        y_min, y_max = min(c.y for c in cos), max(c.y for c in cos)
        x_min, x_max = min(c.x for c in cos), max(c.x for c in cos)
        cx = (x_min + x_max) * 0.5
        dz, dy = z_max - z_min, y_max - y_min
        target = Vector((cx, y_min + 0.10 * dy, z_min + 0.45 * dz))
        kd = kdtree.KDTree(len(obj.data.vertices))
        for v in obj.data.vertices:
            kd.insert(obj.matrix_world @ v.co, v.index)
        kd.balance()
        _co, seed, _d = kd.find(target)
        center = obj.data.vertices[seed].co.copy()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        n_sel = 0
        for f in bm.faces:
            if (f.calc_center_median() - center).length < 0.059:
                f.select = True
                n_sel += 1
        bmesh.update_edit_mesh(obj.data)
        _mark(f"painted {n_sel} faces (59mm radius)")

        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 20.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        t0 = time.perf_counter()
        st = bpy.ops.rigo.region_add()
        _mark(f"region_add {st} {time.perf_counter() - t0:.1f}s")
        region = obj.rigo_regions[obj.rigo_region_index]
        pv = obj.modifiers.get(f"RIGO_REGION_PREVIEW_{region.surface_mask}")
        _mark(f"preview modifier present={pv is not None} "
              f"strength={0 if pv is None else pv.strength}")

        # Per-stage timing: wrap the pipeline helpers with counters.
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops"
        )
        totals = {}

        def _wrap(name):
            orig = getattr(ro, name)

            def timed(*a, **kw):
                t = time.perf_counter()
                out = orig(*a, **kw)
                rec = totals.setdefault(name, [0.0, 0])
                rec[0] += time.perf_counter() - t
                rec[1] += 1
                return out
            setattr(ro, name, timed)

        for name in ("_refine_footprint", "_repair_folds", "_faired_normals",
                     "_footprint_self_intersections", "_cross_sheet_pairs",
                     "_wall_blocked_points", "_static_faces_bvh",
                     "_folded_pairs", "_edge_face_pairs"):
            _wrap(name)

        n0 = len(obj.data.vertices)
        t0 = time.perf_counter()
        try:
            st = bpy.ops.rigo.region_apply()
        except RuntimeError as exc:
            _mark(f"commit RAISED after {time.perf_counter() - t0:.1f}s: "
                  f"{str(exc).strip()[:200]}")
            st = None
        if st is not None:
            _mark(f"commit {st} {time.perf_counter() - t0:.1f}s "
                  f"verts {n0} -> {len(obj.data.vertices)} "
                  f"refined_added={region.refined_added}")
        for name, (secs, calls) in sorted(
                totals.items(), key=lambda kv: -kv[1][0]):
            _mark(f"  {name}: {secs:.2f}s x{calls}")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
