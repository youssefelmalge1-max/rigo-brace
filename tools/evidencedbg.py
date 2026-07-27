"""#37 EVIDENCE SWEEP: re-test the recorded failure cases against current code.

Measurement only. NOTHING in production is modified: `_MAX_CUSTOM_CONTROLS`,
`_PROJECTION_SMOOTH_M` and the fixture settings are overridden on the imported
MODULE OBJECT inside this process only, which is how rimwavedbg and the P2
variant probes already work in this repo. The source files are untouched.

  RIGO_EV_CASE = painted | sigma | btype
    painted : the PAINTED trimline path (custom_trim_ops), which does NOT go
              through Add Curve Detail, at control counts below / at / above
              the recorded 84 ceiling. RIGO_EV_CONTROLS sets the cap.
    sigma   : the projection de-burring sigma ceiling (1.0 shipped, 1.5
              recorded as breaking the hostile hairpin by one rim overlap).
              RIGO_EV_SIGMA sets it in mm.
    btype   : the B-type scan, recorded as failing 4 mm Solidify / outer wall.

Reports, per case: input and control count, code path, self-intersections at
every stage of `_cut_surface`, rim-overlap classification by wall, whether
generation finishes, and the first stage that turns clean geometry invalid.

Writes evidencedbg_<case>_<param>.txt; quits Blender itself.
"""

import math
import os
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_design, prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    custom_trim_ops,
    design_ops,
)
from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (  # noqa: E402
    _ensure_mask,
)
from bl_ext.user_default.rigo_brace.operators.design_ops import _theta_of  # noqa: E402
from bl_ext.user_default.rigo_brace.operators.mesh_intersections import (  # noqa: E402
    triangle_intersection_pairs,
)

CASE = os.environ.get("RIGO_EV_CASE", "painted")
CONTROLS = int(os.environ.get("RIGO_EV_CONTROLS", "84"))
SIGMA_MM = float(os.environ.get("RIGO_EV_SIGMA", "1.0"))
PARAM = CONTROLS if CASE == "painted" else (SIGMA_MM if CASE == "sigma" else "4mm")
OUT = rf"C:\Projects\Blender Add-on Braces\evidencedbg_{CASE}_{PARAM}.txt"
TRIES = {"n": 0}
STAGES = []
CLASSES = {}

_orig_keep = curve_build_ops._keep_curve_interior
_orig_weld = curve_build_ops._weld_exact_cut_tolerance
_orig_resample = curve_build_ops._resample_cut_boundary
_orig_validate_pairs = design_ops.triangle_intersection_pairs


def _count(surface, label):
    mesh = surface.data
    mesh.calc_loop_triangles()
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
    pairs = triangle_intersection_pairs(coordinates, triangles)
    STAGES.append((label, len(pairs), len(coordinates), len(triangles)))


def _keep_spy(surface, retained_region):
    result = _orig_keep(surface, retained_region)
    _count(surface, "2 keep-interior")
    return result


def _weld_spy(surface):
    result = _orig_weld(surface)
    _count(surface, "3 weld slivers")
    return result


def _resample_spy(surface, settings, source_surface):
    result = _orig_resample(surface, settings, source_surface)
    _count(surface, "4 boundary resample")
    return result


def _classify(vertex_count, index):
    if index < vertex_count:
        return "inner"
    if index < vertex_count * 2:
        return "outer"
    return "rim"


def _pairs_spy(coordinates, triangles, bvh=None):
    """Classify the FINAL validator's intersections by which wall they touch."""
    pairs = _orig_validate_pairs(coordinates, triangles, bvh)
    vertex_count = CLASSES.get("paired")
    if pairs and isinstance(vertex_count, int):
        tally = {}
        for first, second in pairs:
            kinds = set()
            for triangle_index in (first, second):
                for index in triangles[triangle_index]:
                    kinds.add(_classify(vertex_count, index))
            key = "+".join(sorted(kinds))
            tally[key] = tally.get(key, 0) + 1
        CLASSES.setdefault("tally", []).append(tally)
    return pairs


def _paint_front_band(scan, axis, front, z_low, z_high):
    attribute = _ensure_mask(scan)
    painted = 0
    for vertex, entry in zip(scan.data.vertices, attribute.data):
        world = scan.matrix_world @ vertex.co
        angle = _theta_of(world.x, world.y, axis[0], axis[1], front[0], front[1])
        inside = abs(angle) <= math.radians(150.0) and z_low <= world.z <= z_high
        entry.color = (0.0, 1.0, 0.0, 1.0) if inside else (1.0, 1.0, 1.0, 1.0)
        painted += int(inside)
    scan.data.update()
    return painted


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = [f"case={CASE} param={PARAM}"]
    try:
        curve_build_ops._keep_curve_interior = _keep_spy
        curve_build_ops._weld_exact_cut_tolerance = _weld_spy
        curve_build_ops._resample_cut_boundary = _resample_spy
        design_ops.triangle_intersection_pairs = _pairs_spy

        if CASE == "btype":
            scan, settings = prepare_design(
                r"C:\Projects\Blender Add-on Braces\B type model.stl", "B"
            )
            lines.append("path=TEMPLATE trimline on the B-type scan")
        else:
            scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0

        if CASE == "painted":
            # Runtime override on the module object; the source file is not
            # touched. This is the only way to probe above the recorded
            # ceiling without changing production.
            custom_trim_ops._MAX_CUSTOM_CONTROLS = CONTROLS
            heights = [
                (scan.matrix_world @ v.co).z for v in scan.data.vertices
            ]
            low = min(heights) + 0.25 * (max(heights) - min(heights))
            high = min(heights) + 0.80 * (max(heights) - min(heights))
            perimeter = bpy.data.objects["Rigo Trim Perimeter"]
            axis = tuple(perimeter.get("rigo_trim_axis", (0.0, 0.0)))
            front = tuple(perimeter.get("rigo_trim_front", (0.0, -1.0)))
            painted = _paint_front_band(scan, axis, front, low, high)
            lines.append(
                f"path=PAINTED (custom_trim_ops; no Add Curve Detail involved) "
                f"cap={CONTROLS} painted_verts={painted}"
            )
            try:
                trim = bpy.ops.rigo.custom_trim_from_paint()
                trim_error = ""
            except RuntimeError as exc:
                trim, trim_error = {"CANCELLED"}, str(exc).strip()[:120]
            lines.append(f"create trimline from paint={trim} {trim_error}")

        if CASE == "sigma":
            curve_build_ops._PROJECTION_SMOOTH_M = SIGMA_MM * 0.001
            lines.append(
                f"path=TEMPLATE trimline, projection sigma={SIGMA_MM:.2f}mm "
                "(1.0 shipped; 1.5 recorded as breaking the hairpin)"
            )

        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        controls = (
            len(perimeter.data.splines[0].bezier_points) if perimeter else 0
        )
        lines.append(f"trimline controls={controls}")

        base = design_ops._prepare_candidate_base(bpy.context, scan, settings)
        _count(base, "0 offset mold (uncut)")
        design_ops._remove_object_and_orphan_mesh(base)

        original_shell = curve_build_ops._build_strict_shell

        def _shell_spy(corset, s):
            CLASSES["paired"] = len(corset.data.vertices)
            return original_shell(corset, s)

        curve_build_ops._build_strict_shell = _shell_spy
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()[:150]
        finally:
            curve_build_ops._build_strict_shell = original_shell

        lines.append(f"generate={result}")
        if error:
            lines.append(f"  error={error}")
        lines.append("")
        lines.append(f"{'stage':<24}{'selfX':>7}{'verts':>9}{'tris':>9}")
        for label, pairs, verts, tris in STAGES:
            lines.append(f"{label:<24}{pairs:>7}{verts:>9}{tris:>9}")
        first_bad = next(
            (label for label, pairs, _v, _t in STAGES if pairs > 0), None
        )
        lines.append("")
        lines.append(
            f"first stage clean -> invalid: {first_bad or 'NONE (clean throughout)'}"
        )
        if CLASSES.get("tally"):
            lines.append(f"final-validator overlap classes: {CLASSES['tally'][-1]}")
        else:
            lines.append("final-validator overlap classes: none")
        corset = bpy.data.objects.get("Rigo Corset")
        if corset is not None:
            lines.append(
                f"outer-wall repair: initial="
                f"{corset.get('rigo_outer_collision_initial')} "
                f"remaining={corset.get('rigo_outer_collision_remaining')} "
                f"verts={len(corset.data.vertices)}"
            )
        lines.append(
            "reproduces historical failure: "
            + ("YES" if result == {"CANCELLED"} else "NO")
        )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    finally:
        curve_build_ops._keep_curve_interior = _orig_keep
        curve_build_ops._weld_exact_cut_tolerance = _orig_weld
        curve_build_ops._resample_cut_boundary = _orig_resample
        design_ops.triangle_intersection_pairs = _orig_validate_pairs
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
