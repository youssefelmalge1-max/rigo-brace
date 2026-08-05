"""Why does the PAINTED trimline branch the cut boundary?

customtrimtest refuses with "0 open and 2 non-manifold edge(s)" while the
same fixture on the TEMPLATE trimline builds cleanly. The painted curve
reports uv_polygon_crossings=0, but that test is in (theta, z) UV space and
cannot see a 3D near-approach: the cutter ribbon is extruded +/-
_CUTTER_HALF_DEPTH_M, so two stretches closer than twice that merge and
branch the boundary without the curve ever crossing itself in UV.

Measures, for the painted trimline:
  - closest NON-ADJACENT 3D self-approach of the projected samples,
  - the same for the raw control polygon,
  - where the cut boundary actually branches (positions of the vertices
    whose boundary valence is not 0 or 2),
  - the control with the sharpest turn, for comparison.
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
)
from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (  # noqa: E402
    _ensure_mask,
)
from bl_ext.user_default.rigo_brace.operators.design_ops import (  # noqa: E402
    _inside_span,
    _theta_of,
)

OUT = r"C:\Projects\Blender Add-on Braces\paintcutdbg_result.txt"
TRIES = {"n": 0}
CAP = {}

_orig_loop_count = curve_build_ops._boundary_loop_count


def _loop_spy(mesh):
    """Capture WHERE the boundary branches before the refusal is raised."""
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(mesh)
    invalid = [
        (vertex.co.copy(), sum(e.is_boundary for e in vertex.link_edges))
        for vertex in bm.verts
        if sum(e.is_boundary for e in vertex.link_edges) not in (0, 2)
    ]
    bm.free()
    if invalid and "branches" not in CAP:
        CAP["branches"] = invalid[:12]
    return _orig_loop_count(mesh)


def _min_self_approach(points, skip):
    """Closest approach between stretches far apart ALONG the closed curve."""
    count = len(points)
    if count < 8:
        return math.inf, -1, -1
    best = (math.inf, -1, -1)
    step = max(1, count // 500)
    for i in range(0, count, step):
        for j in range(0, count, step):
            separation = min((j - i) % count, (i - j) % count)
            if separation < skip:
                continue
            gap = (points[i] - points[j]).length
            if gap < best[0]:
                best = (gap, i, j)
    return best


def _paint(scan, perimeter_data):
    polygon, axis_x, axis_y, front_x, front_y = perimeter_data
    attribute = _ensure_mask(scan)
    selected = 0
    for vertex, color in zip(scan.data.vertices, attribute.data):
        world = scan.matrix_world @ vertex.co
        angle = _theta_of(
            world.x, world.y, axis_x, axis_y, front_x, front_y
        ) % math.tau
        inside = _inside_span((angle, world.z), polygon)
        color.color = (0.0, 0.0, 0.0, 1.0) if inside else (1.0, 1.0, 1.0, 1.0)
        selected += int(inside)
    scan.data.update()
    return selected


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        curve_build_ops._boundary_loop_count = _loop_spy
        half = curve_build_ops._CUTTER_HALF_DEPTH_M * 1000.0
        lines.append(
            f"cutter half depth={half:.2f} mm -> stretches closer than "
            f"{2*half:.2f} mm can merge and branch the cut"
        )
        scan, settings = prepare_reference_design()
        template = design_ops._trim_perimeter_uv(bpy.context)
        painted = _paint(scan, template)
        settings.trim_source_mode = "CUSTOM_PAINT"
        bpy.ops.rigo.clear_trimlines()
        settings.trim_custom_spacing = 6.0
        result = bpy.ops.rigo.custom_trim_from_paint()
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        controls = perimeter.data.splines[0].bezier_points
        lines.append(
            f"painted_vertices={painted} custom_trim={result} "
            f"controls={len(controls)}"
        )

        matrix = perimeter.matrix_world
        control_points = [matrix @ point.co for point in controls]
        gap, first, second = _min_self_approach(
            control_points, max(2, len(control_points) // 12)
        )
        lines.append(
            f"CONTROL polygon: min non-adjacent gap={gap*1000:.3f} mm "
            f"(controls {first} and {second})"
        )

        samples = curve_build_ops._curve_world_samples(perimeter)
        gap, first, second = _min_self_approach(
            samples, max(4, len(samples) // 12)
        )
        lines.append(
            f"SAMPLED curve: n={len(samples)} min non-adjacent gap="
            f"{gap*1000:.3f} mm (samples {first} and {second})"
        )
        if gap < 2 * curve_build_ops._CUTTER_HALF_DEPTH_M:
            lines.append(
                "  -> BELOW the merge floor: the cutter ribbon self-touches "
                "here, which branches the cut boundary"
            )
        else:
            lines.append("  -> above the merge floor; look elsewhere")
        if first >= 0:
            point = samples[first]
            lines.append(
                f"  closest pair near ({point.x:.4f},{point.y:.4f},"
                f"{point.z:.4f})"
            )

        try:
            build = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            build, error = {"CANCELLED"}, str(exc).strip()[:110]
        lines.append(f"build={build} error={error!r}")
        for position, valence in CAP.get("branches", []):
            lines.append(
                f"  BRANCH at ({position.x:.4f},{position.y:.4f},"
                f"{position.z:.4f}) boundary_edges={valence}"
            )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    finally:
        curve_build_ops._boundary_loop_count = _orig_loop_count
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
