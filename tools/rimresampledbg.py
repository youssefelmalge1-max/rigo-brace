"""Classify the rim overlaps that appeared after boundary resampling.

The paired-shell coordinate layout tells us which wall each triangle
belongs to:

    index <  vertex_count            -> inner wall (patient contact)
    vertex_count <= index < 2*vc     -> outer wall (offset by thickness)
    index >= 2*vertex_count          -> rim fillet profile points
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

OUT = r"C:\Projects\Blender Add-on Braces\rimresampledbg_result.txt"
TRIES = {"count": 0}
STATE = {}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


_original_pairs = design_ops.triangle_intersection_pairs
_original_shell = curve_build_ops._build_strict_shell
_original_zero = design_ops._zero_area_triangle_count
_original_profiles = curve_build_ops._rim_profiles


def _profiles_spy(coordinates, topology, radius):
    ring_indices = []
    ring_verts = curve_build_ops._ordered_boundary_ring(topology.boundary)
    if ring_verts:
        ring_indices = list(ring_verts)
    STATE["ring"] = ring_indices
    return _original_profiles(coordinates, topology, radius)


def _zero_spy(coordinates, triangles):
    found = []
    for triangle in triangles:
        first, second, third = triangle
        cross = (coordinates[second] - coordinates[first]).cross(
            coordinates[third] - coordinates[first]
        )
        if 0.5 * cross.length <= 1.0e-12:
            found.append(
                (
                    tuple(triangle),
                    [tuple(coordinates[i]) for i in triangle],
                )
            )
    if found and "zero_faces" not in STATE:
        STATE["zero_faces"] = found[:8]
    return _original_zero(coordinates, triangles)


def _shell_spy(corset, settings):
    result = _original_shell(corset, settings)
    STATE["vertex_count"] = int(corset.get("rigo_paired_source_vertices", 0))
    return result


def _pairs_spy(vertices, triangles, bvh=None):
    pairs = _original_pairs(vertices, triangles, bvh=bvh) if bvh is not None \
        else _original_pairs(vertices, triangles)
    if pairs:
        # Keep the LAST non-empty capture: the resample's own repair loop also
        # calls this, and the interesting call is the final shell validation.
        STATE["nonempty_calls"] = STATE.get("nonempty_calls", 0) + 1
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
        design_ops._zero_area_triangle_count = _zero_spy
        curve_build_ops._rim_profiles = _profiles_spy

        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        # Radius/segments/offset stay at their DEFAULTS (radius 1.0 mm), the
        # exact configuration slotbracetest/referencetrimtest/thicknesstest
        # fail with, and which every earlier audit accidentally overrode.
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result = {"CANCELLED"}
            error = str(exc).strip()

        vertex_count = STATE.get("vertex_count", 0)
        lines.append(f"generate={result} error={error!r}")
        lines.append(
            f"paired_source_vertices={vertex_count} "
            f"nonempty_pair_calls={STATE.get('nonempty_calls', 0)}"
        )

        for triangle, points in STATE.get("zero_faces", []):
            edges = [
                math.dist(points[i], points[(i + 1) % 3]) * 1000.0
                for i in range(3)
            ]
            lines.append(
                f"ZERO-AREA tri idx={triangle} class="
                f"{_classify(triangle, vertex_count)} "
                f"edges_mm=({edges[0]:.5f},{edges[1]:.5f},{edges[2]:.5f}) "
                f"first_point=({points[0][0]:.4f},{points[0][1]:.4f},"
                f"{points[0][2]:.4f})"
            )

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
            ring = STATE.get("ring", [])
            ring_position = {index: pos for pos, index in enumerate(ring)}
            ring_count = max(1, len(ring))

            def _role(index):
                base = index % vertex_count if index < 2 * vertex_count else None
                if base is None:
                    return "rim"
                position = ring_position.get(base)
                wall = "i" if index < vertex_count else "o"
                if position is None:
                    return f"{wall}-int"
                return f"{wall}-B{position}"

            def _gaps(triangle):
                gaps = []
                for a in range(3):
                    first_i, second_i = triangle[a], triangle[(a + 1) % 3]
                    pa = ring_position.get(first_i % vertex_count)
                    pb = ring_position.get(second_i % vertex_count)
                    if (
                        pa is not None
                        and pb is not None
                        and first_i < 2 * vertex_count
                        and second_i < 2 * vertex_count
                    ):
                        gaps.append(
                            min(
                                (pa - pb) % ring_count,
                                (pb - pa) % ring_count,
                            )
                        )
                    else:
                        gaps.append(-1)
                return gaps

            for pair_index, (first, second) in enumerate(offenders[:10]):
                for label, tri in (("A", triangles[first]), ("B", triangles[second])):
                    pts = [verts[i] for i in tri]
                    edges = [
                        math.dist(pts[i], pts[(i + 1) % 3]) * 1000.0
                        for i in range(3)
                    ]
                    lines.append(
                        f"  pair{pair_index} {label}: idx={tri} class="
                        f"{_classify(tri, vertex_count)} "
                        f"roles=({','.join(_role(i) for i in tri)}) "
                        f"edge_gaps={_gaps(tri)} "
                        f"edges_mm=({edges[0]:.4f},{edges[1]:.4f},{edges[2]:.4f})"
                    )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
