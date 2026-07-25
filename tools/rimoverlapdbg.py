"""WHERE are the "local rim overlap(s)" at high trimline density?

`_validate_finished_rim` reports them as rim overlaps, but it runs
`triangle_intersection_pairs` over the WHOLE shell. The paired-shell coordinate
layout tells us which wall each triangle belongs to:

    index <  vertex_count            -> inner wall (patient contact)
    vertex_count <= index < 2*vc     -> outer wall (offset by thickness)
    index >= 2*vertex_count          -> rim fillet profile points

Classifying the offending triangles distinguishes a rim-fillet defect from an
outer-wall offset collision, which are different bugs with different fixes.
"""

import math
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    custom_trim_ops,
    design_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\rimoverlapdbg_result.txt"
TRIES = {"count": 0}
STATE = {}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


_original_pairs = design_ops.triangle_intersection_pairs
_original_shell = curve_build_ops._build_strict_shell


def _shell_spy(corset, settings):
    result = _original_shell(corset, settings)
    STATE["vertex_count"] = int(corset.get("rigo_paired_source_vertices", 0))
    STATE["repair"] = {
        k: corset.get(k)
        for k in (
            "rigo_outer_collision_initial",
            "rigo_outer_collision_remaining",
            "rigo_outer_collision_iterations",
            "rigo_outer_collision_vertices",
            "rigo_outer_collision_max_angle_deg",
        )
    }
    return result


def _pairs_spy(vertices, triangles, bvh=None):
    pairs = _original_pairs(vertices, triangles, bvh=bvh) if bvh is not None \
        else _original_pairs(vertices, triangles)
    if pairs and "offenders" not in STATE:
        STATE["offenders"] = list(pairs)[:40]
        STATE["triangles"] = [tuple(t) for t in triangles]
        STATE["verts"] = [tuple(v) for v in vertices]
    return pairs


def _classify(indices, vertex_count):
    if vertex_count <= 0:
        return "unknown"
    kinds = set()
    for index in indices:
        if index < vertex_count:
            kinds.add("inner")
        elif index < 2 * vertex_count:
            kinds.add("outer")
        else:
            kinds.add("rim")
    return "+".join(sorted(kinds))


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "generate_curve_corset") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        design_ops.triangle_intersection_pairs = _pairs_spy
        curve_build_ops._build_strict_shell = _shell_spy
        custom_trim_ops._MAX_CUSTOM_CONTROLS = int(
            __import__("os").environ.get("RIGO_DBG_CONTROLS", "240")
        )

        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8

        template = design_ops._trim_perimeter_uv(bpy.context)
        _poly, axis_x, axis_y, front_x, front_y = template
        heights = [(scan.matrix_world @ v.co).z for v in scan.data.vertices]
        low, high = min(heights), max(heights)
        attribute = custom_trim_ops._ensure_mask(scan)
        for vertex, entry in zip(scan.data.vertices, attribute.data):
            world = scan.matrix_world @ vertex.co
            angle = design_ops._theta_of(
                world.x, world.y, axis_x, axis_y, front_x, front_y
            )
            inside = (
                abs(angle) <= math.radians(150.0)
                and low + 0.30 * (high - low) <= world.z <= low + 0.70 * (high - low)
            )
            entry.color = (0.0, 1.0, 0.0, 1.0) if inside else (1.0, 1.0, 1.0, 1.0)
        scan.data.update()

        settings.trim_source_mode = "CUSTOM_PAINT"
        bpy.ops.rigo.clear_trimlines()
        settings.trim_custom_spacing = 6.0
        settings.trim_smooth_mm = 8.0
        bpy.ops.rigo.custom_trim_from_paint()
        controls = len(
            bpy.data.objects["Rigo Trim Perimeter"].data.splines[0].bezier_points
        )

        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result = {"CANCELLED"}
            error = str(exc).strip()

        vertex_count = STATE.get("vertex_count", 0)
        lines.append(
            f"cap={custom_trim_ops._MAX_CUSTOM_CONTROLS} controls={controls} "
            f"paired_source_vertices={vertex_count}"
        )
        lines.append(f"generate={result} error={error!r}")
        lines.append(f"outer_wall_repair={STATE.get('repair')}")

        offenders = STATE.get("offenders")
        if not offenders:
            lines.append("no intersecting pairs captured")
        else:
            triangles = STATE["triangles"]
            verts = STATE["verts"]
            tally = {}
            lines.append(f"captured_pairs={len(offenders)}")
            for first, second in offenders:
                a = _classify(triangles[first], vertex_count)
                b = _classify(triangles[second], vertex_count)
                key = " vs ".join(sorted((a, b)))
                tally[key] = tally.get(key, 0) + 1
            lines.append("offending pair classes:")
            for key, count in sorted(tally.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {key:38s} {count}")

            first, second = offenders[0]
            for label, tri in (("A", triangles[first]), ("B", triangles[second])):
                pts = [verts[i] for i in tri]
                edges = [
                    math.dist(pts[i], pts[(i + 1) % 3]) * 1000.0 for i in range(3)
                ]
                lines.append(
                    f"  example {label}: idx={tri} class="
                    f"{_classify(tri, vertex_count)} "
                    f"edges_mm=({edges[0]:.4f},{edges[1]:.4f},{edges[2]:.4f})"
                )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
