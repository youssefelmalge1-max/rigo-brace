"""Measured prototype of the Smooth / Straighten Trimline tool kernels.

EVIDENCE ONLY - no production code changes. One mode per Blender process
(four Generates in one session has crashed the allocator before).

    RIGO_SM_MODE = whole_lo | whole_med | whole_hi | arc | straighten | blend

  whole_*     Smooth Entire Trimline at sigma 5 / 10 / 20 mm
  arc         Smooth Selected Arc on a free back arc, influence-ramped
  straighten  Straighten Selected Arc on the ANTERIOR OPENING edge - the
              user's own clinical example: straight in the front design view,
              still following body depth, endpoints = protected corners
  blend       Smooth Transition centred on one arc junction

Pipeline per mode:
  dense sample the real Bezier -> kernel on the closed polyline ->
  depth re-imposition from the target surface (interpolated normals; the
  tangential shape stays from the kernel - NOT nearest-point snapping of the
  path) -> write the processed stations back to the same 42 controls ->
  re-solve C2 -> Generate -> downstream metadata.

Writes trimsmoothdbg_<mode>.txt; quits Blender itself.
"""

import math
import os
import sys
import traceback

import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
    trimline_ops,
)
from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (  # noqa: E402
    _smooth_closed_parametric,
)

MODE = os.environ.get("RIGO_SM_MODE", "whole_med")
OUT = rf"C:\Projects\Blender Add-on Braces\trimsmoothdbg_{MODE}.txt"
TRIES = {"n": 0}
SIGMA_MM = {"whole_lo": 5.0, "whole_med": 10.0, "whole_hi": 20.0}.get(MODE, 10.0)
PRESERVE = 0.3          # blend back toward the original path
INFLUENCE_MM = 30.0     # arc end ramp
GENERATE = MODE not in ("whole_lo", "whole_hi")  # cap runtime; metrics always


def _pct(v, f):
    return sorted(v)[int(f * (len(v) - 1))] if v else 0.0


def _spacing(points):
    n = len(points)
    return [(points[(i + 1) % n] - points[i]).length for i in range(n)]


def _turns(points):
    n = len(points)
    out = []
    for i in range(n):
        a = points[i] - points[i - 1]
        b = points[(i + 1) % n] - points[i]
        out.append(math.degrees(a.angle(b)) if min(a.length, b.length) > 1e-12 else 0.0)
    return out


def _alternation(points, scan_src, inv, m3, sigma_m=0.003):
    """Sign-flip fraction of the lateral residual vs the path's smoothed self."""
    n = len(points)
    spacing = sum(_spacing(points)) / n
    smooth = _smooth_closed_parametric(points, sigma_m, spacing)
    res = []
    for i in range(n):
        t = smooth[(i + 1) % n] - smooth[i - 1]
        if t.length <= 1e-12:
            res.append(0.0)
            continue
        t.normalize()
        hit = scan_src.bvh.find_nearest(inv @ smooth[i])
        if hit[0] is None:
            res.append(0.0)
            continue
        nrm = (m3 @ design_ops._surface_normal_at(scan_src, hit[0])).normalized()
        bi = t.cross(nrm)
        d = points[i] - smooth[i]
        res.append(d.dot(bi.normalized()) if bi.length > 1e-12 else d.length)
    flips = sum(1 for i in range(n) if res[i] * res[i - 1] < 0.0)
    mag = [abs(x) for x in res]
    return flips / n, _pct(mag, 0.95), max(mag)


def _signed_gap(points, scan_src, inv, m, m3):
    out = []
    for p in points:
        hit = scan_src.bvh.find_nearest(inv @ p)
        if hit[0] is None:
            continue
        nrm = (m3 @ design_ops._surface_normal_at(scan_src, hit[0])).normalized()
        out.append((p - (m @ hit[0])).dot(nrm))
    return out


def _min_self_gap(points):
    n = len(points)
    skip = max(4, n // 20)
    step = max(1, n // 500)
    best = math.inf
    for i in range(0, n, step):
        for j in range(0, n, step):
            if min((j - i) % n, (i - j) % n) < skip:
                continue
            best = min(best, (points[i] - points[j]).length)
    return best


def _redepth(points, weights, scan_src, inv, m, m3, offset):
    """Re-impose the exact standoff along interpolated normals; keep the
    kernel's tangential shape. Only the normal component moves."""
    out = []
    for i, p in enumerate(points):
        w = weights[i]
        if w <= 0.0:
            out.append(p.copy())
            continue
        hit = scan_src.bvh.find_nearest(inv @ p)
        if hit[0] is None:
            out.append(p.copy())
            continue
        nrm = (m3 @ design_ops._surface_normal_at(scan_src, hit[0])).normalized()
        gap = (p - (m @ hit[0])).dot(nrm)
        out.append(p + nrm * ((offset - gap) * w))
    return out


def _cyclic_arc(dense_n, i0, i1):
    """Indices of the cyclic run i0..i1 (forward)."""
    run = []
    i = i0
    while True:
        run.append(i)
        if i == i1:
            return run
        i = (i + 1) % dense_n


def _ramp_weights(dense_n, run, points, ramp_mm):
    """1 inside the arc, cosine-ramped to 0 at both pinned endpoints."""
    w = [0.0] * dense_n
    lengths = _spacing(points)
    # arc-length position of each run member from each end
    total = [0.0]
    for k in range(1, len(run)):
        total.append(total[-1] + lengths[run[k - 1]])
    span = total[-1]
    ramp = min(ramp_mm * 0.001, span * 0.45)
    for k, i in enumerate(run):
        d_end = min(total[k], span - total[k])
        if d_end <= 0.0:
            w[i] = 0.0
        elif d_end >= ramp:
            w[i] = 1.0
        else:
            w[i] = 0.5 * (1.0 - math.cos(math.pi * d_end / ramp))
    return w


def _windowed_gaussian(points, weights, sigma_m):
    n = len(points)
    spacing = sum(_spacing(points)) / n
    smooth = _smooth_closed_parametric(points, sigma_m, spacing)
    return [points[i].lerp(smooth[i], weights[i]) for i in range(n)]


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = [f"mode={MODE} sigma={SIGMA_MM}mm preserve={PRESERVE} "
             f"influence={INFLUENCE_MM}mm"]
    try:
        scan, settings = prepare_reference_design()
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        mw = perimeter.matrix_world
        controls = perimeter.data.splines[0].bezier_points
        n_ctrl = len(controls)
        protected = trimline_ops._opening_locked_indices(
            perimeter, [mw @ p.co for p in controls]
        )
        scan_src = design_ops._source_surface(scan.data)
        inv = scan.matrix_world.inverted()
        m = scan.matrix_world
        m3 = m.to_3x3()
        offset = trimline_ops.SURFACE_OFFSET

        dense = curve_build_ops._curve_world_samples(perimeter)
        n = len(dense)
        per = n // n_ctrl
        pinned_dense = set()
        for c in protected:
            pinned_dense.add(c * per)

        # ---------------- baseline metrics
        base_turn = _turns(dense)
        base_alt, base_r95, base_rmax = _alternation(dense, scan_src, inv, m3)
        base_gap = _signed_gap(dense, scan_src, inv, m, m3)
        lines.append(
            f"BASELINE: turn p95={_pct(base_turn,0.95):.3f} max={max(base_turn):.2f}deg "
            f"| alternation={base_alt*100:.1f}% residual p95={base_r95*1000:.3f}mm "
            f"| gap p50={_pct(base_gap,0.5)*1000:+.2f}mm "
            f"| self-gap={_min_self_gap(dense)*1000:.1f}mm"
        )

        # ---------------- weights + kernel per mode
        weights = [1.0] * n
        view_note = ""
        if MODE.startswith("whole"):
            # pinned landmarks: zero weight in a ramped window around each
            for i in range(n):
                for c in pinned_dense:
                    d = min((i - c) % n, (c - i) % n)
                    if d < per:
                        weights[i] = min(weights[i], d / per)
            processed = _windowed_gaussian(dense, weights, SIGMA_MM * 0.001)
        elif MODE in ("arc", "blend"):
            if MODE == "arc":
                i0, i1 = 26 * per, 34 * per        # free back arc
            else:
                j = 8 * per                        # a junction on the top edge
                i0, i1 = (j - 3 * per) % n, (j + 3 * per) % n
            run = _cyclic_arc(n, i0, i1)
            weights = _ramp_weights(n, run, dense, INFLUENCE_MM)
            processed = _windowed_gaussian(dense, weights, SIGMA_MM * 0.001)
        elif MODE == "straighten":
            # the anterior opening edge: between protected corners 17 and 21
            i0, i1 = 17 * per, 21 * per
            run = _cyclic_arc(n, i0, i1)
            weights = _ramp_weights(n, run, dense, INFLUENCE_MM)
            A, B = dense[i0].copy(), dense[i1].copy()
            fx, fy = perimeter.get("rigo_trim_front", (0.0, -1.0))
            view = Vector((fx, fy, 0.0)).normalized()   # the front design view
            axis = (B - A).normalized()
            lat = axis.cross(view)
            if lat.length < 1e-9:
                lat = axis.cross(Vector((0, 0, 1)))
            lat.normalize()
            view_note = (
                f"  straighten: chord {((B-A).length)*1000:.0f}mm, view=front, "
                f"lateral axis=({lat.x:+.2f},{lat.y:+.2f},{lat.z:+.2f})"
            )
            processed = [p.copy() for p in dense]
            before_lat = [abs((dense[i] - A).dot(lat)) for i in run]
            for k, i in enumerate(run):
                d = (processed[i] - A).dot(lat)
                processed[i] -= lat * (d * weights[i])
            after_lat = [abs((processed[i] - A).dot(lat)) for i in run]
            lines.append(view_note)
            lines.append(
                f"  in-view lateral bow: before p95={_pct(before_lat,0.95)*1000:.2f} "
                f"max={max(before_lat)*1000:.2f}mm -> after "
                f"p95={_pct(after_lat,0.95)*1000:.2f} max={max(after_lat)*1000:.2f}mm"
            )
        else:
            raise ValueError(MODE)

        # preserve-shape blend + surface depth re-imposition
        processed = [dense[i].lerp(processed[i], 1.0 - PRESERVE) for i in range(n)]
        processed = _redepth(processed, weights, scan_src, inv, m, m3, offset)

        # ---------------- post-kernel metrics on the processed PATH
        disp = [(processed[i] - dense[i]).length for i in range(n)]
        pin_drift = max(((processed[i] - dense[i]).length for i in pinned_dense),
                        default=0.0)
        p_turn = _turns(processed)
        p_alt, p_r95, p_rmax = _alternation(processed, scan_src, inv, m3)
        p_gap = _signed_gap(processed, scan_src, inv, m, m3)
        lines.append(
            f"PATH AFTER: turn p95={_pct(p_turn,0.95):.3f} max={max(p_turn):.2f}deg "
            f"| alternation={p_alt*100:.1f}% residual p95={p_r95*1000:.3f}mm "
            f"| gap p50={_pct(p_gap,0.5)*1000:+.2f}mm min={min(p_gap)*1000:+.2f} "
            f"max={max(p_gap)*1000:+.2f}mm"
        )
        lines.append(
            f"  displacement p50={_pct(disp,0.5)*1000:.3f} p95={_pct(disp,0.95)*1000:.3f} "
            f"max={max(disp)*1000:.3f}mm | pinned-landmark drift={pin_drift*1000:.4f}mm "
            f"| self-gap={_min_self_gap(processed)*1000:.1f}mm"
        )

        # ---------------- write back to the SAME controls, re-solve, Generate
        inv_c = mw.inverted()
        moved_ctrl = 0
        for k in range(n_ctrl):
            target = processed[k * per]
            if (mw @ controls[k].co - target).length > 1e-9:
                controls[k].co = inv_c @ target
                moved_ctrl += 1
        trimline_ops._set_c2_tangent_handles(perimeter.data.splines[0])
        perimeter["rigo_trim_handle_model"] = "C2_PERIODIC"
        trimline_ops.mark_handles_solved(perimeter)
        perimeter.data.update_tag()
        bpy.context.view_layer.update()

        rebuilt = curve_build_ops._curve_world_samples(perimeter)
        r_turn = _turns(rebuilt)
        # curve-vs-processed fidelity (how much the 42-control refit loses)
        step = max(1, len(processed) // 400)
        refit_err = []
        for i in range(0, len(processed), step):
            refit_err.append(min((rebuilt[j] - processed[i]).length
                                 for j in range(max(0, i - 2 * per),
                                                min(len(rebuilt), i + 2 * per))))
        lines.append(
            f"REBUILT CURVE: controls moved={moved_ctrl}/{n_ctrl} "
            f"turn p95={_pct(r_turn,0.95):.3f} max={max(r_turn):.2f}deg "
            f"| refit-to-path p95={_pct(refit_err,0.95)*1000:.3f} "
            f"max={max(refit_err)*1000:.3f}mm"
        )

        if GENERATE:
            try:
                result = bpy.ops.rigo.generate_curve_corset()
                err = ""
            except RuntimeError as exc:
                result, err = {"CANCELLED"}, str(exc).strip()[:120]
            corset = bpy.data.objects.get("Rigo Corset")
            lines.append(f"GENERATE={result} {err}")
            if corset is not None:
                lines.append(
                    f"  intersections={corset.get('rigo_generation_rim_intersections')} "
                    f"zero_area={corset.get('rigo_generation_zero_area_faces')} "
                    f"trim p95={corset.get('rigo_trim_curve_p95_error_mm',-1):.4f} "
                    f"max={corset.get('rigo_trim_curve_max_error_mm',-1):.4f}mm "
                    f"verts={len(corset.data.vertices)}"
                )
        else:
            lines.append("GENERATE=skipped (metrics-only mode)")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
