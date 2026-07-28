"""#46 LOCAL: why does arc (17,21) overlap when (24,30) does not?

The aggregate rim metrics do NOT discriminate - both sit at the same saturated
ceiling with near-identical spacing and curvature statistics (rimmargindbg).
So this localises the failure instead: it captures the exact intersecting
triangle pairs and reports what is locally true at each, plus the same
measurements at the corresponding place in the passing case.

Provenance uses the paired-shell layout already established in
tools/rimoverlapdbg.py:

    index <  vertex_count          -> inner wall (patient contact)
    vertex_count <= index < 2*vc   -> outer wall (offset by thickness)
    index >= 2*vertex_count        -> rim fillet profile point

Usage: blender --python rimlocaldbg.py -- <a17|a24|none> <label>
"""

import math
import sys
import traceback

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\rimlocaldbg"
ARCS = {"a17": (17, 21), "a24": (24, 30), "none": None}
TRIES = {"n": 0}
LINES = []
STATE = {}

_original_pairs = design_ops.triangle_intersection_pairs
_original_shell = curve_build_ops._build_strict_shell


def _shell_spy(corset, settings):
    result = _original_shell(corset, settings)
    STATE["vertex_count"] = int(corset.get("rigo_paired_source_vertices", 0))
    return result


def _pairs_spy(vertices, triangles, bvh=None):
    """Keep the LAST call, not the first.

    `_build_strict_shell` runs its own intersection-based repair (see the
    `rigo_outer_collision_*` properties), so the first non-empty result is a
    TRANSIENT set that the repair then clears - capturing it made the passing
    case look worse than the failing one (3 pairs vs 1) while validation said
    the opposite. The final call is the one `_validate_finished_rim` makes, and
    that is the set that decides the build.
    """
    pairs = (
        _original_pairs(vertices, triangles, bvh=bvh)
        if bvh is not None
        else _original_pairs(vertices, triangles)
    )
    STATE.setdefault("call_counts", []).append(len(pairs))
    STATE["offenders"] = list(pairs)
    STATE["triangles"] = [tuple(t) for t in triangles]
    STATE["verts"] = [Vector(v) for v in vertices]
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


def _menger_mm(a, b, c):
    ab, bc, ca = (b - a).length, (c - b).length, (a - c).length
    if min(ab, bc, ca) <= 1.0e-12:
        return math.inf
    s = (ab + bc + ca) * 0.5
    area_sq = s * (s - ab) * (s - bc) * (s - ca)
    if area_sq <= 1.0e-20:
        return math.inf
    return (ab * bc * ca) / (4.0 * math.sqrt(area_sq)) * 1000.0


def _ordered_boundary(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    edges = [e for e in bm.edges if len(e.link_faces) == 1]
    if not edges:
        bm.free()
        return []
    adjacency = {}
    for edge in edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex.index, []).append(edge)
    start = edges[0].verts[0]
    loop, previous, current = [start], None, start
    while True:
        nxt = None
        for edge in adjacency.get(current.index, ()):
            other = edge.other_vert(current)
            if previous is None or other.index != previous.index:
                nxt = other
                break
        if nxt is None or nxt.index == start.index:
            break
        loop.append(nxt)
        previous, current = current, nxt
        if len(loop) > 30000:
            break
    points = [obj.matrix_world @ v.co.copy() for v in loop]
    bm.free()
    return points


def _station(boundary, point):
    if not boundary:
        return None
    count = len(boundary)
    index = min(range(count), key=lambda i: (boundary[i] - point).length)
    before, here, after = (
        boundary[(index - 1) % count], boundary[index],
        boundary[(index + 1) % count],
    )
    spacing = 0.5 * (
        (here - before).length + (after - here).length
    ) * 1000.0
    incoming, outgoing = here - before, after - here
    angle = (
        math.degrees(incoming.angle(outgoing))
        if incoming.length > 1e-12 and outgoing.length > 1e-12 else 0.0
    )
    return {
        "index": index,
        "count": count,
        "distance_mm": (here - point).length * 1000.0,
        "spacing_mm": spacing,
        "turn_radius_mm": _menger_mm(before, here, after),
        "turn_angle_deg": angle,
        "ceiling_mm": curve_build_ops._RIM_SPACING_RADIUS_CEILING * spacing,
    }


def _boundary_profile(boundary, label):
    """Spacing / turn statistics for the whole loop, for the passing case."""
    count = len(boundary)
    spacings, radii, angles = [], [], []
    for index in range(count):
        before, here, after = (
            boundary[(index - 1) % count], boundary[index],
            boundary[(index + 1) % count],
        )
        spacings.append((after - here).length * 1000.0)
        radii.append(_menger_mm(before, here, after))
        incoming, outgoing = here - before, after - here
        if incoming.length > 1e-12 and outgoing.length > 1e-12:
            angles.append(math.degrees(incoming.angle(outgoing)))
    finite = sorted(r for r in radii if math.isfinite(r))
    ordered_angles = sorted(angles)
    LINES.append(
        f"  {label}: n={count} "
        f"turn_radius min={finite[0]:.3f} p01={finite[len(finite)//100]:.3f}mm; "
        f"turn_angle p99={ordered_angles[int(0.99*(len(ordered_angles)-1))]:.2f} "
        f"max={ordered_angles[-1]:.2f}deg; "
        f"stations with turn_radius < ceiling="
        f"{sum(1 for i, r in enumerate(radii) if r < curve_build_ops._RIM_SPACING_RADIUS_CEILING * spacings[i])}"
    )
    return radii, spacings, angles


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    key = sys.argv[-2] if len(sys.argv) >= 2 else "a17"
    label = sys.argv[-1]
    arc = ARCS.get(key)
    base = corset = None
    stage = "setup"
    try:
        design_ops.triangle_intersection_pairs = _pairs_spy
        curve_build_ops._build_strict_shell = _shell_spy
        prepare_reference_design()
        settings = bpy.context.scene.rigo_brace
        bpy.ops.rigo.auto_trimline()
        curve = bpy.data.objects["Rigo Trim Perimeter"]
        if arc is not None:
            for index, point in enumerate(curve.data.splines[0].bezier_points):
                point.select_control_point = arc[0] <= index <= arc[1]
            bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode="SMOOTH_ARC")
        LINES.append(
            f"CASE {key} arc={arc} [{label}]  fillet requested="
            f"{settings.trim_fillet_radius:.2f}mm segments="
            f"{settings.trim_fillet_segments} thickness="
            f"{settings.corset_thickness:.2f}mm offset="
            f"{settings.corset_offset:.2f}mm"
        )
        LINES.append(
            f"  Candidate A in build: "
            f"{hasattr(design_ops, 'InnerSurfaceFoldError')}"
        )

        scan = settings.scan_object
        stage = "offset mold"
        base = design_ops._prepare_candidate_base(bpy.context, scan, settings)
        corset = curve_build_ops._new_brace_candidate(bpy.context, base)
        stage = "projection"
        projected = curve_build_ops._projected_perimeter(corset, curve)
        stage = "cut"
        retained = curve_build_ops._retained_region(settings, curve, projected)
        curve_build_ops._cut_surface(
            bpy.context, corset, projected, retained, settings
        )
        boundary = _ordered_boundary(corset)
        LINES.append(f"  STAGE cut: OK, cut-boundary loop n={len(boundary)}")
        _boundary_profile(boundary, "cut boundary")

        stage = "shell"
        curve_build_ops._build_strict_shell(corset, settings)
        vertex_count = STATE.get("vertex_count", 0)
        LINES.append(f"  STAGE shell: built, paired_source_vertices={vertex_count}")

        stage = "validate"
        verdict = "OK"
        try:
            design_ops._validate_finished_rim(corset)
        except Exception as error:  # noqa: BLE001
            verdict = str(error).strip().splitlines()[0][:110]
        LINES.append(f"  STAGE validate: {verdict}")
        LINES.append(
            f"  FIRST CLEAN-TO-INVALID STAGE: "
            f"{'validate (shell built, then rejected)' if verdict != 'OK' else 'none'}"
        )

        offenders = STATE.get("offenders") or []
        LINES.append(
            f"  triangle_intersection_pairs called {len(STATE.get('call_counts', []))}"
            f" times, pair counts per call: {STATE.get('call_counts')}"
        )
        LINES.append(
            f"  FINAL (validation) intersecting triangle pairs: {len(offenders)}"
        )
        if offenders:
            triangles, verts = STATE["triangles"], STATE["verts"]
            tally = {}
            for first, second in offenders:
                pair_class = " vs ".join(sorted((
                    _classify(triangles[first], vertex_count),
                    _classify(triangles[second], vertex_count),
                )))
                tally[pair_class] = tally.get(pair_class, 0) + 1
            LINES.append("  offending pair classes:")
            for name, count in sorted(tally.items(), key=lambda kv: -kv[1]):
                LINES.append(f"      {name:34s} {count}")
            for order, (first, second) in enumerate(offenders[:8]):
                tri_a, tri_b = triangles[first], triangles[second]
                centre_a = sum((verts[i] for i in tri_a), Vector()) / 3.0
                centre_b = sum((verts[i] for i in tri_b), Vector()) / 3.0
                normal_a = (verts[tri_a[1]] - verts[tri_a[0]]).cross(
                    verts[tri_a[2]] - verts[tri_a[0]])
                normal_b = (verts[tri_b[1]] - verts[tri_b[0]]).cross(
                    verts[tri_b[2]] - verts[tri_b[0]])
                angle = (
                    math.degrees(normal_a.angle(normal_b))
                    if normal_a.length > 1e-16 and normal_b.length > 1e-16
                    else 0.0
                )
                world_a = corset.matrix_world @ centre_a
                station = _station(boundary, world_a)
                LINES.append("")
                LINES.append(f"  OVERLAP {order + 1}: tri{first} x tri{second}")
                LINES.append(
                    f"      A {_classify(tri_a, vertex_count):16s} verts={tri_a} "
                    f"centroid=({world_a.x:.5f},{world_a.y:.5f},{world_a.z:.5f})"
                )
                LINES.append(
                    f"      B {_classify(tri_b, vertex_count):16s} verts={tri_b}"
                )
                LINES.append(
                    f"      face-normal angle={angle:.2f}deg  centroid gap="
                    f"{(centre_a - centre_b).length * 1000.0:.4f}mm"
                )
                if station:
                    LINES.append(
                        f"      nearest cut-boundary station {station['index']}"
                        f"/{station['count']} at {station['distance_mm']:.3f}mm: "
                        f"spacing={station['spacing_mm']:.3f}mm "
                        f"turn_radius={station['turn_radius_mm']:.3f}mm "
                        f"turn_angle={station['turn_angle_deg']:.2f}deg "
                        f"rim_ceiling={station['ceiling_mm']:.3f}mm"
                    )
    except Exception as error:  # noqa: BLE001
        LINES.append(f"  RAISED at stage {stage!r}: {str(error)[:130]}")
        LINES.append(traceback.format_exc())
    finally:
        design_ops.triangle_intersection_pairs = _original_pairs
        curve_build_ops._build_strict_shell = _original_shell
        for obj in (corset, base):
            if obj is not None and design_ops._object_is_registered(obj):
                design_ops._remove_object_and_orphan_mesh(obj)
    with open(f"{OUT}_{label}_{key}.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
