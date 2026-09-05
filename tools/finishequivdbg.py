"""#52 — are the numpy finishing helpers equivalent to the code they replaced?

Carries verbatim copies of the PRE-#52 bodies and compares them against the
installed build on the real 4 mm reference brace, at the exact mesh state
production hands each helper:

  * volume / Euler / edge-use / components / zero-area   on the fresh brace
  * _slot_boundary_edges      eligible edge index list, post-boolean pre-bevel
  * _remove_slot_slivers      resulting V/E/F + vertex coordinate multiset
  * _remove_exact_fillet_degenerates (emboss)  same comparison
  * _validate_finished_rim    same verdict old vs new

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/finishequivdbg.py
"""

import math
import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bracefixture  # noqa: E402
import finishtimedbg as ft  # noqa: E402  (face pickers only)

_OUT = r"C:\Projects\Blender Add-on Braces\finishequivdbg_result.txt"
_TRIES = {"n": 0}
_log = []
_checks = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _check(name, ok, detail=""):
    _checks.append(bool(ok))
    _mark(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


# ---- verbatim PRE-#52 bodies -------------------------------------------------
def old_mesh_volume(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        return abs(bm.calc_volume(signed=True))
    finally:
        bm.free()


def old_surface_euler_characteristic(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        used_faces = list(bm.faces)
        used_edges = {edge for face in used_faces for edge in face.edges}
        used_vertices = {vertex for face in used_faces for vertex in face.verts}
        return len(used_vertices) - len(used_edges) + len(used_faces)
    finally:
        bm.free()


def old_capsule_boundary_distance(point, width, height):
    if width >= height:
        radius = height * 0.5
        half_straight = (width - height) * 0.5
        distance = Vector((max(abs(point.x) - half_straight, 0.0), point.y)).length
    else:
        radius = width * 0.5
        half_straight = (height - width) * 0.5
        distance = Vector((point.x, max(abs(point.y) - half_straight, 0.0))).length
    return abs(distance - radius)


def old_slot_boundary_edges(corset, slots):
    bm = bmesh.new()
    bm.from_mesh(corset.data)
    transforms = []
    for slot in slots:
        transforms.append(
            (
                slot.matrix_world.inverted() @ corset.matrix_world,
                float(slot.get("rigo_h", 12.0)) * 0.001,
                float(slot.get("rigo_w", 40.0)) * 0.001,
            )
        )
    eligible = []
    tolerance = 0.0006
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            continue
        if edge.calc_face_angle(0.0) < math.radians(25.0):
            continue
        for transform, width, height in transforms:
            local_points = [transform @ vertex.co for vertex in edge.verts]
            if all(
                old_capsule_boundary_distance(point, width, height) <= tolerance
                for point in local_points
            ):
                eligible.append(edge)
                break
    return bm, eligible


def old_remove_slot_slivers(corset, slots):
    bm = bmesh.new()
    bm.from_mesh(corset.data)
    transforms = [
        (
            slot.matrix_world.inverted() @ corset.matrix_world,
            float(slot.get("rigo_h", 12.0)) * 0.0005 + 0.002,
            float(slot.get("rigo_w", 40.0)) * 0.0005 + 0.002,
        )
        for slot in slots
    ]

    def near_slot(vertex):
        return any(
            abs((transform @ vertex.co).x) <= half_width
            and abs((transform @ vertex.co).y) <= half_height
            and abs((transform @ vertex.co).z) <= 0.012
            for transform, half_width, half_height in transforms
        )

    local_vertices = [vertex for vertex in bm.verts if near_slot(vertex)]
    try:
        if local_vertices:
            bmesh.ops.remove_doubles(bm, verts=local_vertices, dist=5.0e-6)
            local_set = {vertex for vertex in bm.verts if near_slot(vertex)}
            local_edges = [
                edge for edge in bm.edges if all(vertex in local_set for vertex in edge.verts)
            ]
            if local_edges:
                bmesh.ops.dissolve_degenerate(bm, edges=local_edges, dist=5.0e-5)
            local_faces = [
                face for face in bm.faces if all(vertex in local_set for vertex in face.verts)
            ]
            non_triangles = [face for face in local_faces if len(face.verts) > 3]
            if non_triangles:
                bmesh.ops.triangulate(bm, faces=non_triangles)
            for _iteration in range(2):
                zero_edges = {
                    min(face.edges, key=lambda edge: edge.calc_length())
                    for face in bm.faces
                    if face.calc_area() <= 1.0e-12
                    and all(near_slot(vertex) for vertex in face.verts)
                }
                if not zero_edges:
                    break
                bmesh.ops.collapse(bm, edges=list(zero_edges))
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.to_mesh(corset.data)
            corset.data.update()
    finally:
        bm.free()


def old_remove_exact_fillet_degenerates(corset):
    mesh = corset.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1.0e-8)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=5.0e-7)
    support_ngons = [face for face in bm.faces if len(face.verts) > 3]
    if support_ngons:
        triangulated = bmesh.ops.triangulate(bm, faces=support_ngons)
        bmesh.ops.beautify_fill(
            bm,
            faces=triangulated.get("faces", []),
            method="AREA",
        )
        bmesh.ops.dissolve_degenerate(
            bm, edges=list(bm.edges), dist=5.0e-7
        )
    nearly_collinear = [face for face in bm.faces if face.calc_area() <= 1.0e-11]
    middle_vertices = set()
    for face in nearly_collinear:
        if len(face.edges) != 3:
            continue
        shortest = sorted(face.edges, key=lambda edge: edge.calc_length())[:2]
        shared = set(shortest[0].verts).intersection(shortest[1].verts)
        middle_vertices.update(shared)
    if middle_vertices:
        bmesh.ops.dissolve_verts(
            bm,
            verts=list(middle_vertices),
            use_face_split=False,
            use_boundary_tear=False,
        )
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    for _pass in range(2):
        mesh.calc_loop_triangles()
        repaired = False
        for triangle in mesh.loop_triangles:
            indices = tuple(triangle.vertices)
            coordinates = [mesh.vertices[index].co for index in indices]
            area = 0.5 * (coordinates[1] - coordinates[0]).cross(
                coordinates[2] - coordinates[0]
            ).length
            if area > 1.0e-12:
                continue
            pairs = (
                ((indices[0], indices[1]), (coordinates[0] - coordinates[1]).length),
                ((indices[1], indices[2]), (coordinates[1] - coordinates[2]).length),
                ((indices[2], indices[0]), (coordinates[2] - coordinates[0]).length),
            )
            endpoints = max(pairs, key=lambda pair: pair[1])[0]
            middle_index = next(index for index in indices if index not in endpoints)
            normal = mesh.vertices[middle_index].normal.copy()
            if normal.length_squared > 1.0e-20:
                mesh.vertices[middle_index].co += normal.normalized() * 1.0e-6
                repaired = True
        if not repaired:
            break
        mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = True


def old_mesh_edge_use_counts(triangles):
    uses = {}
    for triangle in triangles:
        for first, second in (
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ):
            edge = tuple(sorted((first, second)))
            uses[edge] = uses.get(edge, 0) + 1
    return uses


def old_zero_area_triangle_count(coordinates, triangles):
    count = 0
    for first, second, third in triangles:
        cross = (coordinates[second] - coordinates[first]).cross(
            coordinates[third] - coordinates[first]
        )
        count += 0.5 * cross.length <= 1.0e-12
    return count


def old_connected_component_count(triangles, vertex_count):
    parent = list(range(vertex_count))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    used = set()
    for triangle in triangles:
        used.update(triangle)
        first = root(triangle[0])
        for vertex in triangle[1:]:
            second = root(vertex)
            if first != second:
                parent[second] = first
    return len({root(vertex) for vertex in used})


def old_rim_stats(mesh):
    mesh.calc_loop_triangles()
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    uses = old_mesh_edge_use_counts(triangles)
    return (
        sum(count == 1 for count in uses.values()),
        sum(count > 2 for count in uses.values()),
        old_connected_component_count(triangles, len(coordinates)),
        old_zero_area_triangle_count(coordinates, triangles),
    )


def new_rim_stats(do, mesh):
    coordinates, triangles = do._triangle_arrays(mesh)
    uses = do._mesh_edge_use_counts(triangles)
    return (
        int((uses == 1).sum()),
        int((uses > 2).sum()),
        do._connected_component_count(triangles, len(coordinates)),
        do._zero_area_triangle_count(coordinates, triangles),
    )


# ---- mesh fingerprint --------------------------------------------------------
def _fingerprint(mesh):
    import numpy as np
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    co = np.round(co.reshape(-1, 3), 9)
    order = np.lexsort((co[:, 2], co[:, 1], co[:, 0]))
    return (len(mesh.vertices), len(mesh.edges), len(mesh.polygons),
            co[order].tobytes().__hash__())


def _twin(corset):
    """A temporary object carrying a copy of corset's mesh, same transform."""
    twin = bpy.data.objects.new("Rigo Equiv Twin", corset.data.copy())
    twin.matrix_world = corset.matrix_world.copy()
    bpy.context.scene.collection.objects.link(twin)
    return twin


def _drop(twin):
    data = twin.data
    bpy.data.objects.remove(twin, do_unlink=True)
    if data.users == 0:
        bpy.data.meshes.remove(data)


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    try:
        import numpy as np
        do = ft._mod("design_ops")
        ro = ft._mod("rivet_ops")
        _mark(f"installed build has _triangle_arrays: {hasattr(do, '_triangle_arrays')}")
        ctx = bpy.context
        scan, settings = bracefixture.prepare_reference_design()
        settings.corset_thickness = 4.0
        gen = bpy.ops.rigo.generate_curve_corset()
        brace = bpy.data.objects["Rigo Corset"]
        _mark(f"generate -> {gen} faces={len(brace.data.polygons)}")
        snapshot = brace.data.copy()
        main = ft._largest_component_faces(brace.data)
        rim_dist = ft._rim_distance(brace)

        # --- 1. counters on the fresh brace -------------------------------
        mesh = brace.data
        v_old, v_new = old_mesh_volume(mesh), do._mesh_volume(mesh)
        # bmesh.calc_volume sums float32 tetrahedra; the numpy sum is float64.
        # Measured gap on the reference brace: 2.9e-7 relative.  Callers only
        # compare two volumes from the same function against changes >= 1e-5.
        _check("mesh_volume", abs(v_old - v_new) <= 1e-6 * max(v_old, 1e-12),
               f"old={v_old:.12g} new={v_new:.12g} rel={abs(v_old - v_new) / max(v_old, 1e-12):.2e}")
        e_old, e_new = old_surface_euler_characteristic(mesh), do._surface_euler_characteristic(mesh)
        _check("surface_euler", e_old == e_new, f"old={e_old} new={e_new}")
        s_old, s_new = old_rim_stats(mesh), new_rim_stats(do, mesh)
        _check("rim_stats(boundary,nonmanifold,components,zero_area)", s_old == s_new,
               f"old={s_old} new={s_new}")
        # synthetic: two detached cubes + a loose triangle -> components must be 3
        tris = [(0, 1, 2), (1, 2, 3), (4, 5, 6), (5, 6, 7), (8, 9, 10)]
        _check("components synthetic",
               do._connected_component_count(tris, 11) == old_connected_component_count(tris, 11) == 3)
        # synthetic: one open quad -> 4 boundary edges, no non-manifold
        uses = do._mesh_edge_use_counts([(0, 1, 2), (0, 2, 3)])
        _check("edge_use synthetic", int((uses == 1).sum()) == 4 and int((uses > 2).sum()) == 0,
               f"counts={uses.tolist()}")

        # --- 2. hooks around the slot cut ----------------------------------
        real_sbe = do._slot_boundary_edges
        real_rss = do._remove_slot_slivers
        real_refd = do._remove_exact_fillet_degenerates
        real_vfr = do._validate_finished_rim

        def hooked_sbe(corset, slots):
            bm_old, old_eligible = old_slot_boundary_edges(corset, slots)
            old_idx = [e.index for e in old_eligible]
            bm_old.free()
            bm_new, new_eligible = real_sbe(corset, slots)
            new_idx = [e.index for e in new_eligible]
            _check("slot_boundary_edges eligible indices", old_idx == new_idx,
                   f"old={len(old_idx)} new={len(new_idx)}")
            return bm_new, new_eligible

        def hooked_rss(corset, slots):
            twin = _twin(corset)
            old_remove_slot_slivers(twin, slots)
            real_rss(corset, slots)
            fo, fn = _fingerprint(twin.data), _fingerprint(corset.data)
            _check("remove_slot_slivers mesh fingerprint", fo == fn,
                   f"old(V,E,F)={fo[:3]} new={fn[:3]}")
            _drop(twin)

        def hooked_refd(corset):
            twin = _twin(corset)
            old_remove_exact_fillet_degenerates(twin)
            real_refd(corset)
            fo, fn = _fingerprint(twin.data), _fingerprint(corset.data)
            smooth = np.zeros(len(corset.data.polygons), dtype=bool)
            corset.data.polygons.foreach_get("use_smooth", smooth)
            _check("remove_exact_fillet_degenerates fingerprint", fo == fn,
                   f"old(V,E,F)={fo[:3]} new={fn[:3]}")
            _check("use_smooth all set", bool(smooth.all()))
            _drop(twin)

        def hooked_vfr(corset):
            so, sn = old_rim_stats(corset.data), new_rim_stats(do, corset.data)
            _check("validate_finished_rim stats", so == sn, f"old={so} new={sn}")
            return real_vfr(corset)

        do._slot_boundary_edges = hooked_sbe
        do._remove_slot_slivers = hooked_rss
        do._remove_exact_fillet_degenerates = hooked_refd
        do._validate_finished_rim = hooked_vfr
        ro._remove_slot_slivers = hooked_rss
        ro._validate_finished_rim = hooked_vfr

        def restore():
            if ctx.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            old = brace.data
            brace.data = snapshot.copy()
            if old.users == 0:
                bpy.data.meshes.remove(old)
            settings.brace_dirty = False
            brace["rigo_brace_dirty"] = False
            bpy.ops.object.select_all(action="DESELECT")
            brace.select_set(True)
            ctx.view_layer.objects.active = brace

        loc, nrm = ft._pick_face(brace, main, lambda p: p.normal.x > 0.55, lambda p: p.center.x)
        settings.slot_width, settings.slot_height = 30.0, 10.0
        settings.slot_edge_radius, settings.symmetrical = 0.6, False
        do._new_slot_marker(ctx, do._SlotPlacement(
            "SLOT_E", brace.matrix_world @ loc,
            (brace.matrix_world.to_3x3() @ nrm).normalized(), 30.0, 10.0))
        res = bpy.ops.rigo.cut_slots()
        _check("cut_slots finished", res == {"FINISHED"}, str(brace.get("rigo_slot_status")))
        restore()

        loc, nrm = ft._pick_face(brace, main, lambda p: p.normal.y < -0.65, rim_dist)
        settings.rivet_diameter, settings.rivet_edge_radius = 4.0, 0.35
        ro._new_rivet_marker(ctx, "RIVET_E", brace.matrix_world @ loc,
                             (brace.matrix_world.to_3x3() @ nrm).normalized(), 4.0)
        res = bpy.ops.rigo.cut_rivets()
        _check("cut_rivets finished", res == {"FINISHED"}, str(brace.get("rigo_rivet_status")))
        restore()

        loc, nrm = ft._pick_face(brace, main, lambda p: p.normal.y < -0.65, rim_dist)
        settings.emboss_text, settings.emboss_depth = "RIGO", 1.0
        settings.emboss_size, settings.emboss_mode = 12.0, "RAISED"
        do._new_emboss_preview(ctx, brace, "RIGO", loc, nrm, 12.0)
        res = bpy.ops.rigo.emboss_text()
        _check("emboss_text finished", res == {"FINISHED"})
        restore()

        # --- 3. the pre-existing #50 refusal on the A trim fixture ----------
        # venttest/designtest are RED at baseline here (ERR-0033).  Prove the
        # refusal is the OLD counters' verdict too, at the exact mesh state.
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        seen = []

        def hooked_vfr_a(corset):
            so, sn = old_rim_stats(corset.data), new_rim_stats(do, corset.data)
            seen.append((so, sn))
            return real_vfr(corset)

        do._validate_finished_rim = hooked_vfr_a
        bracefixture.prepare_a_design()
        settings.corset_thickness = 4.0
        try:
            res = bpy.ops.rigo.generate_curve_corset()
            _mark(f"A-fixture generate -> {res}")
        except RuntimeError as exc:
            _mark(f"A-fixture generate refused: {str(exc).strip()[:120]}")
        _check("A-fixture #50 verdict identical old vs new",
               bool(seen) and all(so == sn for so, sn in seen),
               f"validate calls={len(seen)} stats={seen}")
        do._validate_finished_rim = real_vfr

        _mark("")
        _mark(f"EQUIVALENT={all(_checks)}  checks={len(_checks)} failed={_checks.count(False)}")
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
