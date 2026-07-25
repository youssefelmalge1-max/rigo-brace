"""Regression for the 2026-07-18 custom-trim rim branch crash."""

import collections
import math

import bpy

from bl_ext.user_default.rigo_brace.operators.design_ops import (
    _boundary_edges,
    _clean_open_trim_surface,
)


OUT = r"C:\Projects\Blender Add-on Braces\rimbranchtest_result.txt"


def _boundary_degrees(mesh):
    mesh.calc_loop_triangles()
    triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    boundary = _boundary_edges(triangles)
    return collections.Counter(index for edge in boundary for index in edge)


def _pinched_surface():
    grid_size = 9
    vertices = [
        (column * 0.001, row * 0.001, 0.0)
        for row in range(grid_size)
        for column in range(grid_size)
    ]
    faces = []
    for row in range(grid_size - 1):
        for column in range(grid_size - 1):
            lower = row * grid_size + column
            upper = lower + grid_size
            faces.extend(
                (
                    (lower, lower + 1, upper + 1),
                    (lower, upper + 1, upper),
                )
            )
    center = (grid_size // 2) * grid_size + grid_size // 2
    incident = [face for face in faces if center in face]
    incident.sort(
        key=lambda face: math.atan2(
            sum(vertices[index][1] for index in face) / 3 - vertices[center][1],
            sum(vertices[index][0] for index in face) / 3 - vertices[center][0],
        )
    )
    retained_incident = set(incident[::2])
    faces = [
        face for face in faces if center not in face or face in retained_incident
    ]
    mesh = bpy.data.meshes.new("Pinched Trim Surface")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    corset = bpy.data.objects.new("Pinched Trim Corset", mesh)
    bpy.context.scene.collection.objects.link(corset)
    return corset, center


def _run():
    lines = []
    try:
        corset, branch_index = _pinched_surface()
        initial_degrees = _boundary_degrees(corset.data)
        _clean_open_trim_surface(corset)
        final_degrees = _boundary_degrees(corset.data)
        corset.data.calc_loop_triangles()
        passed = (
            initial_degrees[branch_index] == 6
            and all(degree == 2 for degree in final_degrees.values())
            and len(corset.data.loop_triangles) > 0
        )
        lines.append(f"initial_branch_degree={initial_degrees[branch_index]}")
        lines.append(
            f"final_invalid_degrees="
            f"{sorted(degree for degree in final_degrees.values() if degree != 2)}"
        )
        lines.append(f"final_triangles={len(corset.data.loop_triangles)}")
        lines.append(f"PASS={passed}")
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
