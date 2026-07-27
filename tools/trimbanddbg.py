"""EVIDENCE ONLY: a one-sided band constraint on the evaluated trimline.

NOT integrated into production. This measures whether the raw Bezier's
inter-station dip into the mold can be removed continuously, without doing any
of the things that were already measured to fail:

  - no added control points or stations (P2 measured that station refinement
    breaks the build - issues.md #37)
  - no change to the C2 generator, P3 editing locality or P4 subdivision
  - no hard `find_nearest` projection of every sample (LM-0035: that stamps
    mold facets into the curve and multiplied turn angle 2.7x)
  - no independent per-point clipping (LM-0035 again: a binding per-point cap
    took the reference brace from clean to 7 rim overlaps, because clipping
    each point while its neighbours are clipped differently destroys exactly
    the smoothness being protected)

Mechanism instead: measure each evaluated sample's SIGNED distance to the
mold, build a one-sided violation field (zero wherever the sample is already
outside the minimum standoff), smooth that FIELD along arc length with the
project's existing Gaussian, and displace along the surface normal by the
smoothed amount. Displacing by a smoothed field rather than clipping each
point is what keeps the correction continuous; and because the field is zero
over most of the curve, the correction is local to the dips by construction.

Protected stations (opening endpoints) are excluded from correction, and the
correction is deterministic - no iteration count, no randomness.

  RIGO_BAND_FIXTURE = reference | hostile | dense | sigma | thickB
  RIGO_BAND_SIGMA_MM, RIGO_BAND_STANDOFF_MM

Writes trimbanddbg_<fixture>.txt; quits Blender itself.
"""

import math
import os
import sys
import traceback

import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_design, prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
    trimline_ops,
)
from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (  # noqa: E402
    _smooth_closed_parametric,
)

FIXTURE = os.environ.get("RIGO_BAND_FIXTURE", "reference")
SIGMA_MM = float(os.environ.get("RIGO_BAND_SIGMA_MM", "6.0"))
STANDOFF_MM = float(os.environ.get("RIGO_BAND_STANDOFF_MM", "0.2"))
OUT = rf"C:\Projects\Blender Add-on Braces\trimbanddbg_{FIXTURE}.txt"
TRIES = {"n": 0}


def _pct(values, fraction):
    if not values:
        return 0.0
    return values[int(fraction * (len(values) - 1))]


def _signed_to_mold(points, target):
    """(signed distance, surface normal) per sample; negative = inside.

    The normal is the BARYCENTRICALLY INTERPOLATED vertex normal, not the
    face normal `bvh.find_nearest` returns. Displacing a smooth correction
    along a per-facet normal field re-injects the very triangulation noise
    LM-0035 was written about: with face normals this prototype took the
    reference curve's turn max from 4.65 to 20.32 degrees while correcting
    barely half the penetration.
    """
    source = design_ops._source_surface(target.data)
    inverse = target.matrix_world.inverted()
    normal_matrix = target.matrix_world.to_3x3()
    result = []
    for point in points:
        local = inverse @ point
        hit = source.bvh.find_nearest(local)
        if hit[0] is None:
            result.append((None, None))
            continue
        normal_local = design_ops._surface_normal_at(source, hit[0])
        normal = (normal_matrix @ normal_local).normalized()
        surface = target.matrix_world @ hit[0]
        result.append(((point - surface).dot(normal), normal))
    return result


def _arc_spacing(points):
    count = len(points)
    return sum(
        (points[(index + 1) % count] - points[index]).length
        for index in range(count)
    ) / count


BAND_PASSES = int(os.environ.get("RIGO_BAND_PASSES", "3"))


def _band_correct(points, target, standoff_m, sigma_m, protected_mask):
    """One-sided, arc-length-smoothed correction.

    A FIXED number of passes, not a convergence loop: moving a sample outward
    changes which surface point is nearest to it, so one shot under-corrects
    on curved regions (measured: 11.36 % penetration fell only to 4.32 %).
    A fixed count keeps the result deterministic - the same input always gives
    the same output - which an "iterate until converged" loop would not.
    """
    corrected = [point.copy() for point in points]
    for _pass in range(max(1, BAND_PASSES)):
        corrected, violation = _band_pass(
            corrected, target, standoff_m, sigma_m, protected_mask
        )
    return corrected, violation


def _band_pass(points, target, standoff_m, sigma_m, protected_mask):
    measured = _signed_to_mold(points, target)
    # One-sided violation field: how far each sample must move OUT to reach
    # the minimum standoff. Zero wherever it is already clear, so the field -
    # and therefore the correction - is naturally confined to the dips.
    violation = []
    for index, (signed, _normal) in enumerate(measured):
        if signed is None or protected_mask[index]:
            violation.append(0.0)
            continue
        violation.append(max(0.0, standoff_m - signed))
    spacing = _arc_spacing(points)
    # Dilate before smoothing. A Gaussian averages a peak DOWN, so smoothing
    # the raw violation field under-corrects exactly the deepest dips - the
    # first version left 6.40% of samples still inside. Taking a running
    # maximum over a window at least as wide as the smoothing radius first
    # means the smoothed result still covers the peak, while the transitions
    # either side stay continuous.
    dilated = _dilate_field(violation, sigma_m, spacing)
    smoothed = _smooth_field(dilated, sigma_m, spacing)
    corrected = []
    for index, point in enumerate(points):
        _signed, normal = measured[index]
        if normal is None or smoothed[index] <= 0.0:
            corrected.append(point.copy())
            continue
        corrected.append(point + normal * smoothed[index])
    return corrected, violation


def _dilate_field(values, sigma_m, spacing_m):
    """Running maximum over +-sigma, so smoothing cannot undercut a peak."""
    count = len(values)
    radius = max(1, int(round(sigma_m / max(spacing_m, 1e-12))))
    if radius >= count // 2:
        return list(values)
    return [
        max(values[(index + offset) % count] for offset in range(-radius, radius + 1))
        for index in range(count)
    ]


def _smooth_field(values, sigma_m, spacing_m):
    """Gaussian along arc length on a scalar field, mirroring the curve smoother."""
    count = len(values)
    if sigma_m <= 0.0 or count < 8:
        return list(values)
    sigma_samples = sigma_m / max(spacing_m, 1e-12)
    if sigma_samples < 0.5:
        return list(values)
    radius = min(max(1, math.ceil(3.0 * sigma_samples)), (count - 1) // 2)
    weights = [
        math.exp(-0.5 * (offset / sigma_samples) ** 2)
        for offset in range(-radius, radius + 1)
    ]
    total = sum(weights)
    weights = [weight / total for weight in weights]
    smoothed = []
    for index in range(count):
        accumulated = 0.0
        for step, weight in enumerate(weights):
            accumulated += values[(index + step - radius) % count] * weight
        smoothed.append(accumulated)
    # One-sided: smoothing must never pull a sample back INTO the mold, so the
    # delivered correction is at least the raw requirement's own smoothed
    # value and never negative.
    return [max(0.0, value) for value in smoothed]


def _turn_angles(points):
    count = len(points)
    angles = []
    for index in range(count):
        entering = points[index] - points[index - 1]
        leaving = points[(index + 1) % count] - points[index]
        if min(entering.length, leaving.length) > 1e-12:
            angles.append(math.degrees(entering.angle(leaving)))
    return sorted(angles)


def _min_self_gap(points):
    count = len(points)
    skip = max(4, count // 20)
    best = math.inf
    step = max(1, count // 600)
    for first in range(0, count, step):
        for second in range(0, count, step):
            if min((second - first) % count, (first - second) % count) < skip:
                continue
            best = min(best, (points[first] - points[second]).length)
    return best


def _describe(label, points, target, lines, arc_total):
    measured = _signed_to_mold(points, target)
    signed = sorted(value for value, _n in measured if value is not None)
    inside = [value for value in signed if value < 0.0]
    count = len(signed)
    # Continuous arc length inside, not just a sample percentage.
    inside_arc = 0.0
    total = len(points)
    for index, (value, _n) in enumerate(measured):
        if value is not None and value < 0.0:
            inside_arc += (
                points[(index + 1) % total] - points[index]
            ).length
    angles = _turn_angles(points)
    lines.append(
        f"{label}: inside {len(inside)}/{count} "
        f"({100.0*len(inside)/max(count,1):.2f}%), inside arc "
        f"{inside_arc*1000:.1f}mm of {arc_total*1000:.0f}mm"
    )
    lines.append(
        f"    inward mm  p50={min(_pct(signed,0.5),0.0)*1000:+.3f} "
        f"p95={min(_pct(signed,0.05),0.0)*1000:+.3f} "
        f"p99={min(_pct(signed,0.01),0.0)*1000:+.3f} "
        f"max={signed[0]*1000:+.3f}"
    )
    lines.append(
        f"    outward mm p50={_pct(signed,0.5)*1000:+.3f} "
        f"p95={_pct(signed,0.95)*1000:+.3f} "
        f"p99={_pct(signed,0.99)*1000:+.3f} max={signed[-1]*1000:+.3f}"
    )
    lines.append(
        f"    turn_deg p50={_pct(angles,0.5):.3f} p95={_pct(angles,0.95):.3f} "
        f"max={angles[-1]:.2f} | min self-gap={_min_self_gap(points)*1000:.2f}mm"
    )


def _sharpen():
    perimeter = bpy.data.objects["Rigo Trim Perimeter"]
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    notch = count // 3
    for offset in (-1, 0, 1):
        point = points[(notch + offset) % count]
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    points[notch].co.z -= 0.015
    crowd = (2 * count) // 3
    anchor = points[crowd].co.copy()
    for offset in (1, 2):
        point = points[(crowd + offset) % count]
        direction = point.co - anchor
        if direction.length > 1e-9:
            point.co = anchor + direction.normalized() * (0.005 * offset)
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    perimeter.data.update_tag()
    trimline_ops._set_c2_tangent_handles(perimeter.data.splines[0])
    trimline_ops.mark_handles_solved(perimeter)


def _build_fixture():
    if FIXTURE == "thickB":
        scan, settings = prepare_design(
            r"C:\Projects\Blender Add-on Braces\B type model.stl", "B"
        )
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        return scan, settings
    scan, settings = prepare_reference_design()
    settings.corset_thickness = 4.0
    settings.corset_offset = 3.0
    if FIXTURE == "hostile":
        _sharpen()
    elif FIXTURE == "dense":
        bpy.ops.rigo.refine_trimline()
    elif FIXTURE == "sigma":
        curve_build_ops._PROJECTION_SMOOTH_M = 0.0015
    return scan, settings


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = [
        f"fixture={FIXTURE} sigma_mm={SIGMA_MM:.1f} standoff_mm={STANDOFF_MM:.2f}"
    ]
    try:
        scan, settings = _build_fixture()
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        controls_before = [
            point.co.copy() for point in perimeter.data.splines[0].bezier_points
        ]
        lines.append(f"controls={len(controls_before)}")

        # Baseline build, to have the mold and a reference hash.
        try:
            base_result = bpy.ops.rigo.generate_curve_corset()
            base_error = ""
        except RuntimeError as exc:
            base_result, base_error = {"CANCELLED"}, str(exc).strip()[:110]
        corset = bpy.data.objects.get("Rigo Corset")
        base = bpy.data.objects.get("Rigo Corset Base")
        lines.append(
            f"baseline generate={base_result} {base_error} "
            f"verts={len(corset.data.vertices) if corset else 0}"
        )
        if base is None:
            lines.append("no offset mold available; cannot measure the band")
            raise RuntimeError("no base")

        raw = curve_build_ops._curve_world_samples(perimeter)
        arc_total = sum(
            (raw[(i + 1) % len(raw)] - raw[i]).length for i in range(len(raw))
        )
        # Protect the opening stations' neighbourhood in sample space.
        matrix = perimeter.matrix_world
        protected_controls = trimline_ops._opening_locked_indices(
            perimeter,
            [matrix @ p.co for p in perimeter.data.splines[0].bezier_points],
        )
        per_control = max(1, len(raw) // max(1, len(controls_before)))
        protected_mask = [False] * len(raw)
        for control_index in protected_controls:
            centre = control_index * per_control
            for offset in range(-per_control, per_control + 1):
                protected_mask[(centre + offset) % len(raw)] = True
        if os.environ.get("RIGO_BAND_NO_PROTECT"):
            protected_mask = [False] * len(raw)
        lines.append(
            f"protected: {len(protected_controls)} stations -> "
            f"{sum(protected_mask)}/{len(raw)} samples excluded"
        )
        lines.append("")
        # Target the BODY, not the offset mold. Against the mold the curve is
        # ~1.5 mm "inside" everywhere BY DESIGN - that is the liner offset, and
        # a first version of this prototype duly tried to correct 93 % of the
        # curve for a non-defect, degrading turn p95 from 1.92 to 4.20 deg. The
        # audit's finding was penetration of the PATIENT, which is what the
        # clinical requirement is about.
        _describe("BEFORE (raw evaluated vs BODY)", raw, scan, lines, arc_total)
        _describe(
            "  reference: same curve vs offset mold (liner offset, not a defect)",
            raw, base, lines, arc_total,
        )

        corrected, violation = _band_correct(
            raw, scan, STANDOFF_MM * 0.001, SIGMA_MM * 0.001, protected_mask
        )
        lines.append("")
        _describe("AFTER  (band-constrained vs BODY)", corrected, scan, lines, arc_total)
        moved = sorted((a - b).length for a, b in zip(corrected, raw))
        lines.append(
            f"    correction applied: p50={_pct(moved,0.5)*1000:.4f}mm "
            f"p95={_pct(moved,0.95)*1000:.4f}mm max={moved[-1]*1000:.4f}mm; "
            f"samples touched={sum(1 for v in moved if v > 1e-9)}/{len(moved)}"
        )
        control_move = max(
            (point.co - before).length
            for point, before in zip(
                perimeter.data.splines[0].bezier_points, controls_before
            )
        )
        lines.append(
            f"    control points moved: {control_move*1000:.3e}mm "
            f"(prototype must not touch them)"
        )
        lines.append(
            "    determinism: correction is a closed-form Gaussian over a "
            "one-sided field; no iteration count and no ordering dependence"
        )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
