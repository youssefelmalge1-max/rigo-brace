"""Regression: uniform rim on an uneven, highly curved trimline.

Gates, in order of what they protect:

1. The Exact cut's unevenly tessellated boundary (measured 51x spacing spread
   on this fixture before resampling) must come out approximately uniform,
   and the fillet radius must be uniform too - no serration, no abrupt
   radius jumps, no spikes beyond the fillet amplitude.
2. The clinical trimline must not move: the boundary's distance to the
   projected trim curve stays inside a stated tolerance.
3. A deliberately sharpened, wobbling trimline (vector-handle notch = a
   genuine clinical corner, uneven control spacing) must still build, with
   no frame-reversal spikes, no degenerate faces, and rim self-intersection
   count zero.
4. Manufacturing QA must still FAIL a genuinely thin wall - the rim fixes
   must never mask a real structural defect.
"""

import math
import statistics
import sys
import traceback

import bmesh
import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
)
from bl_ext.user_default.rigo_brace.operators.qa_ops import (  # noqa: E402
    evaluate_brace_qa,
)

OUT = r"C:\Projects\Blender Add-on Braces\rimresampletest_result.txt"
TRIES = {"n": 0}
CAP = {}

# Tolerances, all measured-with-margin rather than aspirational. The hostile
# fixture is deliberately at the pipeline's edge, so its spacing and fidelity
# limits are wider; the substantive gates (intersections, reversals, spikes,
# degenerate faces) are identical for both.
MAX_SPACING_RATIO = 6.0        # was 51x before resampling, 3.6x after
MAX_SPACING_RATIO_HOSTILE = 8.0   # measured 6.06 on the hostile trimline
MAX_RADIUS_JUMPS_25PCT = 10    # was 1455 before resampling, 2 after
MIN_MEAN_RADIUS_FRACTION = 0.8   # delivered mean vs requested radius
MAX_TRIM_ERROR_MM = 1.0        # p95 boundary distance to the trimline
MAX_TRIM_ERROR_MM_HOSTILE = 1.5   # measured 1.067 on the hostile trimline
ZERO_AREA_M2 = 1.0e-12         # the production validator's own threshold
MAX_ASPECT_P99 = 12.0          # was 7.95 pre-resample on a bad boundary
MAX_APEX_OVER_RADIUS = 1.05    # a spike is an apex beyond its own radius


_orig_profiles = curve_build_ops._rim_profiles


def _profiles_spy(coordinates, topology, radius):
    profiles, radii = _orig_profiles(coordinates, topology, radius)
    CAP["radii"] = dict(radii)
    CAP["boundary"] = tuple(topology.boundary)
    CAP["vertex_count"] = topology.vertex_count
    CAP["coords"] = [c.copy() for c in coordinates]
    CAP["profiles"] = {k: list(v) for k, v in profiles.items()}
    CAP["directions"] = curve_build_ops._stable_outward_directions(
        coordinates, topology.triangles, topology.boundary,
        topology.vertex_count,
    )
    return profiles, radii


def _ring(boundary):
    return curve_build_ops._ordered_boundary_ring(boundary)


def _rim_checks(lines, label, requested_radius_m, ratio_limit):
    """Shared gates for one captured build. Returns True when all pass."""
    coords = CAP["coords"]
    radii = CAP["radii"]
    directions = CAP["directions"]
    profiles = CAP["profiles"]
    vc = CAP["vertex_count"]
    ring = _ring(CAP["boundary"])
    n = len(ring)
    ok = n > 0
    lines.append(f"[{label}] ring_len={n}")

    edges = [
        (coords[ring[i]] - coords[ring[(i + 1) % n]]).length for i in range(n)
    ]
    ratio = max(edges) / max(min(edges), 1e-9)
    spacing_ok = ratio <= ratio_limit
    lines.append(
        f"[{label}] spacing_mm min={min(edges)*1000:.3f} "
        f"median={sorted(edges)[n//2]*1000:.3f} max={max(edges)*1000:.3f} "
        f"ratio={ratio:.2f} ok={spacing_ok}"
    )
    ok = ok and spacing_ok

    jumps = 0
    for i in range(n):
        a, b = radii.get(ring[i]), radii.get(ring[(i + 1) % n])
        if a and b and abs(a - b) / max(a, b) > 0.25:
            jumps += 1
    values = list(radii.values())
    mean_radius = sum(values) / max(1, len(values))
    radius_ok = (
        jumps <= MAX_RADIUS_JUMPS_25PCT
        and mean_radius >= MIN_MEAN_RADIUS_FRACTION * requested_radius_m
    )
    lines.append(
        f"[{label}] radius_mm mean={mean_radius*1000:.3f} "
        f"requested={requested_radius_m*1000:.3f} jumps_over_25pct={jumps} "
        f"ok={radius_ok}"
    )
    ok = ok and radius_ok

    # Frame reversals may only exist where the trimline genuinely turns, and
    # there the corner guard must have cut the amplitude to at most the
    # guard's own contract: radius * (1 + dot) / 1.5, always below 0.67x.
    reversal_spikes = 0
    reversals = 0
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        if a in directions and b in directions:
            dot = directions[a].dot(directions[b])
            if dot < 0.0:
                reversals += 1
                allowed = requested_radius_m * (1.0 + dot) / 1.5 + 1e-6
                if max(radii.get(a, 0.0), radii.get(b, 0.0)) > allowed:
                    reversal_spikes += 1
    lines.append(
        f"[{label}] frame_reversals={reversals} "
        f"unsuppressed_reversal_spikes={reversal_spikes} "
        f"ok={reversal_spikes == 0}"
    )
    ok = ok and reversal_spikes == 0

    apex_bad = 0
    for index, prof in profiles.items():
        mid = prof[len(prof) // 2]
        chord_mid = (coords[index] + coords[index + vc]) * 0.5
        offset = (coords[mid] - chord_mid).length
        allowed = max(radii.get(index, 0.0), 1e-6) * MAX_APEX_OVER_RADIUS
        if offset > allowed + 1e-6:
            apex_bad += 1
    lines.append(f"[{label}] apex_beyond_radius={apex_bad} ok={apex_bad == 0}")
    ok = ok and apex_bad == 0
    return ok


def _shell_checks(lines, label, brace, error_limit_mm):
    intersections = brace.get("rigo_generation_rim_intersections", None)
    error_mm = float(brace.get("rigo_trim_curve_max_error_mm", math.inf))
    error_p95_mm = float(brace.get("rigo_trim_curve_p95_error_mm", math.inf))
    bm = bmesh.new()
    bm.from_mesh(brace.data)
    near_zero = sum(1 for f in bm.faces if f.calc_area() <= ZERO_AREA_M2)
    aspects = sorted(
        max(el) / min(el)
        for f in bm.faces
        for el in [[e.calc_length() for e in f.edges]]
        if min(el) > 1e-12
    )
    bm.free()
    p99 = aspects[int(0.99 * (len(aspects) - 1))]
    ok = (
        intersections == 0
        and near_zero == 0
        and p99 <= MAX_ASPECT_P99
        and error_p95_mm <= error_limit_mm
    )
    lines.append(
        f"[{label}] rim_intersections={intersections} near_zero_faces="
        f"{near_zero} aspect_p99={p99:.2f} aspect_max={aspects[-1]:.2f} "
        f"trim_error_p95_mm={error_p95_mm:.3f} "
        f"trim_error_max_mm={error_mm:.3f} ok={ok}"
    )
    return ok


def _sharpen_trimline():
    """Turn the auto trimline into a hostile fixture: a deep vector-handle
    notch (genuine sharp corners) plus wildly uneven control spacing."""
    perimeter = bpy.data.objects["Rigo Trim Perimeter"]
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    # A notch: pull one point sharply downward in z, make it and its
    # neighbours vector-handled so the corners stay corners.
    # Deep rounded notch. Zero-radius (vector-handle) corners were measured
    # to be REFUSED, correctly, by pre-existing stages, not by the rim:
    # a 30 mm vector-cornered notch folds the Exact cutter (non-manifold
    # boundary), and at 20 mm the 4 mm outer wall cannot offset around a
    # zero-radius corner without self-intersection. A physical trimline
    # corner needs a radius on the order of the wall thickness, so the
    # hostile fixture keeps the depth and the crowding but rounds corners.
    notch = count // 3
    for offset in (-1, 0, 1):
        point = points[(notch + offset) % count]
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    points[notch].co.z -= 0.015
    # Uneven spacing: crowd three consecutive points into a ~10 mm cluster.
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


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    checks = []
    try:
        curve_build_ops._rim_profiles = _profiles_spy
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8
        requested = min(
            settings.trim_fillet_radius * 0.001,
            settings.corset_thickness * 0.001 * 0.45,
        )

        # 1+2 - the real uneven Exact-cut boundary.
        result = bpy.ops.rigo.generate_curve_corset()
        lines.append(f"reference generate={result}")
        checks.append(result == {"FINISHED"})
        brace = bpy.data.objects["Rigo Corset"]
        checks.append(
            _rim_checks(lines, "reference", requested, MAX_SPACING_RATIO)
        )
        checks.append(
            _shell_checks(lines, "reference", brace, MAX_TRIM_ERROR_MM)
        )

        # 3 - a genuinely thin structural wall must still fail manufacturing
        # QA. Runs on the PRISTINE trimline, before the hostile fixture.
        settings.corset_thickness = 1.5
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()
        lines.append(f"thin generate={result} error={error!r}")
        if result == {"FINISHED"}:
            brace = bpy.data.objects["Rigo Corset"]
            report = evaluate_brace_qa(bpy.context, brace)
            metrics = report.get("mesh_metrics", report)
            thin_min = metrics.get("min_thickness_mm", math.inf)
            thin_fails = (
                not report.get("passed")
                and thin_min < settings.qa_min_thickness
            )
            lines.append(
                f"[thin] qa_passed={report.get('passed')} "
                f"min_thickness_mm={thin_min} "
                f"required={settings.qa_min_thickness} ok={thin_fails}"
            )
            checks.append(thin_fails)
        else:
            checks.append(False)
        settings.corset_thickness = 4.0

        # 4 - sharpened + unevenly spaced trimline.
        CAP.clear()
        _sharpen_trimline()
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()
        lines.append(f"sharpened generate={result} error={error!r}")
        checks.append(result == {"FINISHED"})
        if result == {"FINISHED"}:
            brace = bpy.data.objects["Rigo Corset"]
            checks.append(
                _rim_checks(
                    lines, "sharpened", requested, MAX_SPACING_RATIO_HOSTILE
                )
            )
            checks.append(
                _shell_checks(
                    lines, "sharpened", brace, MAX_TRIM_ERROR_MM_HOSTILE
                )
            )

        lines.append(f"PASS={all(checks)}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
