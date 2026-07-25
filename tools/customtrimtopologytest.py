"""Regression for the 2026-07-18 narrow painted-opening split."""

import math

import bpy

from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (
    _adjust_mask_values,
    _marching_mask_graph,
    _ordered_closed_loops,
    _topology_preserving_mask_loop,
)


OUT = r"C:\Projects\Blender Add-on Braces\customtrimtopologytest_result.txt"


def _loop_count(mesh, values):
    coordinates, adjacency = _marching_mask_graph(mesh, values)
    return len(_ordered_closed_loops(coordinates, adjacency))


def _cylinder_mask(gap_half_width):
    sides = 64
    rings = 40
    vertices = []
    faces = []
    for ring in range(rings):
        z = -0.20 + 0.40 * ring / (rings - 1)
        for side in range(sides):
            angle = math.tau * side / sides
            vertices.append((0.15 * math.cos(angle), 0.15 * math.sin(angle), z))
    for ring in range(rings - 1):
        for side in range(sides):
            following = (side + 1) % sides
            lower = ring * sides
            upper = (ring + 1) * sides
            faces.append((lower + side, lower + following, upper + following))
            faces.append((lower + side, upper + following, upper + side))
    mesh = bpy.data.meshes.new("Topology Safe Mask Fixture")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    values = []
    for ring in range(rings):
        for side in range(sides):
            wrapped_side = min(side, sides - side)
            in_band = 7 <= ring <= 32
            local_half_width = 0 if ring in {19, 20} else gap_half_width
            in_opening = wrapped_side <= local_half_width
            values.append(float(in_band and not in_opening))
    return mesh, values


def _run():
    lines = []
    passed = False
    try:
        fixture = None
        scenarios = []
        for gap_half_width in range(1, 9):
            mesh, values = _cylinder_mask(gap_half_width)
            raw_count = _loop_count(mesh, values)
            requested = 8
            smoothed = _adjust_mask_values(mesh, values, "SMOOTH", requested)
            requested_count = _loop_count(mesh, smoothed)
            scenarios.append((gap_half_width, raw_count, requested_count))
            if raw_count == 1 and requested_count != 1:
                loop, safe_steps = _topology_preserving_mask_loop(
                    mesh,
                    values,
                    requested,
                )
                fixture = (
                    gap_half_width,
                    raw_count,
                    requested_count,
                    safe_steps,
                    len(loop),
                )
                passed = 0 <= safe_steps < requested and len(loop) >= 3
                bpy.data.meshes.remove(mesh)
                break
            bpy.data.meshes.remove(mesh)
        lines.append(f"fixture={fixture}")
        lines.append(f"scenarios={scenarios}")
        lines.append(f"PASS={passed}")
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
