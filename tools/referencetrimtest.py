"""Regression for the reference-oriented trim and surface-bound point editing."""

import os
import sys

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.core import trim_templates
from bl_ext.user_default.rigo_brace.operators.qa_ops import evaluate_brace_qa


OUT = r"C:\Projects\Blender Add-on Braces\referencetrimtest_result.txt"
TRIES = {"count": 0}
LINES = []


def _write(message):
    LINES.append(str(message))
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(LINES))


def _index(theta_degrees, count=72):
    return int(((theta_degrees + 180.0) / 360.0) * count) % count


def _nearest_distance(scan, bvh, world):
    hit = bvh.find_nearest(scan.matrix_world.inverted() @ world)
    return float("inf") if hit[0] is None else hit[3]


def _curve_surface_metrics(scan, perimeter):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    original_bevel = perimeter.data.bevel_depth
    perimeter.data.bevel_depth = 0.0
    depsgraph.update()
    bvh = BVHTree.FromObject(scan, depsgraph)
    evaluated = perimeter.evaluated_get(depsgraph)
    evaluated_mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=depsgraph)
    distances = [
        _nearest_distance(scan, bvh, evaluated.matrix_world @ vertex.co) * 1000.0
        for vertex in evaluated_mesh.vertices
    ]
    bpy.data.meshes.remove(evaluated_mesh)
    perimeter.data.bevel_depth = original_bevel
    depsgraph.update()
    distances.sort()
    return distances[-1], distances[int(0.95 * (len(distances) - 1))]


def _topology(corset):
    bm = bmesh.new()
    bm.from_mesh(corset.data)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
    bm.free()
    return boundary, non_manifold


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["count"] < 30:
        return 0.1
    try:
        scan, settings = prepare_reference_design()
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        template = trim_templates.load_template("RIGO_CHENEAU")
        top = template["z_top_norm"]
        bottom = template["z_bot_norm"]
        low_chest = max(top[_index(theta)] for theta in (-30, 0, 30))
        wing = max(top[_index(theta)] for theta in (60, 75, 90))
        opposite = max(top[_index(theta)] for theta in (-105, -90, -75))
        pelvis_range = max(bottom) - min(bottom)
        profile_ok = (
            low_chest < 0.40
            and wing > 0.90
            and wing - opposite > 0.35
            and pelvis_range < 0.25
            and bool(template.get("requires_orthotist_review"))
        )
        _write(
            f"profile low_chest={low_chest:.3f} wing={wing:.3f} "
            f"opposite={opposite:.3f} pelvis_range={pelvis_range:.3f} ok={profile_ok}"
        )

        # Deliberately float one control point 60 mm away, then prove Fit returns
        # every raw point and the evaluated Bezier to the corrected mold.
        point = perimeter.data.splines[0].bezier_points[8]
        original_point = point.co.copy()
        axis = perimeter.get("rigo_trim_axis")
        point_world = perimeter.matrix_world @ point.co
        radial = point_world.copy()
        radial.x -= float(axis[0])
        radial.y -= float(axis[1])
        radial.z = 0.0
        radial.normalize()
        point.co = perimeter.matrix_world.inverted() @ (point_world + radial * 0.060)
        bpy.ops.rigo.snap_trimline_to_surface()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        bvh = BVHTree.FromObject(scan, depsgraph)
        raw_distances = [
            _nearest_distance(scan, bvh, perimeter.matrix_world @ item.co) * 1000.0
            for item in perimeter.data.splines[0].bezier_points
        ]
        curve_max, curve_p95 = _curve_surface_metrics(scan, perimeter)
        surface_ok = (
            max(raw_distances) <= 1.7
            and min(raw_distances) >= 1.3
            and curve_p95 <= 2.5
            and curve_max <= 4.0
            and perimeter.modifiers.get("Follow Corrected Mold") is not None
        )
        _write(
            f"surface raw_min_mm={min(raw_distances):.3f} "
            f"raw_max_mm={max(raw_distances):.3f} curve_p95_mm={curve_p95:.3f} "
            f"curve_max_mm={curve_max:.3f} ok={surface_ok}"
        )
        # Keep the generator comparison deterministic; the conformance repair is
        # tested above, while the reference shell uses the unedited clinical profile.
        point.co = original_point
        bpy.ops.rigo.snap_trimline_to_surface()
        opening_ok = (
            abs(float(perimeter.get("rigo_trim_opening_mm", 0.0)) - 25.0) < 0.01
            and 8.0 < float(perimeter.get("rigo_trim_opening_deg", 0.0)) < 35.0
        )
        _write(
            f"opening requested_mm={perimeter.get('rigo_trim_opening_mm')} "
            f"actual_angle_deg={float(perimeter.get('rigo_trim_opening_deg', 0.0)):.3f} "
            f"ok={opening_ok}"
        )

        bpy.ops.rigo.generate_corset()
        corset = bpy.data.objects.get("Rigo Corset")
        boundary, non_manifold = _topology(corset)
        try:
            qa_result = bpy.ops.rigo.verify_brace_qa()
        except RuntimeError:
            qa_result = {"CANCELLED"}
        qa = evaluate_brace_qa(bpy.context, corset)
        shell_ok = (
            boundary == 0
            and non_manifold == 0
            and int(corset.get("rigo_rounded_rim_edges", 0)) > 0
            and qa_result == {"FINISHED"}
            and bool(corset.get("rigo_qa_pass", False))
        )
        _write(
            f"shell boundary={boundary} nonmanifold={non_manifold} "
            f"rounded_rim_edges={int(corset.get('rigo_rounded_rim_edges', 0))} "
            f"min_wall_mm={qa['min_thickness_mm']:.3f} "
            f"intersections={qa['self_intersection_pairs']} qa={qa_result} ok={shell_ok}"
        )
        _write(f"PASS={profile_ok and surface_ok and opening_ok and shell_ok}")
    except Exception as error:  # noqa: BLE001
        import traceback

        _write(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
