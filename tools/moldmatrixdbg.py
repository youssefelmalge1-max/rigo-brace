"""#37 Order B acceptance matrix, through the REAL production path.

Every number here comes from `design_ops._prepare_candidate_base` as it now
stands - real DISPLACE, real LaplacianSmooth with the shipped
use_volume_preserve / lambda_factor / lambda_border / iterations, applied
through the modifier stack - not the stand-in Laplacian used to choose the
order.

Stages logged per clearance:
  1 source scan
  2 raw displaced offset          (fairing disabled, same code path)
  3 real production-faired offset (fairing enabled, repair suppressed)
  4 residual detection
  5 repaired faired offset        (repair active)
  6 final validated candidate base
  7 cutter / rim / completed brace

  RIGO_MATRIX_FIXTURE = btype | atype
  RIGO_MATRIX_OFFSETS = comma-separated mm

Writes moldmatrixdbg_<fixture>.txt; quits Blender itself.
"""

import hashlib
import os
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_design, prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import design_ops  # noqa: E402
from bl_ext.user_default.rigo_brace.operators.mesh_intersections import (  # noqa: E402
    triangle_intersection_pairs,
)

FIXTURE = os.environ.get("RIGO_MATRIX_FIXTURE", "btype")
OFFSETS = [
    float(v)
    for v in os.environ.get("RIGO_MATRIX_OFFSETS", "0.1,0.5,1,2,3,5").split(",")
]
OUT = rf"C:\Projects\Blender Add-on Braces\moldmatrixdbg_{FIXTURE}.txt"
TRIES = {"n": 0}
_orig_repair = design_ops._repair_faired_offset


def _selfx(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    return len(
        triangle_intersection_pairs(
            [v.co.copy() for v in mesh.vertices],
            [tuple(t.vertices) for t in mesh.loop_triangles],
        )
    )


def _digest(obj):
    return hashlib.sha256(
        repr([tuple(round(c, 9) for c in v.co) for v in obj.data.vertices]).encode()
    ).hexdigest()[:12]


def _quality(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    points = [v.co for v in mesh.vertices]
    worst, degenerate, smallest = 0.0, 0, 1e9
    for tri in mesh.loop_triangles:
        a, b, c = (points[i] for i in tri.vertices)
        lengths = ((b - a).length, (c - b).length, (a - c).length)
        area = (b - a).cross(c - a).length * 0.5
        smallest = min(smallest, area)
        if area <= 1e-13:
            degenerate += 1
            continue
        worst = max(worst, max(lengths) ** 2 / (2.0 * area))
    return worst, degenerate, smallest


def _build_base(context, scan, settings, fairing, repair):
    saved = settings.corset_smooth
    settings.corset_smooth = fairing
    if not repair:
        design_ops._repair_faired_offset = lambda *a, **k: {"ran": False}
    try:
        return design_ops._prepare_candidate_base(context, scan, settings)
    finally:
        design_ops._repair_faired_offset = _orig_repair
        settings.corset_smooth = saved


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = [f"fixture={FIXTURE}"]
    try:
        if FIXTURE == "btype":
            scan, settings = prepare_design(
                r"C:\Projects\Blender Add-on Braces\B type model.stl", "B"
            )
        else:
            scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        fairing = int(settings.corset_smooth)
        lines.append(
            f"stage1 source scan: verts={len(scan.data.vertices)} "
            f"selfX={_selfx(scan)} | real fairing iterations={fairing}"
        )
        lines.append("")

        for offset_mm in OFFSETS:
            settings.corset_offset = offset_mm
            lines.append(f"=== clearance {offset_mm:.2f}mm ===")

            raw = _build_base(bpy.context, scan, settings, 0, False)
            stage2 = _selfx(raw)
            design_ops._remove_object_and_orphan_mesh(raw)

            faired = _build_base(bpy.context, scan, settings, fairing, False)
            stage3 = _selfx(faired)
            faired_hash, faired_quality = _digest(faired), _quality(faired)
            faired_points = [v.co.copy() for v in faired.data.vertices]
            design_ops._remove_object_and_orphan_mesh(faired)

            error = ""
            try:
                final = _build_base(bpy.context, scan, settings, fairing, True)
                stage5 = _selfx(final)
                final_hash, final_quality = _digest(final), _quality(final)
                touched = int(final.get("rigo_base_fold_vertices", 0))
                written = int(final.get("rigo_base_fold_written", 0))
                iterations = int(final.get("rigo_base_fold_iterations", 0))
                moved = [
                    (v.co - faired_points[i]).length
                    for i, v in enumerate(final.data.vertices)
                ]
                design_ops._remove_object_and_orphan_mesh(final)
            except design_ops.InnerSurfaceFoldError as exc:
                stage5, final_hash, final_quality = -1, "-", (0, 0, 0)
                touched = iterations = written = -1
                moved = [0.0]
                error = str(exc)[:110]

            lines.append(
                f"  stage2 raw displaced selfX={stage2} | "
                f"stage3 REAL faired selfX={stage3} | "
                f"stage4 detection={'FOLD' if stage3 else 'clean'}"
            )
            if error:
                lines.append(f"  stage5 repair FAILED -> {error}")
            else:
                changed = sum(1 for value in moved if value > 0.0)
                outside = sorted(moved, reverse=True)[written:] if written >= 0 else []
                lines.append(
                    f"  stage5 repaired selfX={stage5} touched={touched} "
                    f"written={written} actually_moved={changed} "
                    f"max_move={max(moved)*1000:.4f}mm | outside written set: "
                    f"max={max(outside, default=0.0)*1000:.2e}mm"
                )
                lines.append(
                    f"  stage6 no-op={'YES' if final_hash == faired_hash else 'NO'} "
                    f"hash {faired_hash} -> {final_hash} | aspect "
                    f"{faired_quality[0]:.2f} -> {final_quality[0]:.2f} "
                    f"degen {faired_quality[1]} -> {final_quality[1]} "
                    f"min_area {faired_quality[2]:.3e} -> {final_quality[2]:.3e}"
                )

            try:
                result = bpy.ops.rigo.generate_curve_corset()
                gen_error = ""
            except RuntimeError as exc:
                result, gen_error = {"CANCELLED"}, str(exc).strip()[:100]
            corset = bpy.data.objects.get("Rigo Corset")
            lines.append(
                f"  stage7 generate={result} "
                f"verts={len(corset.data.vertices) if corset else 0} "
                f"{gen_error}"
            )
            lines.append("")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
