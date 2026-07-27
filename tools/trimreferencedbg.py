"""Reconcile trimline penetration against EACH reference surface separately.

A report in this project stated the protected-zone residual as a "sub-millimetre
dip" when it had been measured at -2.400 mm. The figure was carried across
without its reference surface, which is the one mistake that makes these
numbers useless for a clinical decision. This measures every curve against
every candidate surface explicitly, and reports the protected zone separately
from the rest, because that split is what the future opening policy turns on.

Reference surfaces, stated exactly:

  BODY / source scan   `A type model` - the patient geometry as imported.
                       In this fixture no deform or pad is applied, so the
                       corrected body is IDENTICAL to the source scan; there
                       is no distinct third surface to report.
  OFFSET MOLD          `Rigo Corset Base` = scan displaced +3.0 mm along the
                       normal (liner) then Laplacian-faired. The cutter
                       projects onto THIS.

POLICY CORRECTION 2026-07-27 (project owner): the trimline must NOT have an
independent body offset. Clearance is a property of the brace - it is the gap
between the corrected body and the generated INNER BRACE SURFACE - and the
authoritative trimline must lie ON that generated inner surface, following its
curvature along its whole evaluated length.

So the current `SURFACE_OFFSET = 1.5 mm` standoff from the BODY is itself the
defect, not a design choice. Earlier notes in this file described the
resulting ~1.5 mm gap to the mold as "by design"; that described the old
architecture and is retracted. Against the correct reference - the generated
inner brace surface - that gap is a real adherence failure, and the numbers
below are the baseline for fixing it.

Distances against the BODY are still reported, but only to show that the
control points are consistently placed; the BODY is no longer the surface the
trimline should be constrained to.

Writes trimreferencedbg_result.txt; quits Blender itself.
"""

import math
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
    trimline_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimreferencedbg_result.txt"
TRIES = {"n": 0}


def _pct(values, fraction):
    if not values:
        return 0.0
    return values[int(fraction * (len(values) - 1))]


def _signed(points, target):
    """Signed distance along the interpolated surface normal; - = inside."""
    source = design_ops._source_surface(target.data)
    inverse = target.matrix_world.inverted()
    rotation = target.matrix_world.to_3x3()
    out = []
    for point in points:
        hit = source.bvh.find_nearest(inverse @ point)
        if hit[0] is None:
            out.append(None)
            continue
        normal = (rotation @ design_ops._surface_normal_at(source, hit[0])).normalized()
        out.append((point - target.matrix_world @ hit[0]).dot(normal))
    return out


def _stats(label, signed, points, lines, indent="    "):
    values = sorted(value for value in signed if value is not None)
    if not values:
        lines.append(f"{indent}{label}: (no samples)")
        return
    inside = [value for value in values if value < 0.0]
    arc = 0.0
    count = len(points)
    for index, value in enumerate(signed):
        if value is not None and value < 0.0:
            arc += (points[(index + 1) % count] - points[index]).length
    lines.append(
        f"{indent}{label}: n={len(values)} inside={len(inside)} "
        f"({100.0*len(inside)/len(values):.2f}%) inside_arc={arc*1000:.1f}mm"
    )
    # Signed percentiles as the acceptance audit specifies them: p50/p95/p99
    # by MAGNITUDE of deviation from the surface, plus the two extremes.
    magnitude = sorted(abs(value) for value in values)
    lines.append(
        f"{indent}    |deviation| p50={_pct(magnitude,0.50)*1000:.3f} "
        f"p95={_pct(magnitude,0.95)*1000:.3f} "
        f"p99={_pct(magnitude,0.99)*1000:.3f} "
        f"max={magnitude[-1]*1000:.3f}mm"
    )
    lines.append(
        f"{indent}    signed: worst_penetration={values[0]*1000:+.3f}mm "
        f"max_float_away={values[-1]*1000:+.3f}mm "
        f"p50={_pct(values,0.50)*1000:+.3f}mm"
    )


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        raw = curve_build_ops._curve_world_samples(perimeter)
        matrix = perimeter.matrix_world
        points = perimeter.data.splines[0].bezier_points
        controls = [matrix @ point.co for point in points]

        protected_controls = trimline_ops._opening_locked_indices(
            perimeter, controls
        )
        per_control = max(1, len(raw) // max(1, len(points)))
        protected_mask = [False] * len(raw)
        for control_index in protected_controls:
            centre = control_index * per_control
            for offset in range(-per_control, per_control + 1):
                protected_mask[(centre + offset) % len(raw)] = True

        try:
            bpy.ops.rigo.generate_curve_corset()
        except RuntimeError:
            pass
        base = bpy.data.objects.get("Rigo Corset Base")

        lines.append("REFERENCE SURFACES")
        lines.append(
            f"  BODY / source scan = {scan.name!r} "
            "(no deform or pad applied in this fixture, so the corrected "
            "body is identical to the source scan)"
        )
        lines.append(
            f"  OFFSET MOLD = {base.name if base else 'MISSING'!r} "
            f"= scan +{settings.corset_offset:.1f}mm liner, then faired"
        )
        lines.append(
            f"  trimline's OWN offset = "
            f"{trimline_ops.SURFACE_OFFSET*1000:.1f}mm outside the BODY - the "
            "independent offset the corrected policy removes; the trimline "
            "should instead lie ON the inner brace surface"
        )
        if base is not None:
            mold_gap = sorted(
                value for value in _signed(controls, base) if value is not None
            )
            lines.append(
                f"  measured control offset from the INNER BRACE SURFACE: "
                f"p50={_pct(mold_gap,0.5)*1000:+.3f}mm - under the corrected "
                "policy this should be ~0.000mm"
            )
        lines.append("")

        protected_raw = [
            point for point, flag in zip(raw, protected_mask) if flag
        ]
        open_raw = [
            point for point, flag in zip(raw, protected_mask) if not flag
        ]
        lines.append(
            f"protected opening zone = {len(protected_controls)} stations, "
            f"{len(protected_raw)}/{len(raw)} evaluated samples"
        )
        lines.append("")

        for surface_label, surface in (
            ("vs BODY (placement check only; NOT the constraint surface)", scan),
            (
                "vs INNER BRACE SURFACE (the correct reference; target ~0.000mm)",
                base,
            ),
        ):
            if surface is None:
                continue
            lines.append(f"=== AUTHORITATIVE RAW BEZIER {surface_label} ===")
            _stats("whole curve", _signed(raw, surface), raw, lines)
            _stats(
                "PROTECTED opening zone only",
                _signed(protected_raw, surface),
                protected_raw,
                lines,
            )
            _stats(
                "everywhere else (correctable)",
                _signed(open_raw, surface),
                open_raw,
                lines,
            )
            lines.append(
                f"    CONTROL POINTS only: "
                + ", ".join(
                    f"{value*1000:+.3f}"
                    for value in sorted(
                        v for v in _signed(controls, surface) if v is not None
                    )[:3]
                )
                + " ... (three deepest)"
            )
            lines.append("")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
