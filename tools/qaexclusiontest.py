"""Structural-wall exclusion guard: safety kept, rim density irrelevant.

The old guard counted excluded vertices against EVERY shell vertex, so it
measured how finely the rim was tessellated rather than whether any
load-bearing wall went unmeasured. These checks pin the replacement:

  1. a dense rounded rim passes while its structural wall is measured;
  2. changing fillet segment count does not materially move the guard,
     even though it moves the rim vertex fraction a lot;
  3. a genuinely thin structural wall still fails;
  4. a structural wall that sampling genuinely cannot reach still fails;
  5. braces with a legacy ring-only rim tag, or none at all, still evaluate.
"""

import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces")
sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators.qa_ops import (  # noqa: E402
    evaluate_brace_qa,
)

OUT = r"C:\Projects\Blender Add-on Braces\qaexclusiontest_result.txt"
TRIES = {"n": 0}
RIM_GROUP = "RIGO_RIM_BOUNDARY"
SEGMENT_TOLERANCE = 0.02   # structural exclusion must be this stable
REASON = "structural wall"


def _metrics(brace):
    report = evaluate_brace_qa(bpy.context, brace)
    return report, report.get("mesh_metrics", report)


def _describe(label, metrics):
    return (
        f"[{label}] structural_wall_exclusion="
        f"{metrics.get('structural_wall_exclusion_fraction', -1) * 100:.2f}% "
        f"({metrics.get('structural_wall_excluded_vertices')}/"
        f"{metrics.get('structural_wall_vertices')}) "
        f"rim_vertices={metrics.get('rim_vertex_fraction', -1) * 100:.2f}% "
        f"total_excluded={metrics.get('thickness_excluded_fraction', -1) * 100:.2f}% "
        f"min_wall_mm={metrics.get('min_thickness_mm', 0):.3f}"
    )


def _build(settings, segments):
    settings.trim_fillet_segments = segments
    result = bpy.ops.rigo.generate_curve_corset()
    if result != {"FINISHED"}:
        raise RuntimeError(f"generate failed at segments={segments}")
    return bpy.data.objects["Rigo Corset"]


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    checks = []
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0

        # 1 - a dense rounded rim must PASS on the exclusion guard while its
        # structural wall is genuinely measured.
        brace = _build(settings, 8)
        report, metrics = _metrics(brace)
        lines.append(_describe("dense-rim", metrics))
        exclusion_reasons = [
            reason for reason in report.get("reasons", []) if REASON in reason
        ]
        dense_ok = (
            not exclusion_reasons
            and metrics["min_thickness_mm"] >= settings.qa_min_thickness
        )
        lines.append(
            f"[dense-rim] exclusion_reasons={exclusion_reasons} "
            f"qa_passed={report.get('passed')} ok={dense_ok}"
        )
        checks.append(dense_ok)
        baseline = metrics["structural_wall_exclusion_fraction"]
        baseline_rim = metrics["rim_vertex_fraction"]

        # 2 - rim tessellation density must not move the guard.
        coarse = _metrics(_build(settings, 4))[1]
        fine = _metrics(_build(settings, 12))[1]
        lines.append(_describe("segments-4", coarse))
        lines.append(_describe("segments-12", fine))
        spread = max(
            abs(coarse["structural_wall_exclusion_fraction"] - baseline),
            abs(fine["structural_wall_exclusion_fraction"] - baseline),
        )
        rim_spread = max(
            abs(coarse["rim_vertex_fraction"] - baseline_rim),
            abs(fine["rim_vertex_fraction"] - baseline_rim),
        )
        density_ok = spread <= SEGMENT_TOLERANCE
        lines.append(
            f"[density] structural_spread={spread * 100:.2f}pp "
            f"rim_fraction_spread={rim_spread * 100:.2f}pp "
            f"tolerance={SEGMENT_TOLERANCE * 100:.0f}pp ok={density_ok}"
        )
        checks.append(density_ok)

        # 3 - a genuinely thin structural wall must still fail.
        settings.corset_thickness = 1.5
        thin_report, thin_metrics = _metrics(_build(settings, 8))
        lines.append(_describe("thin-wall", thin_metrics))
        thin_ok = (
            not thin_report.get("passed")
            and thin_metrics["min_thickness_mm"] < settings.qa_min_thickness
        )
        lines.append(
            f"[thin-wall] qa_passed={thin_report.get('passed')} "
            f"reasons={thin_report.get('reasons')} ok={thin_ok}"
        )
        checks.append(thin_ok)
        settings.corset_thickness = 4.0

        # 4 - structural wall that sampling genuinely cannot reach must still
        # fail. A diffuse rim tag shadows nearly every wall triangle, which is
        # exactly the condition the original guard existed to catch.
        brace = _build(settings, 8)
        group = brace.vertex_groups.get(RIM_GROUP)
        # Every second vertex: at every third the metric reached 19.2 %, which
        # proves it responds but sits just under the limit, so the fixture
        # would not demonstrate the guard actually firing.
        scattered = list(range(0, len(brace.data.vertices), 2))
        group.add(scattered, 1.0, "REPLACE")
        shadow_report, shadow_metrics = _metrics(brace)
        lines.append(_describe("shadowed-wall", shadow_metrics))
        shadow_ok = (
            shadow_metrics["structural_wall_exclusion_fraction"] > 0.20
            and any(
                REASON in reason for reason in shadow_report.get("reasons", [])
            )
        )
        lines.append(
            f"[shadowed-wall] reasons={shadow_report.get('reasons')} "
            f"ok={shadow_ok}"
        )
        checks.append(shadow_ok)

        # 5 - legacy braces: a ring-only rim tag, and no tag at all, must both
        # still evaluate rather than crash or fail spuriously.
        brace = _build(settings, 8)
        group = brace.vertex_groups.get(RIM_GROUP)
        ring_only = [
            vertex.index
            for vertex in brace.data.vertices
            if any(entry.group == group.index for entry in vertex.groups)
        ][::4]
        # `add` cannot shrink a group - the previous version left the full rim
        # tagged and silently re-tested the dense case. Rebuild it instead, so
        # this really is a sparse legacy-style tag.
        brace.vertex_groups.remove(group)
        brace.vertex_groups.new(name=RIM_GROUP).add(
            ring_only, 1.0, "REPLACE"
        )
        legacy_metrics = _metrics(brace)[1]
        lines.append(_describe("legacy-ring-tag", legacy_metrics))
        legacy_ok = (
            legacy_metrics["structural_wall_exclusion_fraction"] <= 0.20
        )

        brace.vertex_groups.remove(brace.vertex_groups[RIM_GROUP])
        untagged_metrics = _metrics(brace)[1]
        lines.append(_describe("no-rim-tag", untagged_metrics))
        untagged_ok = (
            untagged_metrics["structural_wall_exclusion_fraction"] == 0.0
            and untagged_metrics["rim_vertex_fraction"] == 0.0
        )
        lines.append(
            f"[legacy] ring_tag_ok={legacy_ok} untagged_ok={untagged_ok}"
        )
        checks.append(legacy_ok and untagged_ok)

        lines.append(f"PASS={all(checks)}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
