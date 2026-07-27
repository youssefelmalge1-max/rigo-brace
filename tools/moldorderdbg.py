"""#37 Candidate A, gaps 1 and 2: quality baseline + fairing order.

EVIDENCE ONLY - production is not modified.

Gap 1. The earlier prototype reported aspect_max 117/222/287 with no control,
so it could not say whether the repair caused them. Quality is now measured
BEFORE and AFTER on the same mesh, split into the four populations that answer
the question separately:
    full        the whole offset surface
    incident    triangles touching a repaired vertex
    regions     triangles wholly inside a connected repair region
    unaffected  everything else (must be bit-identical)

Gap 2. Production is Displace -> LaplacianSmooth. The repair can sit either
side, and the two orders are not equivalent: fairing after repair may reopen a
fold, while fairing before repair changes the surface the repair must work on.
Both are run end to end:
    order A   displace -> repair -> fair -> validate
    order B   displace -> fair -> detect/repair -> validate

For order B the offset length is whatever fairing produced; the repair relaxes
DIRECTIONS about the faired position and never resets a vertex to the nominal
clearance, which is what "preserve the existing local offset lengths" requires.

  RIGO_ORDER_FIXTURE = btype | atype
  RIGO_ORDER_OFFSETS = comma-separated mm

Writes moldorderdbg_<fixture>.txt; quits Blender itself.
"""

import hashlib
import math
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

FIXTURE = os.environ.get("RIGO_ORDER_FIXTURE", "btype")
OFFSETS = [
    float(v) for v in os.environ.get("RIGO_ORDER_OFFSETS", "2,3").split(",")
]
OUT = rf"C:\Projects\Blender Add-on Braces\moldorderdbg_{FIXTURE}.txt"
TRIES = {"n": 0}


def _pct(values, fraction):
    return values[int(fraction * (len(values) - 1))] if values else 0.0


def _quality(points, triangles, subset=None):
    aspects, areas, edges = [], [], []
    degenerate = 0
    for index, tri in enumerate(triangles):
        if subset is not None and index not in subset:
            continue
        a, b, c = (points[i] for i in tri)
        lengths = ((b - a).length, (c - b).length, (a - c).length)
        area = (b - a).cross(c - a).length * 0.5
        areas.append(area)
        edges.extend(lengths)
        if area <= 1e-13:
            degenerate += 1
            continue
        longest = max(lengths)
        aspects.append(longest * longest / (2.0 * area))
    aspects.sort()
    areas.sort()
    edges.sort()
    return {
        "n": len(areas),
        "p95": _pct(aspects, 0.95),
        "p99": _pct(aspects, 0.99),
        "max": aspects[-1] if aspects else 0.0,
        "min_area": areas[0] if areas else 0.0,
        "degenerate": degenerate,
        "edge_min": edges[0] if edges else 0.0,
        "edge_max": edges[-1] if edges else 0.0,
    }


def _fmt(label, stats, lines):
    lines.append(
        f"      {label:<11} n={stats['n']:<6} aspect p95={stats['p95']:.2f} "
        f"p99={stats['p99']:.2f} max={stats['max']:.2f} | "
        f"min_area={stats['min_area']:.3e} degen={stats['degenerate']} | "
        f"edge {stats['edge_min']*1000:.4f}-{stats['edge_max']*1000:.2f}mm"
    )


def _triangles(mesh):
    mesh.calc_loop_triangles()
    return [tuple(t.vertices) for t in mesh.loop_triangles]


def _offset(points, directions, distance):
    return [p + d * distance for p, d in zip(points, directions)]


def _repair_directions(points, normals, triangles, distance, budget=24):
    """Relax colliding offset directions; offset LENGTH never changes."""
    directions = [n.copy() for n in normals]
    adjacency = design_ops._vertex_adjacency(len(points), triangles)
    pairs = triangle_intersection_pairs(_offset(points, directions, distance), triangles)
    initial, touched, iterations = len(pairs), set(), 0
    while pairs and iterations < budget:
        targets = {
            i
            for f, s in pairs
            for t in (f, s)
            for i in triangles[t]
        }
        touched.update(targets)
        previous = [d.copy() for d in directions]
        for i in targets:
            average = sum(
                (previous[o] for o in adjacency[i]), previous[i].copy()
            )
            if average.length_squared <= 1e-20:
                continue
            candidate = previous[i].lerp(average.normalized(), 0.5)
            if candidate.length_squared <= 1e-20:
                continue
            directions[i] = design_ops._limit_direction_change(
                normals[i], candidate.normalized()
            )
        iterations += 1
        pairs = triangle_intersection_pairs(
            _offset(points, directions, distance), triangles
        )
    return directions, initial, len(pairs), touched, iterations


def _repair_positions(points, triangles, budget=24):
    """Order B: relax positions about the FAIRED surface, along local normals.

    The faired vertex already carries whatever offset length fairing produced;
    the direction it is nudged along is the local surface normal of the faired
    mesh, so its distance from the body is preserved rather than reset to the
    nominal clearance.
    """
    working = [p.copy() for p in points]
    adjacency = design_ops._vertex_adjacency(len(points), triangles)
    pairs = triangle_intersection_pairs(working, triangles)
    initial, touched, iterations = len(pairs), set(), 0
    while pairs and iterations < budget:
        targets = {i for f, s in pairs for t in (f, s) for i in triangles[t]}
        touched.update(targets)
        snapshot = [p.copy() for p in working]
        for i in targets:
            ring = adjacency[i]
            if not ring:
                continue
            average = sum(
                (snapshot[o] for o in ring), type(snapshot[i])()
            ) / len(ring)
            working[i] = snapshot[i].lerp(average, 0.5)
        iterations += 1
        pairs = triangle_intersection_pairs(working, triangles)
    return working, initial, len(pairs), touched, iterations


def _regions(triangles, touched):
    ring = {}
    for tri in triangles:
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            if a in touched and b in touched:
                ring.setdefault(a, set()).add(b)
                ring.setdefault(b, set()).add(a)
    seen, groups = set(), []
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
        groups.append(group)
    return groups


def _populations(triangles, touched):
    incident, inside, unaffected = set(), set(), set()
    for index, tri in enumerate(triangles):
        members = set(tri)
        if members & touched:
            incident.add(index)
            if members <= touched:
                inside.add(index)
        else:
            unaffected.add(index)
    return incident, inside, unaffected


def _digest(points):
    return hashlib.sha256(
        repr([tuple(round(c, 9) for c in p) for p in points]).encode()
    ).hexdigest()[:12]


def _fair(points, triangles, iterations, factor=0.12):
    """Stand-in for LaplacianSmooth, applied to a coordinate list."""
    adjacency = design_ops._vertex_adjacency(len(points), triangles)
    working = [p.copy() for p in points]
    for _step in range(iterations):
        snapshot = [p.copy() for p in working]
        for i in range(len(working)):
            ring = adjacency[i]
            if not ring:
                continue
            average = sum(
                (snapshot[o] for o in ring), type(snapshot[i])()
            ) / len(ring)
            working[i] = snapshot[i].lerp(average, factor)
    return working


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
        fairing = int(settings.corset_smooth)
        lines.append(f"fairing iterations={fairing}")
        mesh = scan.data
        base = [v.co.copy() for v in mesh.vertices]
        normals = [v.normal.copy().normalized() for v in mesh.vertices]
        triangles = _triangles(mesh)

        for offset_mm in OFFSETS:
            distance = offset_mm * 0.001
            lines.append("")
            lines.append(f"=== clearance {offset_mm:.2f}mm ===")

            naive = _offset(base, normals, distance)
            naive_pairs = triangle_intersection_pairs(naive, triangles)
            faired_only = _fair(naive, triangles, fairing)
            faired_pairs = triangle_intersection_pairs(faired_only, triangles)
            lines.append(
                f"  PRODUCTION TODAY: displace={len(naive_pairs)} selfX -> "
                f"after fairing={len(faired_pairs)} selfX"
            )

            # ---- ORDER A: displace -> repair -> fair
            directions, a_initial, a_left, a_touched, a_iter = _repair_directions(
                base, normals, triangles, distance
            )
            a_repaired = _offset(base, directions, distance)
            a_after_fair = _fair(a_repaired, triangles, fairing)
            a_final = triangle_intersection_pairs(a_after_fair, triangles)
            lines.append(
                f"  ORDER A displace->repair->fair: {a_initial} -> {a_left} "
                f"after repair ({a_iter} passes, {len(a_touched)} verts) -> "
                f"{len(a_final)} AFTER FAIRING"
                + ("  <-- fairing REOPENED a fold" if len(a_final) > a_left else "")
            )

            # ---- ORDER B: displace -> fair -> repair
            b_points, b_initial, b_left, b_touched, b_iter = _repair_positions(
                faired_only, triangles
            )
            lines.append(
                f"  ORDER B displace->fair->repair: {b_initial} -> {b_left} "
                f"({b_iter} passes, {len(b_touched)} verts)"
            )

            for label, points, touched, reference in (
                ("A", a_after_fair, a_touched, a_repaired),
                ("B", b_points, b_touched, faired_only),
            ):
                if not touched:
                    lines.append(f"    order {label}: NO-OP")
                    continue
                incident, inside, unaffected = _populations(triangles, touched)
                groups = _regions(triangles, touched)
                moved = [(points[i] - reference[i]).length for i in range(len(points))]
                outside_max = max(
                    (moved[i] for i in range(len(moved)) if i not in touched),
                    default=0.0,
                )
                delivered = [
                    (points[i] - base[i]).dot(normals[i]) for i in touched
                ]
                lines.append(
                    f"    order {label}: {len(touched)} verts in {len(groups)} "
                    f"region(s); moved max={max(moved)*1000:.4f}mm; outside "
                    f"regions max={outside_max*1000:.2e}mm"
                )
                lines.append(
                    f"      clearance in repaired verts: "
                    f"min={min(delivered)*1000:.4f} max={max(delivered)*1000:.4f}mm "
                    f"(requested {offset_mm:.2f}) inward_loss="
                    f"{max(0.0, distance-min(delivered))*1000:.4f}mm outward_float="
                    f"{max(0.0, max(delivered)-distance)*1000:.4f}mm"
                )
                _fmt("BEFORE full", _quality(reference, triangles), lines)
                _fmt("AFTER  full", _quality(points, triangles), lines)
                _fmt("BEFORE incid", _quality(reference, triangles, incident), lines)
                _fmt("AFTER  incid", _quality(points, triangles, incident), lines)
                if inside:
                    _fmt("BEFORE region", _quality(reference, triangles, inside), lines)
                    _fmt("AFTER  region", _quality(points, triangles, inside), lines)
                _fmt("unaffected", _quality(points, triangles, unaffected), lines)
                lines.append(f"      hash={_digest(points)}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
