"""Is the 0.35 x spacing rim-radius ceiling unnecessarily limiting?

Sweeps the spacing factor upward on the reference AND the hostile hairpin
fixture, and reports for each value what the safety and quality gates would
see. Nothing in production changes: the factor is patched per run.

The delivered radius today is ~0.349 mm against a 1.0 mm request, because
`_safe_rim_radii` clamps to 0.35 x boundary spacing. That term bounds a
bulge that runs PERPENDICULAR to the boundary by a distance measured ALONG
it, which is not a geometric argument; adjacent-profile overlap is governed
by curvature, which the separate 0.5 x turn-radius clamp already handles.
This measures whether that is true in practice before anything is relaxed.
"""

import math
import os
import statistics
import sys
import traceback

import bmesh
import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import curve_build_ops  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\radiussweepdbg_result.txt"
TRIES = {"n": 0}
FACTORS = (0.35, 0.5, 0.75, 1.0, 1.5, 2.0)
HOSTILE = os.environ.get("RIGO_SWEEP_HOSTILE") == "1"
_original = curve_build_ops._safe_rim_radii


def _patched(factor):
    def _safe_rim_radii(coordinates, boundary, requested):
        linked = curve_build_ops._boundary_neighbours(boundary)
        ceilings = {}
        for index, neighbours in linked.items():
            spacing = min(
                (coordinates[index] - coordinates[neighbour]).length
                for neighbour in neighbours
            )
            ceilings[index] = min(requested, factor * spacing)
        ring = curve_build_ops._ordered_boundary_ring(boundary)
        if not ring:
            return ceilings
        for position, index in enumerate(ring):
            turn = curve_build_ops._local_turn_radius(
                coordinates, ring, position
            )
            if turn < math.inf:
                ceilings[index] = min(ceilings[index], 0.5 * turn)
        return ceilings

    return _safe_rim_radii


def _sharpen():
    perimeter = bpy.data.objects["Rigo Trim Perimeter"]
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    notch = count // 3
    for offset in (-1, 0, 1):
        point = points[(notch + offset) % count]
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    points[notch].co.z -= 0.015
    crowd = (2 * count) // 3
    anchor = points[crowd].co.copy()
    for offset in (1, 2):
        point = points[(crowd + offset) % count]
        direction = point.co - anchor
        if direction.length > 1e-9:
            point.co = anchor + direction.normalized() * (0.005 * offset)
        # Essential, and omitted in the first version of this fixture: the
        # generator leaves FREE handles sized for the ORIGINAL spacing, so
        # crowding the points to 5 mm without re-deriving them makes the
        # curve loop back through itself and branch the cut boundary. That
        # produced an identical non-manifold refusal at every factor and
        # every radius, which reads exactly like a real negative result.
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    perimeter.data.update_tag()


def _signature(brace):
    """Order-independent geometry checksum, for reproducibility only."""
    total = 0.0
    for vertex in brace.data.vertices:
        total += round(vertex.co.x, 9) + 2.0 * round(
            vertex.co.y, 9
        ) + 3.0 * round(vertex.co.z, 9)
    return len(brace.data.vertices), round(total, 6)


def _quality(brace):
    bm = bmesh.new()
    bm.from_mesh(brace.data)
    areas = [face.calc_area() for face in bm.faces]
    aspects = sorted(
        max(lengths) / min(lengths)
        for face in bm.faces
        for lengths in [[edge.calc_length() for edge in face.edges]]
        if min(lengths) > 1e-12
    )
    shortest = min(edge.calc_length() for edge in bm.edges)
    bm.free()
    return (
        aspects[int(0.99 * (len(aspects) - 1))],
        aspects[-1],
        min(areas),
        shortest,
        sum(1 for area in areas if area <= 1.0e-12),
    )


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = [f"fixture={'hostile' if HOSTILE else 'reference'}"]
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = float(
            os.environ.get("RIGO_SWEEP_THICKNESS", "4.0")
        )
        settings.corset_offset = 3.0
        lines.append(f"thickness_mm={settings.corset_thickness}")
        request = os.environ.get("RIGO_SWEEP_REQUEST")
        if request:
            settings.trim_fillet_radius = float(request)
        if HOSTILE:
            # Warm up once on the clean trimline first. Sharpening straight
            # after `prepare_reference_design` refused at EVERY factor with an
            # identical non-manifold error - a fixture artefact, not a radius
            # effect, and it would have been easy to misread as a result.
            bpy.ops.rigo.generate_curve_corset()
            _sharpen()
        lines.append(f"fillet_request_mm={settings.trim_fillet_radius}")
        for factor in FACTORS:
            curve_build_ops._safe_rim_radii = _patched(factor)
            try:
                result = bpy.ops.rigo.generate_curve_corset()
                error = ""
            except RuntimeError as exc:
                result, error = {"CANCELLED"}, str(exc).strip()
            if result != {"FINISHED"}:
                lines.append(f"factor={factor:<5} REFUSED {error[:110]}")
                continue
            brace = bpy.data.objects["Rigo Corset"]
            p99, worst, area, shortest, degenerate = _quality(brace)
            # Everything read from this object must be captured BEFORE the
            # next build: regenerating replaces it and invalidates the
            # pointer (the first run of this script died exactly there).
            summary = (
                f"factor={factor:<5} "
                f"radius_mm mean={brace.get('rigo_trim_fillet_mean_radius_mm', 0):.3f} "
                f"max={brace.get('rigo_trim_fillet_radius_mm', 0):.3f} "
                f"intersections={brace.get('rigo_generation_rim_intersections')} "
                f"aspect_p99={p99:.2f} aspect_max={worst:.1f} "
                f"min_area={area:.3e} min_edge_mm={shortest * 1000:.4f} "
                f"degenerate={degenerate} verts={len(brace.data.vertices)}"
            )
            first = _signature(brace)
            bpy.ops.rigo.generate_curve_corset()
            second = _signature(bpy.data.objects["Rigo Corset"])
            lines.append(f"{summary} deterministic={first == second}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    finally:
        curve_build_ops._safe_rim_radii = _original
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
