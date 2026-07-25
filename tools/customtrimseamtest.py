"""Front-crossing painted trimline: seam correctness + parametric smoothing.

Why this test exists (regression for the "shell does not create" report):
the brace region is decided in a cylindrical (theta, z) parameter plane whose
seam sits at theta = 0 — the PATIENT'S FRONT. Every earlier painted-trim test
painted the region the *template* defines, and the Rigo opening sits on that
seam, so the torn-polygon bug was invisible. This test paints a region that
COVERS the front (opening at the back), which is the ordinary clinical case for
a custom-painted brace, and gates on:

  * the perimeter polygon agreeing with the painted mask (seam correctness),
  * a real shell being generated: closed, manifold, one component,
  * the shell keeping the painted side rather than its complement,
  * the trimline smoothing being parametric in mm, single-pass and deterministic.
"""

import math
import os
import sys

import bmesh
import bpy
from mathutils.kdtree import KDTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (  # noqa: E402
    _ensure_mask,
    _mask_loops,
    _mask_values,
    _smoothed_painted_boundary,
)
from bl_ext.user_default.rigo_brace.operators.design_ops import (  # noqa: E402
    _inside_polygon,
    _inside_unwrapped_polygon,
    _theta_of,
    _trim_perimeter_uv,
)

OUT = r"C:\Projects\Blender Add-on Braces\customtrimseamtest_result.txt"
TRIES = {"count": 0}

FRONT_HALF_ANGLE = math.radians(150.0)  # opening is the remaining 60 deg at back


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))


def _topology(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
    unvisited = set(bm.verts)
    components = 0
    while unvisited:
        components += 1
        pending = [unvisited.pop()]
        while pending:
            vertex = pending.pop()
            linked = {
                edge.other_vert(vertex)
                for edge in vertex.link_edges
                if edge.other_vert(vertex) in unvisited
            }
            unvisited.difference_update(linked)
            pending.extend(linked)
    bm.free()
    return boundary, nonmanifold, components


def _paint_front_band(scan, axis, front, z_low, z_high):
    """Green over the front of the torso; white elsewhere. Crosses theta = 0."""
    attribute = _ensure_mask(scan)
    painted = 0
    for vertex, entry in zip(scan.data.vertices, attribute.data):
        world = scan.matrix_world @ vertex.co
        angle = _theta_of(world.x, world.y, axis[0], axis[1], front[0], front[1])
        inside = abs(angle) <= FRONT_HALF_ANGLE and z_low <= world.z <= z_high
        entry.color = (0.0, 1.0, 0.0, 1.0) if inside else (1.0, 1.0, 1.0, 1.0)
        painted += int(inside)
    scan.data.update()
    return painted


def _polygon_mask_agreement(scan, perimeter):
    """IoU of "perimeter says inside" vs "painted green", BEFORE and AFTER.

    The unwrapped polygon differs from the pre-fix one only by whole turns, so
    wrapping it back into [0, tau) reproduces exactly the polygon the shipped
    code used to build — letting one run measure the regression and the fix on
    the same real clinical geometry.
    """
    unwrapped = _trim_perimeter_uv(bpy.context)[0]
    wrapped = [(angle % math.tau, height) for angle, height in unwrapped]
    angles = [angle for angle, _height in unwrapped]
    theta_min, theta_max = min(angles), max(angles)
    axis = perimeter["rigo_trim_axis"]
    front = perimeter["rigo_trim_front"]
    values = _mask_values(scan)
    counts = {"old_i": 0, "old_u": 0, "new_i": 0, "new_u": 0}
    for vertex, value in zip(scan.data.vertices, values):
        world = scan.matrix_world @ vertex.co
        angle = _theta_of(
            world.x,
            world.y,
            float(axis[0]),
            float(axis[1]),
            float(front[0]),
            float(front[1]),
        ) % math.tau
        wanted = value >= 0.5
        old_kept = _inside_polygon((angle, world.z), wrapped)
        new_kept = _inside_unwrapped_polygon(
            (angle, world.z), unwrapped, theta_min, theta_max
        )
        counts["old_i"] += int(old_kept and wanted)
        counts["old_u"] += int(old_kept or wanted)
        counts["new_i"] += int(new_kept and wanted)
        counts["new_u"] += int(new_kept or wanted)
    return (
        counts["old_i"] / max(1, counts["old_u"]),
        counts["new_i"] / max(1, counts["new_u"]),
        theta_min,
        theta_max,
    )


def _shell_keeps_painted_side(scan, brace):
    """Fraction of the brace's source wall sitting on painted-green scan."""
    source_vertices = int(brace.get("rigo_paired_source_vertices", 0))
    if not source_vertices:
        return 0.0
    values = _mask_values(scan)
    tree = KDTree(len(scan.data.vertices))
    for index, vertex in enumerate(scan.data.vertices):
        tree.insert(scan.matrix_world @ vertex.co, index)
    tree.balance()
    green = 0
    for vertex in list(brace.data.vertices)[:source_vertices]:
        _co, index, _distance = tree.find(brace.matrix_world @ vertex.co)
        green += int(values[index] >= 0.5)
    return green / source_vertices


def _smoothing_contract(scan):
    """Parametric, single-pass, deterministic — measured, not asserted."""
    loop = _mask_loops(scan.data, _mask_values(scan))[0]
    world = [scan.matrix_world @ point for point in loop]
    length = sum(
        (point - world[index - 1]).length for index, point in enumerate(world)
    )
    first, deviation = _smoothed_painted_boundary(world, length, 0.008)
    second, deviation_again = _smoothed_painted_boundary(world, length, 0.008)
    deterministic = deviation == deviation_again and all(
        tuple(a) == tuple(b) for a, b in zip(first, second)
    )
    _off, zero_deviation = _smoothed_painted_boundary(world, length, 0.0)
    _wide, wide_deviation = _smoothed_painted_boundary(world, length, 0.020)
    return {
        "deterministic": deterministic,
        "deviation_8mm": deviation * 1000.0,
        "deviation_0mm": zero_deviation * 1000.0,
        "deviation_20mm": wide_deviation * 1000.0,
        "monotonic": zero_deviation == 0.0 and deviation < wide_deviation,
    }


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "custom_trim_from_paint") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        template = _trim_perimeter_uv(bpy.context)
        _polygon, axis_x, axis_y, front_x, front_y = template
        heights = [(scan.matrix_world @ v.co).z for v in scan.data.vertices]
        low, high = min(heights), max(heights)
        z_low = low + 0.30 * (high - low)
        z_high = low + 0.70 * (high - low)

        settings.trim_source_mode = "CUSTOM_PAINT"
        bpy.ops.rigo.clear_trimlines()
        painted = _paint_front_band(
            scan, (axis_x, axis_y), (front_x, front_y), z_low, z_high
        )
        loops = len(_mask_loops(scan.data, _mask_values(scan)))
        lines.append(
            f"painted_vertices={painted} mask_loops={loops} "
            f"z_band=({z_low:.4f},{z_high:.4f})"
        )

        smoothing = _smoothing_contract(scan)
        lines.append(
            f"smooth_deterministic={smoothing['deterministic']} "
            f"smooth_monotonic={smoothing['monotonic']} "
            f"dev_0mm={smoothing['deviation_0mm']:.4f} "
            f"dev_8mm={smoothing['deviation_8mm']:.4f} "
            f"dev_20mm={smoothing['deviation_20mm']:.4f}"
        )

        settings.trim_custom_spacing = 6.0
        settings.trim_smooth_mm = 8.0
        trim_result = bpy.ops.rigo.custom_trim_from_paint()
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        controls = (
            len(perimeter.data.splines[0].bezier_points)
            if perimeter is not None
            else 0
        )
        stamped = (
            float(perimeter.get("rigo_trim_smoothing_mm", -1.0))
            if perimeter is not None
            else -1.0
        )
        stamped_deviation = (
            float(perimeter.get("rigo_trim_smoothing_deviation_mm", -1.0))
            if perimeter is not None
            else -1.0
        )
        lines.append(
            f"trim_result={trim_result} controls={controls} "
            f"stamped_smoothing_mm={stamped:.3f} "
            f"stamped_deviation_mm={stamped_deviation:.4f}"
        )

        if perimeter is not None:
            before, agreement, theta_min, theta_max = _polygon_mask_agreement(
                scan, perimeter
            )
        else:
            before, agreement, theta_min, theta_max = 0.0, 0.0, 0.0, 0.0
        lines.append(
            f"polygon_mask_iou_before_fix={before:.6f} "
            f"polygon_mask_iou_after_fix={agreement:.6f}"
        )
        # The seam sits at every multiple of tau, not only at zero: the unwrap
        # is free to pick any branch, so "crosses the seam" means the span
        # straddles some k*tau.
        crosses_seam = math.floor(theta_max / math.tau) > math.floor(
            theta_min / math.tau
        )
        lines.append(
            f"unwrapped_span_rad=({theta_min:.6f},{theta_max:.6f}) "
            f"crosses_seam={crosses_seam}"
        )

        settings.corset_thickness = 3.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.30
        try:
            generate_result = bpy.ops.rigo.generate_curve_corset()
            generate_error = ""
        except RuntimeError as error:
            generate_result = {"CANCELLED"}
            generate_error = str(error)
        brace = bpy.data.objects.get("Rigo Corset")
        boundary, nonmanifold, components = (
            _topology(brace) if brace is not None else (999, 999, 999)
        )
        kept_green = _shell_keeps_painted_side(scan, brace) if brace else 0.0
        lines.append(
            f"generate_result={generate_result} boundary={boundary} "
            f"nonmanifold={nonmanifold} components={components} "
            f"error={generate_error!r}"
        )
        lines.append(f"shell_on_painted_side={kept_green:.6f}")

        passed = (
            trim_result == {"FINISHED"}
            and perimeter is not None
            and loops == 1
            and painted > 500
            and abs(stamped - 8.0) < 1.0e-6
            and stamped_deviation >= 0.0
            and smoothing["deterministic"]
            and smoothing["monotonic"]
            and agreement >= 0.90
            and crosses_seam  # the fixture must really exercise the seam
            and before < 0.50  # and the old behaviour must really have failed
            and generate_result == {"FINISHED"}
            and brace is not None
            and boundary == 0
            and nonmanifold == 0
            and components == 1
            and kept_green >= 0.90
        )
        lines.append(f"PASS={passed}")
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
