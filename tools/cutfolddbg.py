"""#37 DIAGNOSIS, part 2: which STAGE folds the inner wall?

Part 1 (`moldoffsetdbg`) falsified the recorded explanation: the offset mold
does not self-intersect at any clearance from 0.1 to 5.0 mm, and the scan it
is built from is clean. `rimoverlapdbg` shows the failures are INNER wall
against INNER wall with zero outer-wall collisions. The inner wall is a subset
of a clean surface, so the fold has to be INTRODUCED between the cut and the
final validation.

`_cut_surface` runs, in order:
    1 exact intersect with the cutter ribbon, delete cutter faces
    2 `_keep_curve_interior`      discard everything outside the trimline
    3 `_weld_exact_cut_tolerance` collapse sub-tolerance slivers
    4 `_resample_cut_boundary`    split / collapse / relax / soften cusps
                                  (this stage already contains two repair
                                   passes for folds it creates itself:
                                   `_revert_folding_relaxation` and
                                   `_repair_boundary_sliver_crossings`)

This counts self-intersections of the surface after each stage, at the default
control count and at the density that is known to fail, so the stage that
introduces them is named rather than inferred.

  RIGO_FOLD_REFINE = number of Add Curve Detail passes (0 = 42 controls,
                     1 = 84, 2 = 168)

Writes cutfolddbg_result.txt; quits Blender itself.
"""

import os
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
)
from bl_ext.user_default.rigo_brace.operators.mesh_intersections import (  # noqa: E402
    triangle_intersection_pairs,
)

OUT = r"C:\Projects\Blender Add-on Braces\cutfolddbg_result.txt"
REFINE = int(os.environ.get("RIGO_FOLD_REFINE", "0"))
TRIES = {"n": 0}
STAGES = []

_orig_keep = curve_build_ops._keep_curve_interior
_orig_weld = curve_build_ops._weld_exact_cut_tolerance
_orig_resample = curve_build_ops._resample_cut_boundary


def _count(surface, label):
    mesh = surface.data
    mesh.calc_loop_triangles()
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
    pairs = triangle_intersection_pairs(coordinates, triangles)
    smallest = min(
        (
            min(
                (coordinates[t[0]] - coordinates[t[1]]).length,
                (coordinates[t[1]] - coordinates[t[2]]).length,
                (coordinates[t[2]] - coordinates[t[0]]).length,
            )
            for t in triangles
        ),
        default=0.0,
    )
    STAGES.append(
        (label, len(pairs), len(coordinates), len(triangles), smallest * 1000.0)
    )
    return pairs


def _keep_spy(surface, retained_region):
    result = _orig_keep(surface, retained_region)
    _count(surface, "2 after keep-interior (trimline discard)")
    return result


def _weld_spy(surface):
    result = _orig_weld(surface)
    _count(surface, "3 after weld sub-tolerance slivers")
    return result


def _resample_spy(surface, settings, source_surface):
    result = _orig_resample(surface, settings, source_surface)
    _count(surface, "4 after boundary RESAMPLE (split/collapse/relax/cusp)")
    return result


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        curve_build_ops._keep_curve_interior = _keep_spy
        curve_build_ops._weld_exact_cut_tolerance = _weld_spy
        curve_build_ops._resample_cut_boundary = _resample_spy

        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        for _step in range(REFINE):
            bpy.ops.rigo.refine_trimline()
        controls = len(
            bpy.data.objects["Rigo Trim Perimeter"].data.splines[0].bezier_points
        )
        lines.append(f"trimline controls={controls} (refine passes={REFINE})")

        # Stage 1 reference: the uncut offset mold, measured independently.
        base = design_ops._prepare_candidate_base(bpy.context, scan, settings)
        _count(base, "0 offset mold BEFORE any cut")
        design_ops._remove_object_and_orphan_mesh(base)

        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:130]
        lines.append(f"generate={result} {error}")
        lines.append("")
        lines.append(
            f"{'stage':<52}{'selfX':>7}{'verts':>9}{'tris':>9}{'min_edge_mm':>13}"
        )
        for label, pairs, verts, tris, smallest in STAGES:
            lines.append(
                f"{label:<52}{pairs:>7}{verts:>9}{tris:>9}{smallest:>13.4f}"
            )
        lines.append("")
        introduced = [
            STAGES[index][0]
            for index in range(1, len(STAGES))
            if STAGES[index][1] > STAGES[index - 1][1]
        ]
        lines.append(
            "stage(s) that INCREASED the self-intersection count: "
            + (", ".join(introduced) if introduced else "none")
        )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    finally:
        curve_build_ops._keep_curve_interior = _orig_keep
        curve_build_ops._weld_exact_cut_tolerance = _orig_weld
        curve_build_ops._resample_cut_boundary = _orig_resample
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
