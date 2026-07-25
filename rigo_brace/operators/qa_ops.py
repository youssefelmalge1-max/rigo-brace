"""Manufacturing geometry checks for the canonical final brace.

These checks are deliberately technical. They can block a broken STL, but they
cannot approve the clinical prescription or the finished orthosis.
"""

import hashlib
import struct

import bpy
from bpy.types import Operator
from mathutils.bvhtree import BVHTree

from ..core import CORSET_NAME, mark_brace_dirty
from ..core.signatures import brace_has_source_record, geometry_signature
from .mesh_intersections import triangle_intersection_pairs


_AREA_EPSILON_M2 = 1.0e-12
_RAY_EPSILON_M = 1.0e-5
_THICKNESS_SAMPLE_LIMIT = 6000
_RIM_PROVENANCE_GROUP = "RIGO_RIM_BOUNDARY"
_STRUCTURAL_EXCLUSION_LIMIT = 0.20


def _evaluated_triangles(context, brace):
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = brace.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
    mesh.calc_loop_triangles()
    matrix = evaluated.matrix_world
    vertices = [matrix @ vertex.co for vertex in mesh.vertices]
    triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    evaluated.to_mesh_clear()
    return vertices, triangles


def _geometry_signature(vertices, triangles):
    digest = hashlib.sha256()
    digest.update(struct.pack("<II", len(vertices), len(triangles)))
    for vertex in vertices:
        digest.update(struct.pack("<3q", *(round(value * 1.0e9) for value in vertex)))
    for triangle in triangles:
        digest.update(struct.pack("<3I", *triangle))
    return digest.hexdigest()


def _connected_components(vertex_count, triangles):
    adjacency = [set() for _ in range(vertex_count)]
    used = set()
    for a, b, c in triangles:
        used.update((a, b, c))
        adjacency[a].update((b, c))
        adjacency[b].update((a, c))
        adjacency[c].update((a, b))
    components = 0
    unseen = set(used)
    while unseen:
        components += 1
        stack = [unseen.pop()]
        while stack:
            for neighbour in adjacency[stack.pop()]:
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    stack.append(neighbour)
    return components


def _ray_wall_thickness_mm(bvh, center, normal, source_index):
    direction = -normal
    origin = center + direction * _RAY_EPSILON_M
    location, hit_normal, hit_index, distance = bvh.ray_cast(origin, direction)
    if location is None or hit_index == source_index or distance is None:
        return None
    if normal.dot(hit_normal) > -0.25:
        return None
    thickness_mm = (distance + _RAY_EPSILON_M) * 1000.0
    return thickness_mm if thickness_mm > _RAY_EPSILON_M * 1000.0 else None


def _topology_counts(triangles):
    edge_faces = {}
    for index, (a, b, c) in enumerate(triangles):
        for edge in ((a, b), (b, c), (c, a)):
            edge_faces.setdefault(tuple(sorted(edge)), []).append(index)
    boundary = sum(len(faces) == 1 for faces in edge_faces.values())
    nonmanifold = sum(len(faces) != 2 for faces in edge_faces.values())
    return edge_faces, boundary, nonmanifold


def _face_data(vertices, triangles):
    centers = []
    normals = []
    areas = []
    signed_volume = 0.0
    for a, b, c in triangles:
        va, vb, vc = vertices[a], vertices[b], vertices[c]
        cross = (vb - va).cross(vc - va)
        length = cross.length
        areas.append(0.5 * length)
        normals.append(cross / length if length else cross)
        centers.append((va + vb + vc) / 3.0)
        signed_volume += va.dot(vb.cross(vc)) / 6.0
    return centers, normals, areas, signed_volume


def _self_intersections(bvh, vertices, triangles):
    """Confirm BVH overlap candidates with exact triangle geometry."""
    return triangle_intersection_pairs(vertices, triangles, bvh=bvh)


def _sample_thickness_mm(
    bvh, triangles, centers, normals, excluded_vertices=None
):
    if not triangles:
        return 0.0, 0, 0
    step = max(1, len(triangles) // _THICKNESS_SAMPLE_LIMIT)
    tested = 0
    valid = 0
    minimum = float("inf")
    excluded_vertices = excluded_vertices or set()
    for index in range(0, len(triangles), step):
        if any(vertex in excluded_vertices for vertex in triangles[index]):
            continue
        normal = normals[index]
        if normal.length_squared == 0.0:
            continue
        tested += 1
        thickness_mm = _ray_wall_thickness_mm(bvh, centers[index], normal, index)
        if thickness_mm is None:
            continue
        minimum = min(minimum, thickness_mm)
        valid += 1
    return (minimum if valid else 0.0), valid, tested


def _rim_provenance_vertices(brace, vertex_count):
    """Vertices whose provenance is GENERATED rim geometry.

    Membership is semantic - the builders tag the rim ring, the fillet
    profile points and the rounded-junction bevel output into this one group
    as they create them - so nothing here depends on index ranges or on
    guessing from shape.
    """
    group = brace.vertex_groups.get(_RIM_PROVENANCE_GROUP)
    if group is None or len(brace.data.vertices) != vertex_count:
        return set()
    return {
        vertex.index
        for vertex in brace.data.vertices
        if any(
            membership.group == group.index and membership.weight > 0.01
            for membership in vertex.groups
        )
    }


def _structural_wall_exclusion(triangles, rim_vertices):
    """How much of the STRUCTURAL wall thickness sampling can never reach.

    The old guard counted excluded vertices against every vertex in the
    shell, so it measured rim tessellation density rather than safety: a
    correctly built rounded rim reported 29.7 % while the wall it protects
    measured 3.47 mm against a 3.0 mm requirement, and rounding the rim
    further would have pushed it higher still.

    Rim geometry carries no wall thickness to measure, so it leaves BOTH
    sides of this ratio. A structural-wall vertex counts as excluded only
    when EVERY triangle carrying it also touches rim geometry - then no
    sampling stride, however fine, could ever measure it. That keeps the
    original intent (unmeasured load-bearing wall is unsafe) while being
    independent of how finely the rim is tessellated.
    """
    present = set()
    reachable = set()
    for triangle in triangles:
        present.update(triangle)
        if not any(index in rim_vertices for index in triangle):
            reachable.update(triangle)
    structural = present - rim_vertices
    if not structural:
        return 0.0, 0, 0
    excluded = structural - reachable
    return len(excluded) / len(structural), len(excluded), len(structural)


def _scene_uses_millimetres(scene):
    return (
        scene.unit_settings.system == "METRIC"
        and abs(scene.unit_settings.scale_length - 1.0) <= 1.0e-9
        and scene.unit_settings.length_unit == "MILLIMETERS"
    )


def _collect_mesh_metrics(context, brace):
    vertices, triangles = _evaluated_triangles(context, brace)
    if not vertices or not triangles:
        return {
            "vertices": len(vertices),
            "triangles": len(triangles),
            "components": 0,
            "boundary_edges": 0,
            "nonmanifold_edges": 0,
            "zero_area_faces": 0,
            "self_intersections": 0,
            "self_intersection_pairs": [],
            "signed_volume_m3": 0.0,
            "min_thickness_mm": 0.0,
            "thickness_valid_samples": 0,
            "thickness_tested_samples": 0,
            "thickness_coverage": 0.0,
            "edge_count": 0,
            "signature": _geometry_signature(vertices, triangles),
        }
    centers, normals, areas, signed_volume = _face_data(vertices, triangles)
    edge_faces, boundary, nonmanifold = _topology_counts(triangles)
    bvh = BVHTree.FromPolygons(vertices, triangles, all_triangles=True, epsilon=0.0)
    excluded_vertices = _rim_provenance_vertices(brace, len(vertices))
    (
        structural_exclusion,
        structural_excluded,
        structural_total,
    ) = _structural_wall_exclusion(triangles, excluded_vertices)
    minimum, valid_samples, tested_samples = _sample_thickness_mm(
        bvh, triangles, centers, normals, excluded_vertices
    )
    intersection_pairs = _self_intersections(bvh, vertices, triangles)
    return {
        "vertices": len(vertices),
        "triangles": len(triangles),
        "components": _connected_components(len(vertices), triangles),
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "zero_area_faces": sum(area <= _AREA_EPSILON_M2 for area in areas),
        "self_intersections": len(intersection_pairs),
        "self_intersection_pairs": intersection_pairs[:20],
        "signed_volume_m3": signed_volume,
        "min_thickness_mm": minimum,
        "thickness_valid_samples": valid_samples,
        "thickness_tested_samples": tested_samples,
        "thickness_coverage": valid_samples / tested_samples if tested_samples else 0.0,
        # Diagnostics: how much of the shell is generated rim, how much is
        # excluded in total, and - the guard - how much load-bearing wall
        # sampling can never reach.
        "thickness_excluded_vertices": len(excluded_vertices),
        "thickness_excluded_fraction": len(excluded_vertices) / len(vertices),
        "rim_vertex_fraction": len(excluded_vertices) / len(vertices),
        "structural_wall_vertices": structural_total,
        "structural_wall_excluded_vertices": structural_excluded,
        "structural_wall_exclusion_fraction": structural_exclusion,
        "edge_count": len(edge_faces),
        "signature": _geometry_signature(vertices, triangles),
    }


def _qa_failure_reasons(mesh_metrics, minimum_required, units_ok):
    reasons = []
    checks = (
        (not mesh_metrics["vertices"] or not mesh_metrics["triangles"], "Final brace has no mesh geometry"),
        (mesh_metrics["components"] != 1, f"Expected one connected shell; found {mesh_metrics['components']}"),
        (mesh_metrics["boundary_edges"] > 0, f"Found {mesh_metrics['boundary_edges']} open boundary edges"),
        (mesh_metrics["nonmanifold_edges"] > 0, f"Found {mesh_metrics['nonmanifold_edges']} non-manifold edges"),
        (mesh_metrics["zero_area_faces"] > 0, f"Found {mesh_metrics['zero_area_faces']} zero-area triangles"),
        (mesh_metrics["self_intersections"] > 0, f"Found {mesh_metrics['self_intersections']} self-intersecting triangle pairs"),
        (mesh_metrics["signed_volume_m3"] <= 0.0, "Brace normals are inverted or the enclosed volume is invalid"),
        (mesh_metrics["thickness_coverage"] < 0.80, f"Wall-thickness sampling coverage is only {mesh_metrics['thickness_coverage'] * 100.0:.1f}%"),
        (mesh_metrics.get("structural_wall_exclusion_fraction", 0.0) > _STRUCTURAL_EXCLUSION_LIMIT, f"Wall-thickness sampling cannot reach {mesh_metrics.get('structural_wall_exclusion_fraction', 0.0) * 100.0:.1f}% of the structural wall"),
        (mesh_metrics["min_thickness_mm"] + 1.0e-6 < minimum_required, f"Minimum sampled wall is {mesh_metrics['min_thickness_mm']:.2f} mm; required is {minimum_required:.2f} mm"),
        (not units_ok, "Scene must use Metric / Millimeters with scale length 1.0"),
    )
    reasons.extend(message for failed, message in checks if failed)
    return reasons


def evaluate_brace_qa(context, brace=None):
    """Return observable manufacturing checks for the evaluated final mesh."""
    brace = brace or bpy.data.objects.get(CORSET_NAME)
    if brace is None or brace.type != "MESH":
        return {
            "passed": False,
            "reasons": ["Generate the final Rigo Corset first"],
            "signature": "",
        }

    settings = context.scene.rigo_brace
    if not brace_has_source_record(brace):
        reason = "Brace has no complete source record"
        mark_brace_dirty(context, reason)
        return {
            "passed": False,
            "reasons": [f"{reason}; click Update Brace first"],
            "signature": "",
        }
    if settings.brace_dirty or bool(brace.get("rigo_brace_dirty", False)):
        return {
            "passed": False,
            "reasons": ["Brace is out of date; click Update Brace first"],
            "signature": "",
        }

    source_scan_signature = str(brace.get("rigo_source_scan_signature", ""))
    source_trim_signature = str(brace.get("rigo_source_trim_signature", ""))
    scan = settings.scan_object
    perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
    if scan is None or perimeter is None:
        reason = "The corrected body or trim perimeter is missing"
    elif geometry_signature(context, scan) != source_scan_signature:
        reason = "The corrected body changed after this brace was generated"
    elif geometry_signature(context, perimeter) != source_trim_signature:
        reason = "The trim perimeter changed after this brace was generated"
    else:
        reason = ""
    if reason:
        mark_brace_dirty(context, reason)
        return {
            "passed": False,
            "reasons": [f"{reason}; click Update Brace first"],
            "signature": "",
        }

    mesh_metrics = _collect_mesh_metrics(context, brace)
    units_ok = _scene_uses_millimetres(context.scene)
    reasons = _qa_failure_reasons(mesh_metrics, settings.qa_min_thickness, units_ok)
    return {**mesh_metrics, "passed": not reasons, "reasons": reasons, "units_ok": units_ok}


def store_qa_result(brace, qa_report):
    brace["rigo_qa_pass"] = bool(qa_report["passed"])
    brace["rigo_qa_signature"] = qa_report.get("signature", "")
    brace["rigo_qa_boundary"] = qa_report.get("boundary_edges", -1)
    brace["rigo_qa_nonmanifold"] = qa_report.get("nonmanifold_edges", -1)
    brace["rigo_qa_self_intersections"] = qa_report.get("self_intersections", -1)
    brace["rigo_qa_min_thickness_mm"] = qa_report.get("min_thickness_mm", 0.0)
    brace["rigo_qa_thickness_coverage"] = qa_report.get("thickness_coverage", 0.0)
    brace["rigo_qa_report"] = "PASS" if qa_report["passed"] else "; ".join(qa_report["reasons"])


class RIGO_OT_verify_brace_qa(Operator):
    """Check final brace topology, intersections, units and sampled wall thickness"""

    bl_idname = "rigo.verify_brace_qa"
    bl_label = "Verify Final Brace"
    bl_options = {"REGISTER"}

    def execute(self, context):
        brace = bpy.data.objects.get(CORSET_NAME)
        qa_report = evaluate_brace_qa(context, brace)
        if brace is not None:
            store_qa_result(brace, qa_report)
        if not qa_report["passed"]:
            self.report({"ERROR"}, qa_report["reasons"][0])
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"QA passed; sampled minimum wall {qa_report['min_thickness_mm']:.2f} mm",
        )
        return {"FINISHED"}


_CLASSES = (RIGO_OT_verify_brace_qa,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
