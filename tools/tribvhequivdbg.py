"""#49m — is `_tri_bvh` bit-identical to the code it replaced, on TRIANGLES?

The whole regression battery runs on triangle meshes.  If the new
fan-triangulating BVH helper returns exactly what the three old inlined
versions returned whenever every polygon is already a triangle, then the quad
fix cannot have changed any existing covered behaviour — and the battery's
value as evidence is preserved without needing to re-run it on a machine that
is currently out of RAM.

This compares, on a real painted region:

  * `_footprint_self_intersections`  new vs an inline copy of the OLD body
  * `_static_faces_bvh`              returned face list, element by element
  * `_cross_sheet_pairs`             resulting pair set

Cheap: one scan, one region, no subdivision, no repeated Blender launches.

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/tribvhequivdbg.py
"""

import os
import traceback

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "tribvhequivdbg_result.txt")
_SCAN = os.path.join(_ROOT, "Brace Sample.stl")
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


# ---- verbatim copies of the PRE-#49m bodies, for differential comparison ---
def old_footprint_self_intersections(me, member, faces=None):
    if faces is None:
        faces = [
            p for p in me.polygons if any(vi in member for vi in p.vertices)
        ]
    if not faces:
        return set()
    used = sorted({vi for p in faces for vi in p.vertices})
    local = {vi: n for n, vi in enumerate(used)}
    verts = [me.vertices[vi].co for vi in used]
    polys = [tuple(local[vi] for vi in p.vertices) for p in faces]
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=True)
    bad = set()
    for a, b in tree.overlap(tree):
        if a == b or set(polys[a]) & set(polys[b]):
            continue
        bad.add(faces[a].index)
        bad.add(faces[b].index)
    return bad


def old_static_faces_bvh(me, member):
    faces = [
        p for p in me.polygons if not any(vi in member for vi in p.vertices)
    ]
    if not faces:
        return None, []
    used = sorted({vi for p in faces for vi in p.vertices})
    local = {vi: n for n, vi in enumerate(used)}
    verts = [me.vertices[vi].co.copy() for vi in used]
    polys = [tuple(local[vi] for vi in p.vertices) for p in faces]
    return BVHTree.FromPolygons(verts, polys, all_triangles=True), faces


def old_cross_sheet_pairs(me, static_tree, static_faces, affected):
    if static_tree is None or not affected:
        return set()
    used = sorted({vi for p in affected for vi in p.vertices})
    local = {vi: n for n, vi in enumerate(used)}
    verts = [me.vertices[vi].co.copy() for vi in used]
    polys = [tuple(local[vi] for vi in p.vertices) for p in affected]
    moved = BVHTree.FromPolygons(verts, polys, all_triangles=True)
    pairs = set()
    for a, b in moved.overlap(static_tree):
        face_a = affected[a]
        face_b = static_faces[b]
        if set(face_a.vertices) & set(face_b.vertices):
            continue
        pairs.add((face_a.index, face_b.index))
    return pairs


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    try:
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops")
        _mark(f"_tri_bvh present in installed build: {hasattr(ro, '_tri_bvh')}")

        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.ops.wm.stl_import(filepath=_SCAN)
        obj = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = obj
        bpy.context.view_layer.objects.active = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        me = obj.data
        mix = {}
        for poly in me.polygons:
            mix[len(poly.vertices)] = mix.get(len(poly.vertices), 0) + 1
        _mark(f"fixture faces={mix}")

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        frontier = [bm.verts[9000].link_faces[0]]
        patch = set(frontier)
        while len(patch) < 400 and frontier:
            nxt = []
            for face in frontier:
                for edge in face.edges:
                    for lf in edge.link_faces:
                        if lf not in patch:
                            patch.add(lf)
                            nxt.append(lf)
            frontier = nxt
        for face in patch:
            face.select = True
        bm.select_flush_mode()
        bmesh.update_edit_mesh(me)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 15.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        region = obj.rigo_regions[obj.rigo_region_index]
        group = obj.vertex_groups.get(region.surface_mask)
        member = set()
        for vertex in me.vertices:
            for g in vertex.groups:
                if g.group == group.index and g.weight > 0.0:
                    member.add(vertex.index)
                    break
        _mark(f"region members={len(member)}")

        # --- 1. self-intersections -------------------------------------
        new_bad = ro._footprint_self_intersections(me, member)
        old_bad = old_footprint_self_intersections(me, member)
        _mark(
            f"self_intersections  new={len(new_bad)} old={len(old_bad)} "
            f"IDENTICAL={new_bad == old_bad}"
        )

        # --- 2. static faces BVH ---------------------------------------
        new_tree, new_faces = ro._static_faces_bvh(me, member)
        old_tree, old_faces = old_static_faces_bvh(me, member)
        same_len = len(new_faces) == len(old_faces)
        same_order = same_len and all(
            new_faces[i].index == old_faces[i].index
            for i in range(len(new_faces))
        )
        _mark(
            f"static_faces_bvh    new={len(new_faces)} old={len(old_faces)} "
            f"SAME_LENGTH={same_len} SAME_ORDER={same_order}"
        )

        # --- 3. cross-sheet pairs --------------------------------------
        affected = [
            p for p in me.polygons if any(vi in member for vi in p.vertices)
        ]
        new_pairs = ro._cross_sheet_pairs(me, new_tree, new_faces, affected)
        old_pairs = old_cross_sheet_pairs(me, old_tree, old_faces, affected)
        _mark(
            f"cross_sheet_pairs   new={len(new_pairs)} old={len(old_pairs)} "
            f"IDENTICAL={new_pairs == old_pairs}"
        )

        allsame = (
            new_bad == old_bad and same_order and new_pairs == old_pairs
        )
        _mark("")
        _mark(
            "VERDICT: on a triangle mesh the #49m helper is "
            + ("BIT-IDENTICAL to the code it replaced."
               if allsame else "NOT identical — investigate.")
        )
        _mark(f"EQUIVALENT={allsame}")
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
