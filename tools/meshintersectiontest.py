"""Regression for exact triangle intersections behind generation and QA."""

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


OUT = r"C:\Projects\Blender Add-on Braces\meshintersectiontest_result.txt"
TRIES = {"count": 0}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))


def _pairs(vertices, triangles, helper, candidate_tree=None):
    tree = candidate_tree or BVHTree.FromPolygons(
        vertices, triangles, all_triangles=True, epsilon=0.0
    )
    broad = {
        tuple(sorted(pair))
        for pair in tree.overlap(tree)
        if pair[0] != pair[1]
    }
    return broad, helper(vertices, triangles, bvh=tree)


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        from bl_ext.user_default.rigo_brace.operators.mesh_intersections import (
            triangle_intersection_pairs,
            triangles_intersect,
        )

        flat = (
            Vector((0.0, 0.0, 0.0)),
            Vector((2.0, 0.0, 0.0)),
            Vector((0.0, 2.0, 0.0)),
        )
        crossing = (
            Vector((0.25, 0.25, -0.5)),
            Vector((0.25, 0.25, 0.5)),
            Vector((0.75, 0.25, 0.0)),
        )
        coplanar = (
            Vector((0.25, 0.25, 0.0)),
            Vector((1.25, 0.25, 0.0)),
            Vector((0.25, 1.25, 0.0)),
        )
        # Its plane crossing lies entirely outside the flat triangle
        # (x + y > 2), so the exact phase must reject it.
        separated = (
            Vector((1.2, 1.2, -0.5)),
            Vector((1.8, 1.2, 0.5)),
            Vector((1.2, 1.8, 0.5)),
        )
        direct_ok = (
            triangles_intersect(flat, crossing)
            and triangles_intersect(flat, coplanar)
            and not triangles_intersect(flat, separated)
        )
        lines.append(f"direct_narrow_phase={direct_ok}")

        # Use a real Blender BVHTree containing the known crossing pair as a
        # deterministic over-inclusive candidate source.  Passing it into the
        # public ``bvh=`` seam proves that a candidate reaching the helper is
        # still rejected according to the exact geometry below.  Constructing
        # a naturally false-positive two-triangle BVH is platform-sensitive.
        candidate_vertices = list(flat + crossing)
        candidate_triangles = [(0, 1, 2), (3, 4, 5)]
        candidate_tree = BVHTree.FromPolygons(
            candidate_vertices,
            candidate_triangles,
            all_triangles=True,
            epsilon=0.0,
        )

        false_vertices = list(flat + separated)
        false_triangles = [(0, 1, 2), (3, 4, 5)]
        false_broad, false_exact = _pairs(
            false_vertices,
            false_triangles,
            triangle_intersection_pairs,
            candidate_tree=candidate_tree,
        )
        false_ok = false_broad == {(0, 1)} and false_exact == []
        lines.append(
            f"separated_overlapping_bounds broad={sorted(false_broad)} "
            f"exact={false_exact} ok={false_ok}"
        )

        true_vertices = list(flat + crossing)
        true_triangles = [(0, 1, 2), (3, 4, 5)]
        _true_broad, true_exact = _pairs(
            true_vertices, true_triangles, triangle_intersection_pairs
        )
        true_ok = true_exact == [(0, 1)]
        lines.append(f"noncoplanar_exact={true_exact} ok={true_ok}")

        # These non-coplanar faces share a real mesh edge.  Their boxes
        # overlap, but the shared edge is topological adjacency rather than a
        # self-intersection and therefore must be excluded.
        adjacent_vertices = [
            Vector((0.0, 0.0, 0.0)),
            Vector((2.0, 0.0, 0.0)),
            Vector((0.0, 2.0, 0.0)),
            Vector((1.0, 1.0, 1.0)),
        ]
        adjacent_triangles = [(0, 1, 2), (0, 1, 3)]
        adjacent_broad, adjacent_exact = _pairs(
            adjacent_vertices,
            adjacent_triangles,
            triangle_intersection_pairs,
            candidate_tree=candidate_tree,
        )
        adjacent_ok = adjacent_broad == {(0, 1)} and adjacent_exact == []
        lines.append(
            f"topological_neighbours broad={sorted(adjacent_broad)} "
            f"exact={adjacent_exact} ok={adjacent_ok}"
        )

        vertex_neighbour_vertices = [
            Vector((0.0, 0.0, 0.0)),
            Vector((2.0, 0.0, 0.0)),
            Vector((0.0, 2.0, 0.0)),
            Vector((-2.0, 0.0, 0.0)),
            Vector((0.0, -2.0, 0.0)),
        ]
        vertex_neighbour_triangles = [(0, 1, 2), (0, 3, 4)]
        _vertex_broad, vertex_exact = _pairs(
            vertex_neighbour_vertices,
            vertex_neighbour_triangles,
            triangle_intersection_pairs,
            candidate_tree=candidate_tree,
        )
        vertex_neighbour_ok = vertex_exact == []
        lines.append(
            f"shared_vertex_expected={vertex_exact} ok={vertex_neighbour_ok}"
        )

        vertex_crossing_vertices = [
            Vector((0.0, 0.0, 0.0)),
            Vector((2.0, 0.0, 0.0)),
            Vector((0.0, 2.0, 0.0)),
            Vector((1.0, 1.0, -1.0)),
            Vector((1.0, 1.0, 1.0)),
        ]
        vertex_crossing_triangles = [(0, 1, 2), (0, 3, 4)]
        _vertex_cross_broad, vertex_cross_exact = _pairs(
            vertex_crossing_vertices,
            vertex_crossing_triangles,
            triangle_intersection_pairs,
            candidate_tree=candidate_tree,
        )
        vertex_cross_ok = vertex_cross_exact == [(0, 1)]
        lines.append(
            f"shared_vertex_crossing={vertex_cross_exact} ok={vertex_cross_ok}"
        )

        folded_edge_vertices = [
            Vector((0.0, 0.0, 0.0)),
            Vector((2.0, 0.0, 0.0)),
            Vector((0.0, 2.0, 0.0)),
            Vector((0.5, 0.5, 0.0)),
        ]
        folded_edge_triangles = [(0, 1, 2), (0, 1, 3)]
        _folded_broad, folded_exact = _pairs(
            folded_edge_vertices,
            folded_edge_triangles,
            triangle_intersection_pairs,
            candidate_tree=candidate_tree,
        )
        folded_edge_ok = folded_exact == [(0, 1)]
        lines.append(f"shared_edge_overlap={folded_exact} ok={folded_edge_ok}")

        duplicate_triangles = [(0, 1, 2), (0, 1, 2)]
        _duplicate_broad, duplicate_exact = _pairs(
            list(flat),
            duplicate_triangles,
            triangle_intersection_pairs,
            candidate_tree=candidate_tree,
        )
        duplicate_ok = duplicate_exact == [(0, 1)]
        lines.append(f"duplicate_face={duplicate_exact} ok={duplicate_ok}")

        passed = all(
            (
                direct_ok,
                false_ok,
                true_ok,
                adjacent_ok,
                vertex_neighbour_ok,
                vertex_cross_ok,
                folded_edge_ok,
                duplicate_ok,
            )
        )
        lines.append(f"PASS={passed}")
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
