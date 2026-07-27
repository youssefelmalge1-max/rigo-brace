"""#37 CANDIDATE A prototype: topology-preserving local repair of the mold fold.

EVIDENCE ONLY - nothing in production is modified.

Mechanism being repaired: `_prepare_candidate_base` offsets with a DISPLACE
modifier, direction NORMAL. Where neighbouring vertex normals converge inside
the offset distance, adjacent offset points cross and the surface folds.

Candidate A does NOT invent a repair. This project already solved the identical
problem one stage later: `design_ops._repair_outer_offset_directions` untangles
the OUTER wall by relaxing only the colliding offset DIRECTIONS toward their
neighbours, bounded by `_limit_direction_change`, while keeping every offset
LENGTH at exactly the requested value. Applying the same proven repair to the
mold satisfies the stated constraints by construction:

  - offset LENGTH is never shortened, so the requested clearance is preserved
    and the fold is not removed by collapsing toward the patient;
  - only directions of colliding vertices and their rings change, so topology,
    vertex identity, vertex count and provenance are untouched;
  - nothing is remeshed and the source scan is never modified;
  - it is not smoothing - unaffected geometry is bit-identical.

The prototype therefore replaces ONLY the displacement step: explicit
per-vertex offset along the stored normals, with collision repair, instead of
the Displace modifier. Fairing is left exactly as it is.

  RIGO_REPAIR_FIXTURE = btype | atype        (atype is the no-op control)
  RIGO_REPAIR_OFFSETS = comma-separated clearances in mm

Writes moldrepairdbg_<fixture>.txt; quits Blender itself.
"""

import hashlib
import math
import os
import sys
import traceback

import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_design, prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import design_ops  # noqa: E402
from bl_ext.user_default.rigo_brace.operators.mesh_intersections import (  # noqa: E402
    triangle_intersection_pairs,
)

FIXTURE = os.environ.get("RIGO_REPAIR_FIXTURE", "btype")
OFFSETS = [
    float(v)
    for v in os.environ.get("RIGO_REPAIR_OFFSETS", "0.1,0.5,1,2,3,5").split(",")
]
OUT = rf"C:\Projects\Blender Add-on Braces\moldrepairdbg_{FIXTURE}.txt"
TRIES = {"n": 0}


def _triangles(mesh):
    mesh.calc_loop_triangles()
    return [tuple(t.vertices) for t in mesh.loop_triangles]


def _offset_points(base_points, directions, distance):
    return [
        point + direction * distance
        for point, direction in zip(base_points, directions)
    ]


def _repair(base_points, normals, triangles, distance, lines):
    """Relax only colliding offset directions; never shorten the offset."""
    directions = [normal.copy() for normal in normals]
    adjacency = design_ops._vertex_adjacency(len(base_points), triangles)
    pairs = triangle_intersection_pairs(
        _offset_points(base_points, directions, distance), triangles
    )
    initial = len(pairs)
    touched = set()
    iterations = 0
    while pairs and iterations < 24:
        targets = {
            index
            for first, second in pairs
            for triangle in (first, second)
            for index in triangles[triangle]
        }
        touched.update(targets)
        previous = [direction.copy() for direction in directions]
        for index in targets:
            average = sum(
                (previous[other] for other in adjacency[index]),
                previous[index].copy(),
            )
            if average.length_squared <= 1e-20:
                continue
            candidate = previous[index].lerp(average.normalized(), 0.5)
            if candidate.length_squared <= 1e-20:
                continue
            directions[index] = design_ops._limit_direction_change(
                normals[index], candidate.normalized()
            )
        iterations += 1
        pairs = triangle_intersection_pairs(
            _offset_points(base_points, directions, distance), triangles
        )
    return directions, initial, len(pairs), touched, iterations


def _connected_regions(triangles, touched):
    ring = {}
    for triangle in triangles:
        for i in range(3):
            a, b = triangle[i], triangle[(i + 1) % 3]
            if a in touched and b in touched:
                ring.setdefault(a, set()).add(b)
                ring.setdefault(b, set()).add(a)
    seen, regions = set(), []
    for start in touched:
        if start in seen:
            continue
        stack, group = [start], set()
        while stack:
            node = stack.pop()
            if node in group:
                continue
            group.add(node)
            stack.extend(ring.get(node, ()) - group)
        seen |= group
        regions.append(group)
    return regions


def _quality(points, triangles):
    worst_aspect, inverted, smallest = 0.0, 0, math.inf
    for tri in triangles:
        a, b, c = (points[i] for i in tri)
        edges = ((b - a).length, (c - b).length, (a - c).length)
        area = (b - a).cross(c - a).length * 0.5
        smallest = min(smallest, area)
        if area <= 1e-14:
            inverted += 1
            continue
        worst_aspect = max(worst_aspect, max(edges) / (2.0 * area / max(edges)))
    return worst_aspect, inverted, smallest


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
        lines.append(
            "repair = relax colliding offset DIRECTIONS only "
            "(design_ops._repair_outer_offset_directions mechanism); "
            "offset LENGTH always exactly the requested clearance"
        )
        lines.append("")

        mesh = scan.data
        mesh.calc_normals_split() if hasattr(mesh, "calc_normals_split") else None
        base_points = [v.co.copy() for v in mesh.vertices]
        normals = [v.normal.copy().normalized() for v in mesh.vertices]
        triangles = _triangles(mesh)

        for offset_mm in OFFSETS:
            distance = offset_mm * 0.001
            naive = _offset_points(base_points, normals, distance)
            before = triangle_intersection_pairs(naive, triangles)
            directions, initial, remaining, touched, iterations = _repair(
                base_points, normals, triangles, distance, lines
            )
            repaired = _offset_points(base_points, directions, distance)

            moved = [
                (repaired[i] - naive[i]).length
                for i in range(len(repaired))
            ]
            moved_nonzero = [value for value in moved if value > 1e-12]
            outside = [
                moved[i] for i in range(len(moved)) if i not in touched
            ]
            # Signed offset error: the delivered gap along the ORIGINAL normal.
            delivered = [
                (repaired[i] - base_points[i]).dot(normals[i])
                for i in touched
            ] or [distance]
            regions = _connected_regions(triangles, touched)
            aspect, inverted, smallest_area = _quality(repaired, triangles)
            digest = hashlib.sha256(
                repr([tuple(round(c, 9) for c in p) for p in repaired]).encode()
            ).hexdigest()[:12]

            lines.append(
                f"clearance {offset_mm:5.2f}mm: selfX {len(before)} -> {remaining} "
                f"in {iterations} passes"
            )
            if touched:
                lines.append(
                    f"    repaired {len(touched)} verts of {len(base_points)} "
                    f"({100.0*len(touched)/len(base_points):.4f}%) in "
                    f"{len(regions)} connected region(s), largest "
                    f"{max(len(r) for r in regions)} verts"
                )
                rms = math.sqrt(
                    sum(v * v for v in moved_nonzero) / max(1, len(moved_nonzero))
                )
                lines.append(
                    f"    vertex movement: max={max(moved)*1000:.4f}mm "
                    f"rms={rms*1000:.4f}mm | outside repair regions: "
                    f"max={max(outside, default=0.0)*1000:.2e}mm"
                )
                lines.append(
                    f"    delivered clearance in repaired regions: "
                    f"min={min(delivered)*1000:.4f}mm "
                    f"max={max(delivered)*1000:.4f}mm "
                    f"(requested {offset_mm:.2f}mm) -> inward loss "
                    f"{max(0.0,(distance-min(delivered)))*1000:.4f}mm, "
                    f"outward float {max(0.0,(max(delivered)-distance))*1000:.4f}mm"
                )
                lines.append(
                    f"    quality: aspect_max={aspect:.2f} inverted={inverted} "
                    f"min_area={smallest_area:.3e} verts={len(repaired)} "
                    f"(unchanged) hash={digest}"
                )
            else:
                lines.append(
                    f"    NO-OP: nothing to repair; hash={digest} "
                    f"verts={len(repaired)}"
                )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
