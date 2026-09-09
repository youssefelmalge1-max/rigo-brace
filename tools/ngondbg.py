"""#54 Task 3 probe 3: what does beauty-only triangulation ship on the coarse
Brace Sample route, versus the hand split of unlifted midpoint quads?

Refines the same painted region twice on copies — current rule vs plain
bmesh.ops.triangulate — and counts non-manifold edges, zero-area faces and
needle triangles in the refined footprint.  Writes ngondbg_result.txt.
"""

import math
import traceback

import bpy
import bmesh

_OUT = r"C:\Projects\Blender Add-on Braces\ngondbg_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []
COUNT = {"hand": 0, "quads": 0}


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _paint_patch(scan, seed_vertex=9000, n_faces=300):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(scan.data)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    seed = bm.verts[seed_vertex].link_faces[0]
    patch = {seed}
    frontier = [seed]
    while len(patch) < n_faces and frontier:
        nxt = []
        for f in frontier:
            for e in f.edges:
                for lf in e.link_faces:
                    if lf not in patch:
                        patch.add(lf)
                        nxt.append(lf)
        frontier = nxt
    for f in patch:
        f.select = True
    bmesh.update_edit_mesh(scan.data)


def _quality(me, gi, n_orig):
    bm = bmesh.new()
    bm.from_mesh(me)
    deform = bm.verts.layers.deform.verify()
    nonman = sum(1 for e in bm.edges if not e.is_manifold)
    zero = 0
    needles = 0
    minang = 180.0
    touched = 0
    for f in bm.faces:
        if not any(v.index >= n_orig or gi in v[deform] for v in f.verts):
            continue
        touched += 1
        area = f.calc_area() * 1e6
        if area < 1e-4:
            zero += 1
        angs = []
        for l in f.loops:
            try:
                angs.append(math.degrees(l.calc_angle()))
            except ValueError:
                angs.append(0.0)
        a = min(angs) if angs else 0.0
        minang = min(minang, a)
        if a < 2.0:
            needles += 1
    bm.free()
    return nonman, zero, needles, minang, touched


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops"
        )
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        _paint_patch(scan)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 20.0
        settings.region_feather = 15.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        region = scan.rigo_regions[scan.rigo_region_index]
        gi = scan.vertex_groups.get(region.surface_mask).index
        me = scan.data
        n_orig = len(me.vertices)
        field = ro._authored_rim_field(me, gi, region)
        _mark(f"fixture verts={n_orig} edge_mm={region.edge_mm:.2f} field={'yes' if field else 'None'}")

        orig_split = ro._split_refined_ngons

        def counting(bm, ngons, fresh):
            COUNT["quads"] += sum(1 for f in ngons if len(f.verts) == 4)
            before = len(bm.faces)
            orig_split(bm, ngons, fresh)
            return None

        # A: current rule (count hand splits by wrapping face_split)
        import bmesh.utils as bu
        orig_face_split = bu.face_split

        def fs(*a, **k):
            COUNT["hand"] += 1
            return orig_face_split(*a, **k)

        bu.face_split = fs
        ro._split_refined_ngons = counting
        copy_a = me.copy()
        added_a, h_a = ro._refine_footprint(copy_a, gi, -0.020, field=field)
        bu.face_split = orig_face_split
        qa = _quality(copy_a, gi, n_orig)
        _mark(f"A current rule: added={added_a} quads={COUNT['quads']} hand_split={COUNT['hand']} "
              f"nonman={qa[0]} zero_area={qa[1]} needles<2deg={qa[2]} min_angle={qa[3]:.2f} faces={qa[4]}")

        # B: beauty only
        ro._split_refined_ngons = lambda bm, ngons, fresh: bmesh.ops.triangulate(bm, faces=ngons)
        copy_b = me.copy()
        added_b, h_b = ro._refine_footprint(copy_b, gi, -0.020, field=field)
        qb = _quality(copy_b, gi, n_orig)
        _mark(f"B beauty only : added={added_b} nonman={qb[0]} zero_area={qb[1]} "
              f"needles<2deg={qb[2]} min_angle={qb[3]:.2f} faces={qb[4]}")
        ro._split_refined_ngons = orig_split
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
