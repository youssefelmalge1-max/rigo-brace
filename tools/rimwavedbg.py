"""Which pipeline stage introduces the alternating boundary waviness?

Captures the boundary at six stages and measures each against a continuous
reference, so the scalloping can be attributed rather than guessed:

  1 clinical curve      the Bezier trimline, sampled densely
  2 projection          those samples pulled onto the offset mold
  3 exact cut boundary  the intersection curve, before any resampling
  4 uniform resample    after split/collapse/arc-length equalisation
  5a after relaxation   after _relax_boundary_spacing
  5b after cusp pass    after _soften_boundary_cusps
  6 final boundary      what _rim_profile actually sweeps

Reference for stages 3-6 is the PROJECTED curve (stage 2), because the
boundary is constrained to lie on the surface and cannot be compared fairly
against a curve floating off it. Stage 2 is measured against stage 1, which
isolates what projection alone costs.

Signed offsets are taken along the local binormal (curve tangent x surface
normal), so sign alternation - the signature of scalloping as opposed to a
smooth drift - is meaningful.
"""

import math
import statistics
import sys
import traceback

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\rimwavedbg_result.txt"
TRIES = {"n": 0}
CAP = {}
SMOOTH_WINDOW_M = 0.003
SMOOTH_REGION_TURN_R = 0.005

_orig_projected = curve_build_ops._projected_samples
_orig_resample = curve_build_ops._resample_cut_boundary
_orig_relax = curve_build_ops._relax_boundary_spacing
_orig_cusp = curve_build_ops._soften_boundary_cusps
_orig_curve = curve_build_ops._curve_world_samples


def _ring_coords(surface):
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(surface.data)
    ring = curve_build_ops._bm_boundary_ring(bm)
    points = [vertex.co.copy() for vertex in ring]
    bm.free()
    return points


def _curve_spy(perimeter):
    samples = _orig_curve(perimeter)
    CAP.setdefault("world_curve", [s.copy() for s in samples])
    return samples


def _projected_spy(base, perimeter):
    coordinates, normals = _orig_projected(base, perimeter)
    if "projected" not in CAP:
        CAP["projected"] = [c.copy() for c in coordinates]
        inverse = base.matrix_world.inverted()
        CAP["curve_local"] = [
            inverse @ point for point in CAP.get("world_curve", [])
        ]
        CAP["source"] = design_ops._source_surface(base.data)
    return coordinates, normals


def _relax_spy(bm, ring, anchors, source_surface):
    CAP["stage4"] = [vertex.co.copy() for vertex in ring]
    result = _orig_relax(bm, ring, anchors, source_surface)
    CAP["stage5a"] = [vertex.co.copy() for vertex in ring]
    return result


def _cusp_spy(bm, ring, source_surface, spacing):
    result = _orig_cusp(bm, ring, source_surface, spacing)
    CAP["stage5b"] = [vertex.co.copy() for vertex in ring]
    return result


def _resample_spy(surface, settings, source_surface):
    CAP["stage3"] = _ring_coords(surface)
    result = _orig_resample(surface, settings, source_surface)
    CAP["stage6"] = _ring_coords(surface)
    return result


def _reference_tree(points):
    tree = KDTree(len(points))
    for index, point in enumerate(points):
        tree.insert(point, index)
    tree.balance()
    return tree


def _signed_offsets(points, reference, tree, source):
    """Perpendicular offset of each point from the reference polyline."""
    count = len(reference)
    offsets = []
    for point in points:
        _co, index, _distance = tree.find(point)
        here = reference[index]
        tangent = reference[(index + 1) % count] - reference[index - 1]
        if tangent.length <= 1e-12:
            offsets.append(0.0)
            continue
        tangent.normalize()
        delta = point - here
        perpendicular = delta - tangent * delta.dot(tangent)
        normal = design_ops._surface_normal_at(source, here)
        binormal = tangent.cross(normal)
        if binormal.length <= 1e-12:
            offsets.append(perpendicular.length)
            continue
        offsets.append(perpendicular.dot(binormal.normalized()))
    return offsets


def _turn_angles(points):
    count = len(points)
    angles = []
    for index in range(count):
        entering = points[index] - points[index - 1]
        leaving = points[(index + 1) % count] - points[index]
        if min(entering.length, leaving.length) > 1e-12:
            angles.append(math.degrees(entering.angle(leaving)))
        else:
            angles.append(0.0)
    return angles


def _turn_radius(points, index):
    count = len(points)
    a = points[index - 1]
    b = points[index]
    c = points[(index + 1) % count]
    first, second, third = (b - a).length, (c - b).length, (c - a).length
    if min(first, second, third) <= 1e-12:
        return math.inf
    half = (first + second + third) * 0.5
    area_sq = max(half * (half - first) * (half - second) * (half - third), 0.0)
    if area_sq <= 1e-24:
        return math.inf
    return (first * second * third) / (4.0 * math.sqrt(area_sq))


def _highpass(values, points, window):
    """Residual after removing anything slower than `window` of arc length."""
    count = len(values)
    lengths = [
        (points[(i + 1) % count] - points[i]).length for i in range(count)
    ]
    smooth = []
    for index in range(count):
        total, weight = 0.0, 0.0
        walked = 0.0
        step = index
        while walked < window and step < index + count // 2:
            total += values[step % count]
            weight += 1.0
            walked += lengths[step % count]
            step += 1
        walked = 0.0
        step = index - 1
        while walked < window and step > index - count // 2:
            total += values[step % count]
            weight += 1.0
            walked += lengths[step % count]
            step -= 1
        smooth.append(total / max(1.0, weight))
    return [values[i] - smooth[i] for i in range(count)]


def _describe(label, points, reference, tree, source, lines):
    if not points or len(points) < 5:
        lines.append(f"{label}: (too few points)")
        return
    offsets = _signed_offsets(points, reference, tree, source)
    magnitude = sorted(abs(value) for value in offsets)
    count = len(offsets)
    steps = [
        abs(offsets[i] - offsets[i - 1]) for i in range(count)
    ]
    flips = sum(
        1
        for i in range(count)
        if offsets[i] * offsets[i - 1] < 0.0
    )
    angles = _turn_angles(points)
    radii = [_turn_radius(points, i) for i in range(count)]
    smooth_mask = [r > SMOOTH_REGION_TURN_R for r in radii]
    smooth_angles = sorted(
        angle for angle, ok in zip(angles, smooth_mask) if ok
    )
    smooth_dev = sorted(
        abs(value) for value, ok in zip(offsets, smooth_mask) if ok
    )
    residual = _highpass(offsets, points, SMOOTH_WINDOW_M)
    rms = math.sqrt(sum(r * r for r in residual) / count)
    ordered_angles = sorted(angles)
    lines.append(
        f"{label}: n={count} "
        f"|offset|mm p50={magnitude[count//2]*1000:.4f} "
        f"p95={magnitude[int(0.95*(count-1))]*1000:.4f} "
        f"p99={magnitude[int(0.99*(count-1))]*1000:.4f} "
        f"max={magnitude[-1]*1000:.4f}"
    )
    lines.append(
        f"    neighbour_step_mm p95={sorted(steps)[int(0.95*(count-1))]*1000:.4f} "
        f"max={max(steps)*1000:.4f} | sign_flips={flips} "
        f"({100.0*flips/count:.1f}% of points)"
    )
    lines.append(
        f"    turn_deg p50={ordered_angles[count//2]:.2f} "
        f"p95={ordered_angles[int(0.95*(count-1))]:.2f} "
        f"max={ordered_angles[-1]:.2f} | "
        f"HF_oscillation_rms_mm={rms*1000:.4f}"
    )
    if smooth_angles and smooth_dev:
        lines.append(
            f"    SMOOTH REGIONS ONLY (turnR>{SMOOTH_REGION_TURN_R*1000:.0f}mm, "
            f"n={len(smooth_angles)}): turn_p95={smooth_angles[int(0.95*(len(smooth_angles)-1))]:.2f}deg "
            f"dev_p95={smooth_dev[int(0.95*(len(smooth_dev)-1))]*1000:.4f}mm "
            f"dev_max={smooth_dev[-1]*1000:.4f}mm"
        )


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        curve_build_ops._curve_world_samples = _curve_spy
        curve_build_ops._projected_samples = _projected_spy
        curve_build_ops._resample_cut_boundary = _resample_spy
        curve_build_ops._relax_boundary_spacing = _relax_spy
        curve_build_ops._soften_boundary_cusps = _cusp_spy

        import os

        sigma = os.environ.get("RIGO_PROJ_SIGMA")
        if sigma is not None:
            curve_build_ops._PROJECTION_SMOOTH_M = float(sigma) * 0.001
        lines.append(
            f"projection sigma_mm={curve_build_ops._PROJECTION_SMOOTH_M*1000:.2f} "
            f"feature_turn_mm={curve_build_ops._PROJECTION_FEATURE_TURN_M*1000:.2f} "
            f"max_shift_mm={curve_build_ops._PROJECTION_MAX_SHIFT_M*1000:.3f}"
        )
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:120]
        lines.append(f"generate={result} error={error!r}")
        brace = bpy.data.objects.get("Rigo Corset")
        if brace is not None:
            lines.append(
                f"SAFETY: intersections="
                f"{brace.get('rigo_generation_rim_intersections')} "
                f"zero_area={brace.get('rigo_generation_zero_area_faces')} "
                f"verts={len(brace.data.vertices)} "
                f"trim_p95_mm={brace.get('rigo_trim_curve_p95_error_mm', -1):.4f} "
                f"trim_max_mm={brace.get('rigo_trim_curve_max_error_mm', -1):.4f} "
                f"radius_mean_mm="
                f"{brace.get('rigo_trim_fillet_mean_radius_mm', -1):.3f}"
            )

        source = CAP["source"]
        projected = CAP["projected"]
        curve_local = CAP["curve_local"]
        lines.append(
            f"clinical curve samples={len(curve_local)} "
            f"projected={len(projected)}"
        )
        lines.append("")

        # Stage 1: the clinical curve's own smoothness (reference for stage 2)
        curve_tree = _reference_tree(curve_local)
        angles = sorted(_turn_angles(curve_local))
        lines.append(
            f"1 CLINICAL CURVE (self): n={len(curve_local)} "
            f"turn_deg p50={angles[len(angles)//2]:.3f} "
            f"p95={angles[int(0.95*(len(angles)-1))]:.3f} max={angles[-1]:.3f}"
        )

        # Stage 2: projection cost, measured against the clinical curve
        _describe(
            "2 PROJECTION onto mold (vs clinical curve)",
            projected,
            curve_local,
            curve_tree,
            source,
            lines,
        )
        lines.append("")
        lines.append("reference for stages 3-6 = the projected curve")

        tree = _reference_tree(projected)
        for label, key in (
            ("3 EXACT CUT boundary   ", "stage3"),
            ("4 UNIFORM RESAMPLE     ", "stage4"),
            ("5a AFTER RELAXATION    ", "stage5a"),
            ("5b AFTER CUSP PASS     ", "stage5b"),
            ("6 FINAL boundary       ", "stage6"),
        ):
            _describe(label, CAP.get(key, []), projected, tree, source, lines)
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    finally:
        curve_build_ops._curve_world_samples = _orig_curve
        curve_build_ops._projected_samples = _orig_projected
        curve_build_ops._resample_cut_boundary = _orig_resample
        curve_build_ops._relax_boundary_spacing = _orig_relax
        curve_build_ops._soften_boundary_cusps = _orig_cusp
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
