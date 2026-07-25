"""Installed-copy regression for smooth, surface-bound, filleted trim quality."""

import math
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators.qa_ops import evaluate_brace_qa
from bl_ext.user_default.rigo_brace.operators.trimline_ops import (
    _TrimBrushConfig,
    _smooth_trim_controls_local,
)


OUT = r"C:\Projects\Blender Add-on Braces\trimqualitytest_result.txt"
TRIES = {"count": 0}
LINES = []


def _write(message):
    LINES.append(str(message))
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(LINES))


def _sample_curve(perimeter, samples_per_segment=16):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated = perimeter.evaluated_get(depsgraph)
    matrix = evaluated.matrix_world
    samples = []
    for spline in evaluated.data.splines:
        points = spline.bezier_points
        for index, first in enumerate(points):
            second = points[(index + 1) % len(points)]
            segment = interpolate_bezier(
                first.co,
                first.handle_right,
                second.handle_left,
                second.co,
                samples_per_segment,
            )
            samples.extend(matrix @ coordinate for coordinate in segment[:-1])
    return samples


def _turn_metrics(samples):
    angles = []
    for index, current in enumerate(samples):
        previous = samples[index - 1]
        following = samples[(index + 1) % len(samples)]
        incoming = current - previous
        outgoing = following - current
        if incoming.length > 1.0e-8 and outgoing.length > 1.0e-8:
            angles.append(math.degrees(incoming.angle(outgoing)))
    angles.sort()
    return max(angles, default=180.0), angles[int(0.95 * (len(angles) - 1))]


def _surface_distances(scan, samples):
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    inverse = scan.matrix_world.inverted()
    distances = []
    for coordinate in samples:
        hit = bvh.find_nearest(inverse @ coordinate)
        if hit[0] is not None:
            surface_world = scan.matrix_world @ hit[0]
            distances.append((coordinate - surface_world).length * 1000.0)
    distances.sort()
    return max(distances, default=999.0), distances[
        int(0.95 * (len(distances) - 1))
    ]


def _evaluated_surface_metrics(scan, perimeter):
    """Measure the actual drawn centreline after Shrinkwrap evaluation."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    original_bevel = perimeter.data.bevel_depth
    perimeter.data.bevel_depth = 0.0
    depsgraph.update()
    evaluated = perimeter.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=depsgraph)
    samples = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    surface_max, surface_p95 = _surface_distances(scan, samples)
    bpy.data.meshes.remove(mesh)
    perimeter.data.bevel_depth = original_bevel
    depsgraph.update()
    return surface_max, surface_p95


def _topology(corset):
    bm = bmesh.new()
    bm.from_mesh(corset.data)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
    bm.free()
    return boundary, non_manifold


def _component_count(obj):
    neighbours = {vertex.index: set() for vertex in obj.data.vertices}
    for edge in obj.data.edges:
        first, second = edge.vertices
        neighbours[first].add(second)
        neighbours[second].add(first)
    remaining = set(neighbours)
    components = 0
    while remaining:
        components += 1
        pending = [remaining.pop()]
        while pending:
            linked = neighbours[pending.pop()] & remaining
            remaining.difference_update(linked)
            pending.extend(linked)
    return components


def _call_generate():
    try:
        return bpy.ops.rigo.generate_curve_corset(), ""
    except RuntimeError as error:
        return {"CANCELLED"}, str(error)


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["count"] < 30:
        return 0.1
    try:
        scan, settings = prepare_reference_design()
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        points = perimeter.data.splines[0].bezier_points

        # Recreate the reported failure: a sharp VECTOR junction and a control
        # dragged far enough to form a local kink while still shrinkwrapped.
        point_world = perimeter.matrix_world @ points[8].co
        points[8].co = perimeter.matrix_world.inverted() @ (
            point_world + Vector((0.0, 0.0, 0.018))
        )
        bpy.ops.rigo.snap_trimline_to_surface()
        for index in (7, 8, 9):
            points[index].handle_left_type = "VECTOR"
            points[index].handle_right_type = "VECTOR"
        hard_max, hard_p95 = _turn_metrics(_sample_curve(perimeter))

        bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
        smooth_result = _smooth_trim_controls_local(
            perimeter,
            scan,
            bvh,
            _TrimBrushConfig(
                center_index=8,
                radius_m=0.090,
                strength=0.65,
                visible_indices=frozenset(range(len(points))),
                lock_opening=False,
            ),
        )
        smooth_samples = _sample_curve(perimeter)
        smooth_max, smooth_p95 = _turn_metrics(smooth_samples)
        surface_max, surface_p95 = _evaluated_surface_metrics(scan, perimeter)
        handles_ok = all(
            point.handle_left_type == "FREE"
            and point.handle_right_type == "FREE"
            and (point.co - point.handle_left).cross(
                point.handle_right - point.co
            ).length <= 1.0e-7
            for point in points
        )
        from bl_ext.user_default.rigo_brace.operators.design_ops import (
            _inside_unwrapped_polygon,
            _theta_of,
            _trim_perimeter_uv,
        )

        def _inside_span(sample, polygon):
            # `_trim_perimeter_uv` returns an UNWRAPPED polygon, so a plain
            # planar odd-even test against it is wrong past the front seam.
            angles = [angle for angle, _height in polygon]
            return _inside_unwrapped_polygon(
                sample, polygon, min(angles), max(angles)
            )

        polygon_before_refine = _trim_perimeter_uv(bpy.context)[0]
        raw_before_refine = _sample_curve(perimeter, samples_per_segment=33)
        controls_before_refine = len(points)
        refine_result = bpy.ops.rigo.refine_trimline()
        refined_points = perimeter.data.splines[0].bezier_points
        polygon_after_refine = _trim_perimeter_uv(bpy.context)[0]
        axis = tuple(perimeter["rigo_trim_axis"])
        front = tuple(perimeter["rigo_trim_front"])
        region_pairs = []
        for vertex in scan.data.vertices:
            world = scan.matrix_world @ vertex.co
            angle = _theta_of(
                world.x,
                world.y,
                axis[0],
                axis[1],
                front[0],
                front[1],
            ) % math.tau
            sample = (angle, world.z)
            region_pairs.append(
                (
                    _inside_span(sample, polygon_before_refine),
                    _inside_span(sample, polygon_after_refine),
                )
            )
        region_intersection = sum(first and second for first, second in region_pairs)
        region_union = sum(first or second for first, second in region_pairs)
        refine_region_iou = region_intersection / max(1, region_union)
        raw_after_refine = _sample_curve(perimeter, samples_per_segment=17)
        refined_control_surface_max = _surface_distances(
            scan,
            [
                perimeter.matrix_world @ point.co
                for point in refined_points
            ],
        )[0]
        refine_deviation = max(
            max(abs(first[0] - second[0]), abs(first[1] - second[1]))
            for first, second in zip(
                polygon_before_refine, polygon_after_refine
            )
        )
        raw_refine_deviation = max(
            (first - second).length
            for first, second in zip(raw_before_refine, raw_after_refine)
        )
        post_refine_smooth = _smooth_trim_controls_local(
            perimeter,
            scan,
            bvh,
            _TrimBrushConfig(
                center_index=16,
                radius_m=0.060,
                strength=0.40,
                visible_indices=frozenset(range(len(refined_points))),
                lock_opening=False,
            ),
        )
        refine_ok = (
            refine_result == {"FINISHED"}
            and len(refined_points) == controls_before_refine * 2
            and len(polygon_before_refine) == len(polygon_after_refine)
            and refined_control_surface_max <= 1.75
            and refine_region_iou >= 0.995
            and post_refine_smooth.affected > 0
        )
        curve_ok = (
            smooth_result.affected > 0
            and handles_ok
            and smooth_max < hard_max
            and smooth_p95 < hard_p95
            and surface_p95 <= 1.60
            and surface_max <= 1.75
            and refine_ok
        )
        _write(
            f"curve hard_max_deg={hard_max:.3f} hard_p95_deg={hard_p95:.3f} "
            f"smooth_max_deg={smooth_max:.3f} smooth_p95_deg={smooth_p95:.3f} "
            f"surface_p95_mm={surface_p95:.3f} surface_max_mm={surface_max:.3f} "
            f"handles_clamped={handles_ok} refine={controls_before_refine}->"
            f"{len(refined_points)} raw_refine_deviation="
            f"{raw_refine_deviation:.9f} generator_refine_deviation="
            f"{refine_deviation:.9f} control_surface_max_mm="
            f"{refined_control_surface_max:.6f} region_iou="
            f"{refine_region_iou:.6f} "
            f"post_refine_affected={post_refine_smooth.affected} ok={curve_ok}"
        )

        settings.corset_thickness = 4.0
        settings.trim_fillet_radius = 0.30
        settings.trim_fillet_segments = 6
        stress_result, stress_error = _call_generate()
        stress_brace = bpy.data.objects.get("Rigo Corset")
        stress_qa = (
            evaluate_brace_qa(bpy.context, stress_brace)
            if stress_brace is not None
            else None
        )
        stress_guard_ok = (
            stress_result == {"CANCELLED"}
            and stress_brace is None
            and (
                "Trim rim cannot be built safely" in stress_error
                or "cannot be generated" in stress_error
            )
        ) or (
            stress_result == {"FINISHED"}
            and stress_qa is not None
            and not stress_qa["self_intersection_pairs"]
            and stress_qa["zero_area_faces"] == 0
        )
        _write(
            f"stress_guard result={stress_result} safe_or_blocked="
            f"{stress_guard_ok} error={stress_error!r}"
        )

        # Test the normal reviewed boundary in a fresh fixture so the prior
        # intentional kink and its retained transactional result cannot leak
        # into the acceptance case.
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        scan, settings = prepare_reference_design()
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        points = perimeter.data.splines[0].bezier_points
        bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
        _smooth_trim_controls_local(
            perimeter,
            scan,
            bvh,
            _TrimBrushConfig(
                center_index=8,
                radius_m=0.090,
                strength=0.60,
                visible_indices=frozenset(range(len(points))),
                lock_opening=False,
            ),
        )
        settings.trim_fillet_radius = 0.30
        generate_result, generate_error = _call_generate()
        corset = bpy.data.objects.get("Rigo Corset")
        boundary, non_manifold = _topology(corset)
        qa = evaluate_brace_qa(bpy.context, corset)
        # The boundary-spacing and transition-refinement properties asserted
        # here previously were written only by the retired legacy builder. The
        # curve builder reaches the same goal - a closed, well-filleted solid
        # whose rim follows the authored trim curve - by exact intersection
        # instead, and records its own accuracy, so gate on that rather than on
        # the old implementation's bookkeeping.
        build_method = str(corset.get("rigo_build_method", ""))
        curve_max_error = float(
            corset.get("rigo_trim_curve_max_error_mm", 999.0)
        )
        curve_p95_error = float(
            corset.get("rigo_trim_curve_p95_error_mm", 999.0)
        )
        rim_edges = int(corset.get("rigo_paired_rim_edges", 0))
        fillet_radius = float(corset.get("rigo_trim_fillet_radius_mm", 0.0))
        fillet_segments = int(corset.get("rigo_trim_fillet_segments", 0))
        transition_width = float(
            corset.get("rigo_trim_transition_width_mm", 0.0)
        )
        components = _component_count(corset)
        shell_ok = (
            generate_result == {"FINISHED"}
            and boundary == 0
            and non_manifold == 0
            and components == 1
            and build_method == "CURVE_EXACT"
            and rim_edges > 100
            and curve_max_error <= 5.0
            and curve_p95_error <= 0.75
            and abs(fillet_radius - 0.30) <= 0.01
            and fillet_segments == 6
            and abs(transition_width - 30.0) <= 0.01
            and not qa["self_intersection_pairs"]
        )
        _write(
            f"shell result={generate_result} boundary={boundary} "
            f"nonmanifold={non_manifold} components={components} "
            f"method={build_method} rim_edges={rim_edges} "
            f"curve_max_mm={curve_max_error:.4f} curve_p95_mm={curve_p95_error:.4f} "
            f"fillet_radius_mm={fillet_radius:.3f} "
            f"fillet_segments={fillet_segments} transition_width_mm="
            f"{transition_width:.1f} intersections="
            f"{qa['self_intersection_pairs']} error={generate_error!r} ok={shell_ok}"
        )
        _write(f"PASS={curve_ok and stress_guard_ok and shell_ok}")
    except Exception as error:  # noqa: BLE001
        import traceback

        _write(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
