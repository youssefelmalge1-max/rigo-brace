"""Is the visible trim-band seam a shading artifact or a real C1 break?

Classifies the finished shell into regions using the paired-index layout
(inner wall < vc, outer wall < 2vc, rim-strip intermediates >= 2vc) and
measures, per region and per BFS ring outward from the trim boundary:

  1. dihedral angle across every manifold edge (the geometric truth),
  2. vertex-normal jump along edges (what smooth shading actually shows),
  3. median edge length per ring (density grading),
  4. shading configuration (sharp edges, custom normals, smooth flags),
  5. outer silhouette wobble (turn angles along the outer boundary ring).

The junction between the rim strip and the wall faces gets its own bucket:
if the seam is geometric, the dihedral spike must sit exactly there.
"""

import math
import statistics
import sys
import traceback

import bmesh
import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

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
        result = bpy.ops.rigo.generate_curve_corset()
        lines.append(f"generate={result} fillet_request_mm={settings.trim_fillet_radius}")
        brace = bpy.data.objects["Rigo Corset"]
        mesh = brace.data
        vc = int(brace["rigo_paired_source_vertices"])
        lines.append(
            f"delivered_fillet_mm min={brace.get('rigo_trim_fillet_min_radius_mm', 0):.3f} "
            f"mean={brace.get('rigo_trim_fillet_mean_radius_mm', 0):.3f} "
            f"max={brace.get('rigo_trim_fillet_radius_mm', 0):.3f}"
        )

        # 4 - shading configuration on the final mesh
        sharp = mesh.attributes.get("sharp_edge")
        sharp_count = (
            sum(1 for entry in sharp.data if entry.value) if sharp else 0
        )
        custom = "custom_normal" in mesh.attributes
        smooth_faces = sum(1 for polygon in mesh.polygons if polygon.use_smooth)
        lines.append(
            f"shading: sharp_edges={sharp_count} custom_normals={custom} "
            f"smooth_faces={smooth_faces}/{len(mesh.polygons)}"
        )

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.index_update()
        bm.faces.index_update()

        def face_region(face):
            kinds = {(
                "strip" if v.index >= 2 * vc else
                ("inner" if v.index < vc else "outer")
            ) for v in face.verts}
            if "strip" in kinds:
                return "strip"
            if kinds == {"inner"}:
                return "inner"
            if kinds == {"outer"}:
                return "outer"
            return "mixed"

        regions = {face: face_region(face) for face in bm.faces}

        # BFS rings outward from the trim boundary on each wall
        ring_of = {}
        seeds = {
            vertex
            for face, region in regions.items()
            if region == "strip"
            for vertex in face.verts
            if vertex.index < 2 * vc
        }
        frontier = seeds
        for depth in range(RINGS + 1):
            next_frontier = set()
            for vertex in frontier:
                if vertex in ring_of:
                    continue
                ring_of[vertex] = depth
                for edge in vertex.link_edges:
                    other = edge.other_vert(vertex)
                    if other.index < 2 * vc and other not in ring_of:
                        next_frontier.add(other)
            frontier = next_frontier

        def vertex_wall(vertex):
            return "inner" if vertex.index < vc else (
                "outer" if vertex.index < 2 * vc else "strip"
            )

        # 1 - dihedral angles per bucket
        dihedral = {}
        for edge in bm.edges:
            if len(edge.link_faces) != 2:
                continue
            first, second = edge.link_faces
            angle = math.degrees(first.normal.angle(second.normal))
            a, b = regions[first], regions[second]
            if {a, b} == {"strip"}:
                key = "strip-internal"
            elif "strip" in (a, b):
                wall = a if b == "strip" else b
                key = f"JUNCTION-{wall}"
            else:
                wall = vertex_wall(edge.verts[0])
                depth = min(
                    ring_of.get(edge.verts[0], RINGS + 1),
                    ring_of.get(edge.verts[1], RINGS + 1),
                )
                key = f"{wall}-ring{min(depth, RINGS)}"
            dihedral.setdefault(key, []).append(angle)
        lines.append("1. DIHEDRAL ANGLE ACROSS EDGES (degrees)")
        for key in sorted(dihedral):
            lines.append(f"  {key:18s} {_stats(dihedral[key])}")

        # 2 - vertex-normal jump along edges, outer wall rings
        bm.normal_update()
        jumps = {}
        for edge in bm.edges:
            a, b = edge.verts
            if vertex_wall(a) != "outer" or vertex_wall(b) != "outer":
                continue
            depth = min(
                ring_of.get(a, RINGS + 1), ring_of.get(b, RINGS + 1)
            )
            angle = math.degrees(a.normal.angle(b.normal))
            jumps.setdefault(min(depth, RINGS), []).append(angle)
        lines.append("2. VERTEX-NORMAL JUMP ALONG OUTER-WALL EDGES (degrees)")
        for depth in sorted(jumps):
            lines.append(f"  ring{depth}: {_stats(jumps[depth])}")

        # 3 - edge-length grading per ring, outer wall
        lengths = {}
        for edge in bm.edges:
            a, b = edge.verts
            if vertex_wall(a) != "outer" or vertex_wall(b) != "outer":
                continue
            depth = min(
                ring_of.get(a, RINGS + 1), ring_of.get(b, RINGS + 1)
            )
            lengths.setdefault(min(depth, RINGS), []).append(
                edge.calc_length()
            )
        lines.append("3. EDGE LENGTH PER RING, OUTER WALL (mm)")
        previous = None
        for depth in sorted(lengths):
            median = statistics.median(lengths[depth]) * 1000.0
            ratio = f" step_ratio={median / previous:.2f}" if previous else ""
            lines.append(
                f"  ring{depth}: median={median:.3f} "
                f"n={len(lengths[depth])}{ratio}"
            )
            previous = median

        # 5 - outer silhouette wobble: turn angle along the outer trim ring
        outer_ring = [
            vertex for vertex in seeds if vertex.index >= vc
        ]
        strip_neighbours = {}
        for face, region in regions.items():
            if region != "strip":
                continue
            ring_members = [v for v in face.verts if vc <= v.index < 2 * vc]
            for vertex in ring_members:
                for other in ring_members:
                    if other is not vertex:
                        strip_neighbours.setdefault(vertex, set()).add(other)
        turns = []
        for vertex in outer_ring:
            neighbours = sorted(
                strip_neighbours.get(vertex, ()),
                key=lambda v: v.index,
            )
            if len(neighbours) == 2:
                entering = vertex.co - neighbours[0].co
                leaving = neighbours[1].co - vertex.co
                if min(entering.length, leaving.length) > 1e-12:
                    turns.append(math.degrees(entering.angle(leaving)))
        lines.append(
            f"5. OUTER TRIM RING TURN ANGLE (deg): {_stats(turns)}"
        )
        bm.free()
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
