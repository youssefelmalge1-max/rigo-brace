"""Installed-copy regression for measurable brace thickness and stale state."""

import os
import sys
from statistics import median

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators.qa_ops import evaluate_brace_qa


OUT = r"C:\Projects\Blender Add-on Braces\thicknesstest_result.txt"
STALE_STL = r"C:\Projects\Blender Add-on Braces\_stale_brace_test.stl"
TRIES = {"count": 0}
LINES = []


def _write(message):
    LINES.append(str(message))
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(LINES))


def _scan_signature(scan):
    coordinates = tuple(
        round(component, 9)
        for vertex in scan.data.vertices
        for component in vertex.co
    )
    return len(scan.data.vertices), hash(coordinates)


def _mesh_metrics(brace):
    bm = bmesh.new()
    bm.from_mesh(brace.data)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
    volume = abs(bm.calc_volume(signed=True))
    bm.free()
    return boundary, non_manifold, volume


def _evaluated_wall_measurement(context, brace):
    """Measure the finished shell independently from its audit properties.

    Rays start at sampled evaluated-triangle centres and travel along both
    normal directions.  A real brace wall produces a dense cluster of hits on
    the opposing wall; trim-side and near-tangent hits are rejected as
    outliers before taking a robust median.  This intentionally does not call
    the add-on's thickness helper or read any ``rigo_*thickness*`` property.
    """
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = brace.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
    try:
        mesh.calc_loop_triangles()
        matrix = evaluated.matrix_world
        vertices = [matrix @ vertex.co for vertex in mesh.vertices]
        triangles = [tuple(loop.vertices) for loop in mesh.loop_triangles]
    finally:
        evaluated.to_mesh_clear()

    tree = BVHTree.FromPolygons(
        vertices, triangles, all_triangles=True, epsilon=0.0
    )
    stride = max(1, len(triangles) // 1600)
    distances_mm = []
    for triangle_index in range(0, len(triangles), stride):
        indices = triangles[triangle_index]
        first, second, third = (vertices[index] for index in indices)
        cross = (second - first).cross(third - first)
        if cross.length_squared <= 1.0e-20:
            continue
        normal = cross.normalized()
        center = (first + second + third) / 3.0
        candidate_hits = []
        for direction in (normal, -normal):
            # Start clear of the sampled face.  The opposing wall is expected
            # within 15 mm for all supported brace settings.
            origin = center + direction * 0.00005
            location, _hit_normal, hit_index, _distance = tree.ray_cast(
                origin, direction, 0.015
            )
            if location is None or hit_index == triangle_index:
                continue
            measured_mm = (location - center).length * 1000.0
            if 0.25 <= measured_mm <= 15.0:
                candidate_hits.append(measured_mm)
        if candidate_hits:
            distances_mm.append(min(candidate_hits))

    distances_mm.sort()
    if not distances_mm:
        return {"samples": 0, "median_mm": 0.0, "p10_mm": 0.0, "p90_mm": 0.0}
    last = len(distances_mm) - 1
    return {
        "samples": len(distances_mm),
        "median_mm": median(distances_mm),
        "p10_mm": distances_mm[round(last * 0.10)],
        "p90_mm": distances_mm[round(last * 0.90)],
    }


def _build(settings, requested):
    settings.corset_thickness = requested
    result = bpy.ops.rigo.generate_corset()
    brace = bpy.data.objects.get("Rigo Corset")
    boundary, non_manifold, volume = _mesh_metrics(brace)
    pair_min = float(brace.get("rigo_pair_min_thickness_mm", -1.0))
    pair_max = float(brace.get("rigo_pair_max_thickness_mm", -1.0))
    built = float(brace.get("rigo_requested_thickness_mm", -1.0))
    collision_initial = int(brace.get("rigo_outer_collision_initial", -1))
    collision_remaining = int(brace.get("rigo_outer_collision_remaining", -1))
    collision_iterations = int(brace.get("rigo_outer_collision_iterations", -1))
    collision_vertices = int(brace.get("rigo_outer_collision_vertices", -1))
    collision_angle = float(
        brace.get("rigo_outer_collision_max_angle_deg", -1.0)
    )
    names = [obj.name for obj in bpy.data.objects if obj.name.startswith("Rigo Corset")]
    qa = evaluate_brace_qa(bpy.context, brace)
    measured = _evaluated_wall_measurement(bpy.context, brace)
    measurement_tolerance = max(0.40, requested * 0.12)
    measurement_ok = (
        measured["samples"] >= 100
        and abs(measured["median_mm"] - requested) <= measurement_tolerance
    )
    qa_geometry_ok = (
        qa.get("components") == 1
        and qa.get("boundary_edges") == 0
        and qa.get("nonmanifold_edges") == 0
        and qa.get("self_intersections") == 0
    )
    if requested < settings.qa_min_thickness:
        qa_ok = (
            not qa["passed"]
            and qa_geometry_ok
            and qa["reasons"]
            and all("Minimum sampled wall" in reason for reason in qa["reasons"])
        )
    else:
        qa_ok = qa["passed"] and qa_geometry_ok
    ok = (
        result == {"FINISHED"}
        and abs(built - requested) <= 0.001
        and measurement_ok
        and boundary == 0
        and non_manifold == 0
        and names.count("Rigo Corset") == 1
        and names.count("Rigo Corset Base") == 1
        and len(names) == 2
        and not settings.brace_dirty
        and not bool(brace.get("rigo_brace_dirty", True))
        and qa_ok
    )
    _write(
        f"thickness={requested:.1f} result={result} built={built:.3f} "
        f"pair={pair_min:.3f}-{pair_max:.3f} boundary={boundary} "
        f"nonmanifold={non_manifold} volume={volume:.9f} "
        f"collision={collision_initial}->{collision_remaining} "
        f"iterations={collision_iterations} vertices={collision_vertices} "
        f"angle={collision_angle:.3f} names={names} ok={ok}"
        f" qa_pass={qa['passed']} qa_min={qa.get('min_thickness_mm', 0.0):.3f} "
        f"measured_samples={measured['samples']} "
        f"measured_p10={measured['p10_mm']:.3f} "
        f"measured_median={measured['median_mm']:.3f} "
        f"measured_p90={measured['p90_mm']:.3f} "
        f"measurement_tolerance={measurement_tolerance:.3f} "
        f"measurement_ok={measurement_ok}"
    )
    return brace, volume, measured, ok, qa


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["count"] < 30:
        return 0.1
    try:
        if os.path.exists(STALE_STL):
            os.remove(STALE_STL)
        scan, settings = prepare_reference_design()
        scan_signature = _scan_signature(scan)

        _brace_2, volume_2, measured_2, ok_2, _qa_2 = _build(settings, 2.0)
        brace_4, volume_4, measured_4, ok_4, _qa_4 = _build(settings, 4.0)

        settings.corset_thickness = 6.0
        stale_qa = evaluate_brace_qa(bpy.context, brace_4)
        export_error = ""
        try:
            export_result = bpy.ops.rigo.export_brace(filepath=STALE_STL)
        except RuntimeError as error:
            export_result = {"CANCELLED"}
            export_error = str(error)
        stale_ok = (
            settings.brace_dirty
            and bool(brace_4.get("rigo_brace_dirty", False))
            and float(brace_4.get("rigo_requested_thickness_mm", -1.0)) == 4.0
            and not stale_qa["passed"]
            and stale_qa["reasons"]
            and "out of date" in stale_qa["reasons"][0].lower()
            and export_result == {"CANCELLED"}
            and "out of date" in export_error.lower()
            and not os.path.exists(STALE_STL)
        )
        _write(
            f"stale dirty={settings.brace_dirty} qa={stale_qa['reasons']} "
            f"export={export_result} error={export_error!r} "
            f"written={os.path.exists(STALE_STL)} ok={stale_ok}"
        )

        brace_6, volume_6, measured_6, ok_6, qa_6 = _build(settings, 6.0)
        valid_base = bpy.data.objects.get("Rigo Corset Base")
        valid_mesh = brace_6.data
        settings.corset_thickness = 12.0
        infeasible_error = ""
        try:
            infeasible_result = bpy.ops.rigo.generate_corset()
        except RuntimeError as error:
            infeasible_result = {"CANCELLED"}
            infeasible_error = str(error)
        retained_brace = bpy.data.objects.get("Rigo Corset")
        retained_base = bpy.data.objects.get("Rigo Corset Base")
        transaction_ok = (
            infeasible_result == {"CANCELLED"}
            and "cannot be generated" in infeasible_error.lower()
            and "traceback" not in infeasible_error.lower()
            and retained_brace is brace_6
            and retained_brace.data is valid_mesh
            and retained_base is valid_base
            and float(
                retained_brace.get("rigo_requested_thickness_mm", -1.0)
            )
            == 6.0
            and settings.brace_dirty
            and bool(retained_brace.get("rigo_brace_dirty", False))
            and bpy.data.objects.get("Rigo Corset Candidate") is None
            and bpy.data.objects.get("Rigo Corset Base Candidate") is None
        )
        _write(
            f"infeasible_12mm result={infeasible_result} "
            f"error={infeasible_error!r} "
            f"brace_retained={retained_brace is brace_6} "
            f"base_retained={retained_base is valid_base} "
            f"candidates_clean={bpy.data.objects.get('Rigo Corset Candidate') is None} "
            f"ok={transaction_ok}"
        )
        monotonic = volume_2 < volume_4 < volume_6
        measured_monotonic = (
            measured_2["median_mm"]
            < measured_4["median_mm"]
            < measured_6["median_mm"]
        )
        scan_unchanged = _scan_signature(scan) == scan_signature
        final_ok = (
            ok_2
            and ok_4
            and ok_6
            and stale_ok
            and monotonic
            and measured_monotonic
            and scan_unchanged
            and qa_6["passed"]
            and transaction_ok
        )
        _write(
            f"volume_monotonic={monotonic} "
            f"measured_monotonic={measured_monotonic} "
            f"scan_unchanged={scan_unchanged} "
            f"qa6_pass={qa_6['passed']} qa6_reasons={qa_6['reasons']}"
        )
        _write(f"PASS={final_ok}")
    except Exception as error:  # noqa: BLE001
        import traceback

        _write(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    finally:
        if os.path.exists(STALE_STL):
            os.remove(STALE_STL)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
