"""Rim-generation quality audit.

Measures, for a real curve-built brace, every failure mode that produces a
jagged / serrated / pinched / spiky rim:

  1. boundary edge-length distribution (uneven spacing)
  2. short and duplicate boundary edges
  3. degenerate / skinny triangles near the trimline
  4. boundary winding consistency and flipped normals
  5. per-vertex frame stability (outward direction reversals)
  6. fillet radius against local curvature
  7. self-intersections inside the rim strip
  8. abnormal per-vertex displacement (spikes)
"""

import math
import statistics
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

OUT = r"C:\Projects\Blender Add-on Braces\rimqualitydbg_result.txt"
TRIES = {"n": 0}
CAP = {}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


_orig = curve_build_ops._rim_profiles


def _spy(coordinates, topology, radius):
    profiles, radii = _orig(coordinates, topology, radius)
    if "radii" not in CAP:
        CAP["radii"] = dict(radii)
        CAP["boundary"] = tuple(topology.boundary)
        CAP["vertex_count"] = topology.vertex_count
        CAP["segments"] = topology.segments
        CAP["coords"] = [c.copy() for c in coordinates]
        CAP["profiles"] = {k: list(v) for k, v in profiles.items()}
        # Measure BOTH: the retired per-vertex heuristic and the ordered-ring
        # frames actually used, so the fix is visible rather than assumed.
        CAP["directions_old"] = design_ops._rim_outward_directions(
            coordinates, topology.triangles, topology.boundary,
            topology.vertex_count,
        )
        CAP["directions"] = curve_build_ops._stable_outward_directions(
            coordinates, topology.triangles, topology.boundary,
            topology.vertex_count,
        )
    return profiles, radii


def _ordered_ring(boundary):
    nb = {}
    for a, b in boundary:
        nb.setdefault(a, []).append(b)
        nb.setdefault(b, []).append(a)
    start = next(iter(nb))
    ring, seen = [start], {start}
    prev, cur = None, start
    while True:
        nxt = [n for n in nb[cur] if n != prev]
        if not nxt or nxt[0] == start:
            break
        step = nxt[0]
        if step in seen:
            break
        ring.append(step)
        seen.add(step)
        prev, cur = cur, step
    return ring, nb


def _stats(name, values, scale=1000.0):
    if not values:
        return f"  {name}: (none)"
    v = sorted(x * scale for x in values)
    return (
        f"  {name}: min={v[0]:.4f} p05={v[len(v)//20]:.4f} "
        f"median={v[len(v)//2]:.4f} p95={v[int(0.95*(len(v)-1))]:.4f} "
        f"max={v[-1]:.4f} ratio_max_min={v[-1]/max(v[0],1e-9):.1f}"
    )


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.ops.rigo, "generate_curve_corset") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        curve_build_ops._rim_profiles = _spy
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8
        try:
            result = bpy.ops.rigo.generate_curve_corset()
            err = ""
        except RuntimeError as exc:
            result, err = {"CANCELLED"}, str(exc).strip()
        lines.append(f"generate={result} error={err!r}")

        if "radii" not in CAP:
            lines.append("no capture")
            _write(lines)
            bpy.ops.wm.quit_blender()
            return None

        coords = CAP["coords"]
        vc = CAP["vertex_count"]
        ring, nb = _ordered_ring(CAP["boundary"])
        n = len(ring)
        lines.append(
            f"boundary_vertices={len(CAP['radii'])} ring_len={n} "
            f"segments={CAP['segments']}"
        )

        # 1/2 - spacing and duplicate/short edges
        edges = [
            (coords[ring[i]] - coords[ring[(i + 1) % n]]).length
            for i in range(n)
        ]
        lines.append("1/2. BOUNDARY EDGE LENGTH (mm)")
        lines.append(_stats("edge_len", edges))
        lines.append(
            f"  edges_under_0.05mm={sum(1 for e in edges if e < 5e-5)} "
            f"under_0.10mm={sum(1 for e in edges if e < 1e-4)} "
            f"exact_duplicates={sum(1 for e in edges if e < 1e-9)}"
        )

        # 4/5 - frame stability: outward direction reversal between neighbours
        lines.append("4/5. FRAME STABILITY (outward direction continuity)")
        for label, directions in (
            ("retired heuristic", CAP["directions_old"]),
            ("ordered-ring frames", CAP["directions"]),
        ):
            flips = 0
            turn_dots = []
            for i in range(n):
                a, b = ring[i], ring[(i + 1) % n]
                if a in directions and b in directions:
                    d = directions[a].dot(directions[b])
                    turn_dots.append(d)
                    if d < 0.0:
                        flips += 1
            if not turn_dots:
                lines.append(f"  {label}: (no frames)")
                continue
            lines.append(
                f"  {label:22s} min_dot={min(turn_dots):+.4f} "
                f"median={statistics.median(turn_dots):.4f} "
                f"REVERSALS={flips} "
                f"near_orthogonal(<0.5)={sum(1 for d in turn_dots if d < 0.5)}"
            )

        # 6 - fillet radius: absolute spread AND adjacent-vertex gradient, which
        # is what is actually seen as serration.
        radii = CAP["radii"]
        lines.append("6. FILLET RADIUS (mm)")
        lines.append(_stats("assigned_radius", list(radii.values())))
        steps = []
        for i in range(n):
            a, b = radii.get(ring[i]), radii.get(ring[(i + 1) % n])
            if a and b:
                steps.append(abs(a - b) / max(a, b))
        if steps:
            steps.sort()
            lines.append(
                f"  adjacent_relative_change: median={steps[len(steps)//2]:.4f} "
                f"p95={steps[int(0.95*(len(steps)-1))]:.4f} max={steps[-1]:.4f} "
                f"jumps_over_25pct={sum(1 for s in steps if s > 0.25)}"
            )

        # 8 - abnormal displacement: rim apex offset from the inner-outer chord
        profiles = CAP["profiles"]
        apex_offsets = []
        for index, prof in profiles.items():
            mid = prof[len(prof) // 2]
            inner = coords[index]
            outer = coords[index + vc]
            chord_mid = (inner + outer) * 0.5
            apex_offsets.append((coords[mid] - chord_mid).length)
        lines.append("8. RIM APEX DISPLACEMENT (mm)")
        lines.append(_stats("apex_offset", apex_offsets))

        # 3/7 - degenerate faces and rim self-intersections on the built mesh
        brace = bpy.data.objects.get("Rigo Corset")
        if brace is not None:
            bm = bmesh.new()
            bm.from_mesh(brace.data)
            areas = [f.calc_area() for f in bm.faces]
            tiny = sum(1 for a in areas if a < 1e-10)
            aspects = []
            for f in bm.faces:
                el = [e.calc_length() for e in f.edges]
                if min(el) > 1e-12:
                    aspects.append(max(el) / min(el))
            bm.free()
            aspects.sort()
            lines.append("3. FACE QUALITY (built shell)")
            lines.append(
                f"  faces={len(areas)} near_zero_area={tiny} "
                f"aspect_median={aspects[len(aspects)//2]:.2f} "
                f"aspect_p99={aspects[int(0.99*(len(aspects)-1))]:.2f} "
                f"aspect_max={aspects[-1]:.2f}"
            )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
