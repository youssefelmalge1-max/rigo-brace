"""Print the exact manufacturing-QA failure reasons for a curve-built brace."""

import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators.qa_ops import (  # noqa: E402
    evaluate_brace_qa,
)

OUT = r"C:\Projects\Blender Add-on Braces\qareasondbg_result.txt"
TRIES = {"n": 0}


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8
        bpy.ops.rigo.generate_curve_corset()
        brace = bpy.data.objects["Rigo Corset"]
        report = evaluate_brace_qa(bpy.context, brace)
        metrics = report.get("mesh_metrics", report)
        lines.append(f"qa_passed={report.get('passed')}")
        lines.append(f"required_min_mm={settings.qa_min_thickness}")
        for key in (
            "min_thickness_mm",
            "thickness_coverage",
            "thickness_excluded_vertices",
            "thickness_excluded_fraction",
            "vertices",
            "components",
            "boundary_edges",
            "nonmanifold_edges",
            "self_intersections",
        ):
            if key in metrics:
                lines.append(f"  {key}={metrics[key]}")
        lines.append("reasons:")
        for reason in report.get("reasons", []):
            lines.append(f"  - {reason}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
