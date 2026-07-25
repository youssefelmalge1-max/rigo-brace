"""Does a dihedral spike sit at the rim / shell transition?

Region membership comes from the RIGO_RIM_BOUNDARY vertex group, not from
the paired-index layout, so the same measurement is valid before and after
the junction bevel (which rewrites indices).

Reports, per BFS ring outward from the rim region:
  1. dihedral angle across edges (the geometric truth - a seam is a spike),
  2. vertex-normal jump along edges (what smooth shading actually shows),
  3. median edge length (density grading),
plus the shading configuration of the final mesh.
"""

import math
import statistics
import sys
import traceback

import bmesh
import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import design_ops  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\rimseamdbg_result.txt"
TRIES = {"n": 0}
RINGS = 6


def _stats(values, scale=1.0):
    if not values:
        return "(none)"
    data = sorted(value * scale for value in values)
    return (
        f"n={len(data)} median={data[len(data) // 2]:.3f} "
        f"p95={data[int(0.95 * (len(data) - 1))]:.3f} max={data[-1]:.3f}"
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
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()
        lines.append(
            f"generate={result} error={error!r} "
            f"fillet_request_mm={settings.trim_fillet_radius}"
        )
        brace = bpy.data.objects.get("Rigo Corset")
        if brace is None:
            raise RuntimeError("no brace to measure")
        mesh = brace.data
        lines.append(
            f"vertices={len(mesh.vertices)} faces={len(mesh.polygons)} "
            f"delivered_fillet_mm min="
            f"{brace.get('rigo_trim_fillet_min_radius_mm', 0):.3f} "
            f"mean={brace.get('rigo_trim_fillet_mean_radius_mm', 0):.3f} "
            f"max={brace.get('rigo_trim_fillet_radius_mm', 0):.3f} "
            f"junction_bevel_edges={brace.get('rigo_rim_junction_bevel_edges', 0)}"
        )

        sharp = mesh.attributes.get("sharp_edge")
        sharp_count = (
            sum(1 for entry in sharp.data if entry.value) if sharp else 0
        )
        lines.append(
            f"shading: sharp_edges={sharp_count} "
            f"custom_normals={'custom_normal' in mesh.attributes} "
            f"smooth_faces="
            f"{sum(1 for p in mesh.polygons if p.use_smooth)}/{len(mesh.polygons)}"
        )

        group = brace.vertex_groups.get(design_ops._RIM_BOUNDARY_GROUP)
        if group is None:
            raise RuntimeError("rim group missing")
        rim_indices = {
            vertex.index
            for vertex in mesh.vertices
            if any(entry.group == group.index for entry in vertex.groups)
        }
        lines.append(
            f"rim_group_vertices={len(rim_indices)} "
            f"({100.0 * len(rim_indices) / max(1, len(mesh.vertices)):.1f}% "
            f"of shell)"
        )

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.index_update()
        bm.normal_update()

        # BFS rings outward from the rim region.
        ring_of = {}
        frontier = {v for v in bm.verts if v.index in rim_indices}
        for depth in range(RINGS + 1):
            following = set()
            for vertex in frontier:
                if vertex in ring_of:
                    continue
                ring_of[vertex] = depth
                for edge in vertex.link_edges:
                    other = edge.other_vert(vertex)
                    if other not in ring_of:
                        following.add(other)
            frontier = following

        def bucket(edge):
            first = ring_of.get(edge.verts[0], RINGS + 1)
            second = ring_of.get(edge.verts[1], RINGS + 1)
            if first == 0 and second == 0:
                return "rim-internal"
            if min(first, second) == 0:
                return "JUNCTION(rim->shell)"
            return f"ring{min(min(first, second), RINGS)}"

        dihedral = {}
        jumps = {}
        lengths = {}
        for edge in bm.edges:
            key = bucket(edge)
            if len(edge.link_faces) == 2:
                dihedral.setdefault(key, []).append(
                    math.degrees(
                        edge.link_faces[0].normal.angle(
                            edge.link_faces[1].normal
                        )
                    )
                )
            jumps.setdefault(key, []).append(
                math.degrees(edge.verts[0].normal.angle(edge.verts[1].normal))
            )
            lengths.setdefault(key, []).append(edge.calc_length())

        order = ["rim-internal", "JUNCTION(rim->shell)"] + [
            f"ring{depth}" for depth in range(1, RINGS + 1)
        ]
        lines.append("1. DIHEDRAL ANGLE ACROSS EDGES (degrees)")
        for key in order:
            if key in dihedral:
                lines.append(f"  {key:22s} {_stats(dihedral[key])}")
        lines.append("2. VERTEX-NORMAL JUMP ALONG EDGES (degrees)")
        for key in order:
            if key in jumps:
                lines.append(f"  {key:22s} {_stats(jumps[key])}")
        lines.append("3. EDGE LENGTH (mm)")
        previous = None
        for key in order:
            if key not in lengths:
                continue
            median = statistics.median(lengths[key]) * 1000.0
            ratio = f" step_ratio={median / previous:.2f}" if previous else ""
            lines.append(
                f"  {key:22s} median={median:.3f} n={len(lengths[key])}{ratio}"
            )
            previous = median
        bm.free()
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
