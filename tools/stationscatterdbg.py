"""Is the template trimline's waviness in the STATIONS or in the interpolation?

Measurement only. P2 made the interpolation curvature-continuous (junction
ratio 9.70 -> 1.01), so if the line still reads as wavy the input must be at
fault: each template station is placed by a radial raycast onto the raw scan,
so it lands on whatever local detail that ray meets.

The decisive test is WAVELENGTH. If the oscillation's arc-length period is
close to the station spacing, the stations are the source. If it is far
shorter, the source is scan faceting instead, and no amount of station fairing
would help.

Separates three things that all look like "waviness":
  intentional shape   the template's own clinical profile
  anatomy             large-scale body curvature the line must follow
  scatter             station displacement from an arc-length-faired path

Also reports whether scatter correlates with local scan curvature and with
local triangle size, and compares protected (opening) stations against the
free arcs between them.

Writes stationscatterdbg_result.txt; quits Blender itself.
"""

import math
import sys
import traceback

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    trimline_ops,
)
from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (  # noqa: E402
    _smooth_closed_parametric,
)

OUT = r"C:\Projects\Blender Add-on Braces\stationscatterdbg_result.txt"
TRIES = {"n": 0}


def _pct(values, fraction):
    return sorted(values)[int(fraction * (len(values) - 1))] if values else 0.0


def _spacing(points):
    count = len(points)
    return [
        (points[(i + 1) % count] - points[i]).length for i in range(count)
    ]


def _turns(points):
    count = len(points)
    out = []
    for i in range(count):
        entering = points[i] - points[i - 1]
        leaving = points[(i + 1) % count] - points[i]
        if min(entering.length, leaving.length) > 1e-12:
            out.append(math.degrees(entering.angle(leaving)))
        else:
            out.append(0.0)
    return out


def _resample(points, count):
    """Uniform arc-length resample of a closed polyline."""
    total = _spacing(points)
    cumulative = [0.0]
    for length in total:
        cumulative.append(cumulative[-1] + length)
    span = cumulative[-1]
    out = []
    segment = 0
    for index in range(count):
        target = span * index / count
        while segment + 1 < len(cumulative) and cumulative[segment + 1] < target:
            segment += 1
        length = cumulative[segment + 1] - cumulative[segment]
        fraction = (target - cumulative[segment]) / max(length, 1e-12)
        following = (segment + 1) % len(points)
        out.append(points[segment].lerp(points[following], fraction))
    return out


def _lateral_residual(points, sigma_m, scan, bvh):
    """Signed sideways offset of each sample from its own faired path.

    Signed along the surface binormal (tangent x normal), so sign alternation
    means genuine side-to-side oscillation rather than a smooth drift.
    """
    count = len(points)
    spacing = sum(_spacing(points)) / count
    faired = _smooth_closed_parametric(points, sigma_m, spacing)
    inverse = scan.matrix_world.inverted()
    normal_matrix = inverse.transposed().to_3x3()
    residual = []
    for index in range(count):
        tangent = faired[(index + 1) % count] - faired[index - 1]
        if tangent.length <= 1e-12:
            residual.append(0.0)
            continue
        tangent.normalize()
        hit = bvh.find_nearest(inverse @ faired[index])
        if hit[0] is None:
            residual.append(0.0)
            continue
        normal = (normal_matrix @ hit[1]).normalized()
        binormal = tangent.cross(normal)
        delta = points[index] - faired[index]
        if binormal.length <= 1e-12:
            residual.append(delta.length)
            continue
        residual.append(delta.dot(binormal.normalized()))
    return residual, faired


def _zero_crossing_wavelength(residual, points):
    """Mean arc length between sign changes, doubled = wavelength."""
    count = len(residual)
    lengths = _spacing(points)
    crossings = []
    walked = 0.0
    for index in range(count):
        walked += lengths[index]
        if residual[index] * residual[(index + 1) % count] < 0.0:
            crossings.append(walked)
            walked = 0.0
    if len(crossings) < 2:
        return 0.0, 0
    return 2.0 * sum(crossings) / len(crossings), len(crossings)


def _local_scan_metrics(scan, bvh, point):
    """(discrete mean curvature 1/m, local triangle edge length m)."""
    inverse = scan.matrix_world.inverted()
    hit = bvh.find_nearest(inverse @ point)
    if hit[0] is None:
        return 0.0, 0.0
    polygon = scan.data.polygons[hit[2]]
    verts = [scan.data.vertices[i] for i in polygon.vertices]
    edge = sum(
        (verts[i].co - verts[(i + 1) % len(verts)].co).length
        for i in range(len(verts))
    ) / len(verts)
    centre = sum((v.co for v in verts), Vector()) / len(verts)
    curvature = 0.0
    for vertex in verts:
        delta = vertex.co - centre
        if delta.length > 1e-9:
            curvature += delta.normalized().dot(vertex.normal)
    return curvature / len(verts) / max(edge, 1e-9), edge


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
        perimeter = bpy.data.objects["Rigo Trim Perimeter"]
        matrix = perimeter.matrix_world
        points = perimeter.data.splines[0].bezier_points
        stations = [matrix @ p.co for p in points]
        count = len(stations)

        protected = trimline_ops._opening_locked_indices(perimeter, stations)
        lines.append("=== 1. RAW STATIONS ===")
        spacing = _spacing(stations)
        turns = _turns(stations)
        total = sum(spacing)
        lines.append(
            f"  n={count} perimeter={total*1000:.0f}mm | spacing mm "
            f"min={min(spacing)*1000:.1f} p50={_pct(spacing,0.5)*1000:.1f} "
            f"max={max(spacing)*1000:.1f} (ratio {max(spacing)/min(spacing):.1f}x)"
        )
        lines.append(
            f"  control-polygon turn deg p50={_pct(turns,0.5):.1f} "
            f"p95={_pct(turns,0.95):.1f} max={max(turns):.1f}"
        )
        lines.append(
            f"  protected (opening) stations: {sorted(protected)}"
        )
        lines.append("")

        lines.append("=== 2. STATION SCATTER vs arc-length-faired station path ===")
        lines.append("  (sigma sweep; scatter = signed sideways offset)")
        for sigma_mm in (20.0, 40.0, 80.0):
            residual, _faired = _lateral_residual(
                stations, sigma_mm * 0.001, scan, bvh
            )
            magnitude = [abs(v) for v in residual]
            flips = sum(
                1 for i in range(count) if residual[i] * residual[i - 1] < 0.0
            )
            wavelength, crossings = _zero_crossing_wavelength(residual, stations)
            free = [abs(residual[i]) for i in range(count) if i not in protected]
            pinned = [abs(residual[i]) for i in range(count) if i in protected]
            lines.append(
                f"  sigma={sigma_mm:4.0f}mm: scatter mm p50={_pct(magnitude,0.5)*1000:.2f} "
                f"p95={_pct(magnitude,0.95)*1000:.2f} max={max(magnitude)*1000:.2f} "
                f"| sign flips={flips} ({100.0*flips/count:.0f}%) "
                f"| wavelength={wavelength*1000:.0f}mm ({crossings} crossings)"
            )
            lines.append(
                f"      at protected stations p95={_pct(pinned,0.95)*1000:.2f}mm "
                f"| between them p95={_pct(free,0.95)*1000:.2f}mm"
            )
        lines.append("")

        lines.append("=== 3. EVALUATED CURVE (what the user actually sees) ===")
        dense = curve_build_ops._curve_world_samples(perimeter)
        dense_turns = _turns(dense)
        lines.append(
            f"  n={len(dense)} turn deg p50={_pct(dense_turns,0.5):.3f} "
            f"p95={_pct(dense_turns,0.95):.3f} max={max(dense_turns):.2f}"
        )
        for sigma_mm in (10.0, 20.0, 40.0):
            residual, _f = _lateral_residual(dense, sigma_mm * 0.001, scan, bvh)
            magnitude = [abs(v) for v in residual]
            flips = sum(
                1
                for i in range(len(dense))
                if residual[i] * residual[i - 1] < 0.0
            )
            wavelength, crossings = _zero_crossing_wavelength(residual, dense)
            lines.append(
                f"  sigma={sigma_mm:4.0f}mm: residual mm p50={_pct(magnitude,0.5)*1000:.3f} "
                f"p95={_pct(magnitude,0.95)*1000:.3f} max={max(magnitude)*1000:.3f} "
                f"| flips={flips} ({100.0*flips/len(dense):.0f}%) "
                f"| wavelength={wavelength*1000:.0f}mm"
            )
        lines.append("")
        lines.append(
            "  DECISIVE: if the evaluated wavelength is close to the station "
            f"spacing (p50 {_pct(spacing,0.5)*1000:.0f}mm) the STATIONS are the "
            "source; if far shorter, scan faceting is."
        )
        lines.append("")

        lines.append("=== 4. CORRELATION with local scan geometry ===")
        residual, _f = _lateral_residual(stations, 0.040, scan, bvh)
        curvatures, edges = [], []
        for station in stations:
            curvature, edge = _local_scan_metrics(scan, bvh, station)
            curvatures.append(curvature)
            edges.append(edge)

        def _corr(first, second):
            n = len(first)
            mean_a = sum(first) / n
            mean_b = sum(second) / n
            num = sum(
                (first[i] - mean_a) * (second[i] - mean_b) for i in range(n)
            )
            den = math.sqrt(
                sum((first[i] - mean_a) ** 2 for i in range(n))
                * sum((second[i] - mean_b) ** 2 for i in range(n))
            )
            return num / den if den > 1e-12 else 0.0

        magnitude = [abs(v) for v in residual]
        lines.append(
            f"  |scatter| vs |local scan curvature| : r={_corr(magnitude, [abs(c) for c in curvatures]):+.3f}"
        )
        lines.append(
            f"  |scatter| vs local triangle edge    : r={_corr(magnitude, edges):+.3f}"
        )
        lines.append(
            f"  local scan edge length mm: p50={_pct(edges,0.5)*1000:.2f} "
            f"max={max(edges)*1000:.2f}"
        )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
