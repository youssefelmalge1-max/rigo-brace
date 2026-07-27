"""#37 DIAGNOSIS: where and why do neighbouring offset profiles intersect?

Measurement only - no production code is changed by this script.

Hypothesis under test. `design_ops._prepare_candidate_base` builds the inner
brace surface with a DISPLACE modifier, direction NORMAL, strength = the
clearance. That is a naive per-vertex normal displacement, not a true offset
surface. A classical result says such a displacement self-intersects wherever
the concave principal radius of curvature is smaller than the offset distance:
the local surface folds through itself. On a torso the candidates are skin
folds, the gluteal cleft, the axillary crease and the navel - all with radii
well under 3 mm.

If that is the mechanism, then:
  1. the base mesh already self-intersects BEFORE any cutting or wall building;
  2. the count grows with the clearance and shrinks toward zero as it goes to 0;
  3. the intersections sit in concave regions, not convex ones;
  4. fairing reduces but does not reliably eliminate them;
  5. a trimline that retains MORE of the base is more likely to include one -
     which is exactly the reported behaviour of the density ceiling, the
     sigma ceiling and the rejected band constraint.

That last point is the link to all five evidence cases: none of them is a
trimline defect at all, they are all the same fold being retained or excluded
by chance.

  RIGO_MOLD_OFFSETS  comma-separated clearances in mm (default 0.1,1,2,3,5)
  RIGO_MOLD_FAIRING  Laplacian iterations to use (default: the scene default)

Writes moldoffsetdbg_result.txt; quits Blender itself.
"""

import math
import os
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import design_ops  # noqa: E402
from bl_ext.user_default.rigo_brace.operators.mesh_intersections import (  # noqa: E402
    triangle_intersection_pairs,
)

OUT = r"C:\Projects\Blender Add-on Braces\moldoffsetdbg_result.txt"
OFFSETS = [
    float(value)
    for value in os.environ.get("RIGO_MOLD_OFFSETS", "0.1,1,2,3,5").split(",")
]
TRIES = {"n": 0}


def _triangles_of(mesh):
    mesh.calc_loop_triangles()
    return [tuple(triangle.vertices) for triangle in mesh.loop_triangles]


def _mean_curvature(mesh, triangles, vertex_index, neighbours):
    """Sign-carrying discrete curvature proxy at one vertex.

    Negative = concave (the surface curves away from its own normal), which is
    where a normal offset folds. Uses the cotangent-free umbrella: the mean of
    the neighbour offsets projected onto the vertex normal, divided by the mean
    edge length, so it has units of 1/length.
    """
    ring = neighbours.get(vertex_index)
    if not ring:
        return 0.0
    vertex = mesh.vertices[vertex_index]
    total = 0.0
    spacing = 0.0
    for other in ring:
        delta = mesh.vertices[other].co - vertex.co
        spacing += delta.length
        total += delta.dot(vertex.normal)
    if spacing <= 1e-12:
        return 0.0
    return (total / len(ring)) / (spacing / len(ring)) ** 2


def _neighbours(triangles):
    ring = {}
    for triangle in triangles:
        for index in range(3):
            first = triangle[index]
            second = triangle[(index + 1) % 3]
            ring.setdefault(first, set()).add(second)
            ring.setdefault(second, set()).add(first)
    return ring


def _describe_sites(mesh, triangles, pairs, ring, lines, limit=6):
    """Where the folds are, and whether those places are concave."""
    seen = []
    for first, second in pairs:
        vertices = set(triangles[first]) | set(triangles[second])
        centre = sum(
            (mesh.vertices[index].co for index in vertices),
            type(mesh.vertices[0].co)(),
        ) / len(vertices)
        curvature = sum(
            _mean_curvature(mesh, triangles, index, ring) for index in vertices
        ) / len(vertices)
        seen.append((centre, curvature))
    concave = sum(1 for _c, curvature in seen if curvature < 0.0)
    lines.append(
        f"      sites: {concave}/{len(seen)} lie in CONCAVE geometry "
        f"(negative discrete curvature)"
    )
    for centre, curvature in seen[:limit]:
        radius = math.inf if abs(curvature) < 1e-9 else 1.0 / abs(curvature)
        lines.append(
            f"        at ({centre.x*1000:.0f}, {centre.y*1000:.0f}, "
            f"{centre.z*1000:.0f})mm curvature={curvature:+.1f}/m "
            f"~radius={radius*1000:.2f}mm"
        )


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        fairing = int(os.environ.get("RIGO_MOLD_FAIRING", settings.corset_smooth))
        settings.corset_smooth = fairing
        lines.append(
            f"scan={scan.name!r} verts={len(scan.data.vertices)} "
            f"fairing={fairing} iterations"
        )
        lines.append(
            "inner surface built by design_ops._prepare_candidate_base: "
            "DISPLACE direction=NORMAL strength=clearance, then LaplacianSmooth"
        )
        lines.append("")

        control_triangles = _triangles_of(scan.data)
        control = triangle_intersection_pairs(
            [vertex.co.copy() for vertex in scan.data.vertices], control_triangles
        )
        lines.append(
            f"CONTROL - the scan itself: {len(control)} self-intersections "
            f"({len(control_triangles)} triangles). A clean scan should be 0, "
            "so anything below is created BY the offset."
        )
        lines.append("")
        lines.append("=== SELF-INTERSECTIONS OF THE INNER SURFACE, BY CLEARANCE ===")
        lines.append(
            "prediction if the naive normal offset is the mechanism: count "
            "rises with clearance and approaches 0 as clearance approaches 0"
        )
        lines.append("")

        for offset_mm in OFFSETS:
            settings.corset_offset = offset_mm
            base = None
            try:
                base = design_ops._prepare_candidate_base(
                    bpy.context, scan, settings
                )
                triangles = _triangles_of(base.data)
                coordinates = [vertex.co.copy() for vertex in base.data.vertices]
                pairs = triangle_intersection_pairs(coordinates, triangles)
                lines.append(
                    f"  clearance {offset_mm:5.2f}mm -> "
                    f"{len(pairs):4d} self-intersecting triangle pairs "
                    f"({len(triangles)} triangles, {len(coordinates)} verts)"
                )
                if pairs:
                    ring = _neighbours(triangles)
                    _describe_sites(base.data, triangles, pairs, ring, lines)
            finally:
                if base is not None and design_ops._object_is_registered(base):
                    design_ops._remove_object_and_orphan_mesh(base)
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
