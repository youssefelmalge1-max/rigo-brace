"""Why does a denser trimline make the rim fillet self-intersect?

`_safe_rim_radii` clamps the rim bulge only by the distance to the boundary
NEIGHBOURS. Hypothesis: the binding constraint at a concave turn is the local
TURN RADIUS of the boundary, not neighbour spacing - where the boundary curves
tighter than the bulge, adjacent rim profiles converge and cross.

Captures, at a raised control density, every boundary vertex's assigned rim
radius against its local turn radius, and reports whether the offenders are
exactly the vertices where turn radius < assigned radius.
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

OUT = r"C:\Projects\Blender Add-on Braces\rimdensitydbg_result.txt"
TRIES = {"count": 0}
CAPTURE = {}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


_original_profiles = curve_build_ops._rim_profiles


def _instrumented(coordinates, topology, radius):
    profiles, radii = _original_profiles(coordinates, topology, radius)
    if "radii" not in CAPTURE:
        CAPTURE["radii"] = dict(radii)
        CAPTURE["boundary"] = tuple(topology.boundary)
        CAPTURE["coords"] = [c.copy() for c in coordinates[: topology.vertex_count]]
        CAPTURE["requested"] = radius
    return profiles, radii


def _turn_radius(previous, current, following):
    """Circumradius of the three consecutive boundary points."""
    a = (current - previous).length
    b = (following - current).length
    c = (following - previous).length
    if min(a, b, c) <= 1e-12:
        return math.inf
    s = (a + b + c) * 0.5
    area_sq = max(s * (s - a) * (s - b) * (s - c), 0.0)
    if area_sq <= 1e-24:
        return math.inf
    return (a * b * c) / (4.0 * math.sqrt(area_sq))


def _ordered_rings(boundary):
    neighbours = {}
    for first, second in boundary:
        neighbours.setdefault(first, []).append(second)
        neighbours.setdefault(second, []).append(first)
    rings = []
    seen = set()
    for start in neighbours:
        if start in seen or len(neighbours[start]) != 2:
            continue
        ring = [start]
        seen.add(start)
        previous, current = None, start
        while True:
            nxt = [n for n in neighbours[current] if n != previous]
            if not nxt:
                break
            step = nxt[0]
            if step == start:
                break
            if step in seen:
                break
            ring.append(step)
            seen.add(step)
            previous, current = current, step
        if len(ring) > 3:
            rings.append(ring)
    return rings


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "generate_curve_corset") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        curve_build_ops._rim_profiles = _instrumented
        # Raise the density ceiling for this diagnostic only. It is read inside
        # `_resample_closed` at call time and only affects the PAINTED path, so
        # the trimline below must come from paint, not from the template.
        custom_trim_ops._MAX_CUSTOM_CONTROLS = int(
            __import__("os").environ.get("RIGO_DBG_CONTROLS", "240")
        )

        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8

        # Paint a front-covering band, exactly as customtrimseamtest does.
        template = design_ops._trim_perimeter_uv(bpy.context)
        _poly, axis_x, axis_y, front_x, front_y = template
        heights = [(scan.matrix_world @ v.co).z for v in scan.data.vertices]
        low, high = min(heights), max(heights)
        z_low = low + 0.30 * (high - low)
        z_high = low + 0.70 * (high - low)
        attribute = custom_trim_ops._ensure_mask(scan)
        for vertex, entry in zip(scan.data.vertices, attribute.data):
            world = scan.matrix_world @ vertex.co
            angle = design_ops._theta_of(
                world.x, world.y, axis_x, axis_y, front_x, front_y
            )
            inside = abs(angle) <= math.radians(150.0) and z_low <= world.z <= z_high
            entry.color = (0.0, 1.0, 0.0, 1.0) if inside else (1.0, 1.0, 1.0, 1.0)
        scan.data.update()

        settings.trim_source_mode = "CUSTOM_PAINT"
        bpy.ops.rigo.clear_trimlines()
        settings.trim_custom_spacing = 6.0
        settings.trim_smooth_mm = 8.0
        bpy.ops.rigo.custom_trim_from_paint()
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        controls = len(perimeter.data.splines[0].bezier_points)
        lines.append(
            f"cap={custom_trim_ops._MAX_CUSTOM_CONTROLS} controls={controls}"
        )

        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result = {"CANCELLED"}
            error = str(exc).strip()
        lines.append(f"generate={result} error={error!r}")

        if "radii" not in CAPTURE:
            lines.append("NO CAPTURE - _rim_profiles never ran")
            _write(lines)
            bpy.ops.wm.quit_blender()
            return None

        coords = CAPTURE["coords"]
        radii = CAPTURE["radii"]
        rings = _ordered_rings(CAPTURE["boundary"])
        lines.append(
            f"requested_radius_mm={CAPTURE['requested'] * 1000:.4f} "
            f"boundary_vertices={len(radii)} rings={len(rings)} "
            f"ring_sizes={[len(r) for r in rings][:5]}"
        )

        rows = []
        for ring in rings:
            n = len(ring)
            for i, index in enumerate(ring):
                previous = coords[ring[(i - 1) % n]]
                current = coords[index]
                following = coords[ring[(i + 1) % n]]
                turn = _turn_radius(previous, current, following)
                assigned = radii.get(index, 0.0)
                rows.append((turn, assigned, index))

        rows.sort(key=lambda r: r[0])
        violating = [r for r in rows if r[0] < r[1]]
        spacing = []
        for ring in rings:
            n = len(ring)
            for i, index in enumerate(ring):
                spacing.append(
                    (coords[index] - coords[ring[(i + 1) % n]]).length
                )
        spacing.sort()

        lines.append(
            f"control_spacing_mm: min={spacing[0] * 1000:.4f} "
            f"median={spacing[len(spacing) // 2] * 1000:.4f} "
            f"max={spacing[-1] * 1000:.4f}"
        )
        lines.append(
            f"turn_radius_mm: min={rows[0][0] * 1000:.4f} "
            f"p05={rows[len(rows) // 20][0] * 1000:.4f} "
            f"median={rows[len(rows) // 2][0] * 1000:.4f}"
        )
        lines.append(
            f"assigned_radius_mm: min={min(r[1] for r in rows) * 1000:.4f} "
            f"max={max(r[1] for r in rows) * 1000:.4f}"
        )
        lines.append(
            f"vertices_with_turn_radius_BELOW_assigned={len(violating)} "
            f"({100.0 * len(violating) / max(1, len(rows)):.2f}%)"
        )
        lines.append("tightest 10 (turn_mm, assigned_mm, ratio):")
        for turn, assigned, index in rows[:10]:
            ratio = turn / assigned if assigned > 0 else math.inf
            lines.append(
                f"  turn={turn * 1000:9.4f}  assigned={assigned * 1000:7.4f}  "
                f"ratio={ratio:8.2f}  vert={index}"
            )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
