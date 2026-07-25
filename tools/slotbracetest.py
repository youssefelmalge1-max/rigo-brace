"""Installed-copy curved-brace regression for rounded strap slots."""

import os
import sys

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402


OUT = r"C:\Projects\Blender Add-on Braces\slotbracetest_result.txt"


def _topology(obj):
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        used_edges = {edge for face in bm.faces for edge in face.edges}
        used_vertices = {vertex for face in bm.faces for vertex in face.verts}
        chi = len(used_vertices) - len(used_edges) + len(bm.faces)
        boundary = sum(edge.is_boundary for edge in bm.edges)
        nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
        volume = abs(bm.calc_volume(signed=True))
    finally:
        bm.free()
    return chi, boundary, nonmanifold, volume


def _component_labels(mesh):
    adjacency = [[] for _vertex in mesh.vertices]
    for edge in mesh.edges:
        first, second = edge.vertices
        adjacency[first].append(second)
        adjacency[second].append(first)
    labels = [-1] * len(mesh.vertices)
    sizes = []
    for seed in range(len(mesh.vertices)):
        if labels[seed] >= 0:
            continue
        label = len(sizes)
        stack = [seed]
        labels[seed] = label
        size = 0
        while stack:
            vertex = stack.pop()
            size += 1
            for neighbour in adjacency[vertex]:
                if labels[neighbour] < 0:
                    labels[neighbour] = label
                    stack.append(neighbour)
        sizes.append(size)
    return labels, sizes


def _run():
    lines = []
    try:
        from bl_ext.user_default.rigo_brace.operators.design_ops import (
            _SlotPlacement,
            _new_slot_marker,
        )
        from bl_ext.user_default.rigo_brace.operators.mesh_intersections import (
            triangle_intersection_pairs,
        )

        _scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        generated = bpy.ops.rigo.generate_curve_corset()
        brace = bpy.data.objects.get("Rigo Corset")
        if generated != {"FINISHED"} or brace is None:
            raise RuntimeError("reference brace generation failed")

        mesh = brace.data
        z_min = min(vertex.co.z for vertex in mesh.vertices)
        z_max = max(vertex.co.z for vertex in mesh.vertices)
        z_mid = (z_min + z_max) * 0.5
        component_labels, component_sizes = _component_labels(mesh)
        largest_component = max(
            range(len(component_sizes)), key=component_sizes.__getitem__
        )
        candidates = [
            polygon
            for polygon in mesh.polygons
            if abs(polygon.center.z - z_mid) < (z_max - z_min) * 0.12
            and polygon.normal.x > 0.55
            and all(
                component_labels[vertex] == largest_component
                for vertex in polygon.vertices
            )
        ]
        if not candidates:
            raise RuntimeError("no stable lateral surface found for the slot fixture")
        polygon = max(candidates, key=lambda item: item.center.x)
        location = brace.matrix_world @ polygon.center
        normal = (brace.matrix_world.to_3x3() @ polygon.normal).normalized()

        settings.slot_width = 30.0
        settings.slot_height = 10.0
        settings.slot_edge_radius = 0.6
        settings.symmetrical = False
        _new_slot_marker(
            bpy.context,
            _SlotPlacement(
                "SLOT_CURVED",
                location,
                normal,
                settings.slot_width,
                settings.slot_height,
            ),
        )
        side_marker = bpy.data.objects["SLOT_CURVED"]
        expected_vertical = Vector((0.0, 0.0, 1.0))
        expected_vertical -= normal * expected_vertical.dot(normal)
        expected_vertical.normalize()
        marker_vertical = side_marker.rotation_quaternion @ Vector((0.0, 1.0, 0.0))
        vertical_alignment = marker_vertical.dot(expected_vertical)
        topo0 = _topology(brace)
        result = bpy.ops.rigo.cut_slots()
        topo1 = _topology(brace)
        side_fillet_radius = float(brace.get("rigo_slot_fillet_radius_mm", 0.0))

        rim_group = brace.vertex_groups.get("RIGO_RIM_BOUNDARY")
        rim_vertices = []
        if rim_group is not None:
            rim_vertices = [
                vertex.co
                for vertex in brace.data.vertices
                if any(
                    membership.group == rim_group.index
                    and membership.weight > 0.5
                    for membership in vertex.groups
                )
            ]
        rim_tree = kdtree.KDTree(len(rim_vertices))
        for index, coordinate in enumerate(rim_vertices):
            rim_tree.insert(coordinate, index)
        rim_tree.balance()
        front_faces = [
            face
            for face in brace.data.polygons
            if face.normal.y < -0.65
            and abs(face.center.z - z_mid) < (z_max - z_min) * 0.12
            and face.center.x > 0.04
            and rim_vertices
            and rim_tree.find(face.center)[2] > 0.030
        ]
        if not front_faces:
            raise RuntimeError("no stable anterior surface found for the slot fixture")
        front_face = max(
            front_faces, key=lambda candidate: rim_tree.find(candidate.center)[2]
        )
        front_location = brace.matrix_world @ front_face.center
        front_normal = (
            brace.matrix_world.to_3x3() @ front_face.normal
        ).normalized()
        settings.slot_width = 40.0
        settings.slot_height = 12.0
        settings.slot_edge_radius = 0.8
        _new_slot_marker(
            bpy.context,
            _SlotPlacement(
                "SLOT_ANTERIOR",
                front_location,
                front_normal,
                settings.slot_width,
                settings.slot_height,
            ),
        )
        front_result = bpy.ops.rigo.cut_slots()
        topo2 = _topology(brace)

        mesh.calc_loop_triangles()
        coordinates = [vertex.co.copy() for vertex in mesh.vertices]
        triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
        intersections = len(triangle_intersection_pairs(coordinates, triangles))
        passed = (
            result == {"FINISHED"}
            and topo1[3] < topo0[3]
            and topo0[0] - topo1[0] == 2
            and topo0[1] == topo1[1] == 0
            and topo0[2] == topo1[2] == 0
            and intersections == 0
            and int(brace.get("rigo_slot_rounded_edges", 0)) >= 2
            and abs(side_fillet_radius - 0.6) < 1.0e-6
            and vertical_alignment > 0.999999
            and front_result == {"FINISHED"}
            and topo2[3] < topo1[3]
            and topo1[0] - topo2[0] == 2
            and topo1[1] == topo2[1] == 0
            and topo1[2] == topo2[2] == 0
            and abs(float(brace.get("rigo_slot_fillet_radius_mm", 0.0)) - 0.8)
            < 1.0e-6
        )
        lines.extend(
            (
                f"generated={generated} cut={result}",
                f"components_before={component_sizes}",
                f"location={tuple(round(value, 6) for value in location)}",
                f"normal={tuple(round(value, 6) for value in normal)}",
                f"vertical_alignment={vertical_alignment:.9f}",
                f"chi={topo0[0]}->{topo1[0]}",
                f"boundary={topo0[1]}->{topo1[1]}",
                f"nonmanifold={topo0[2]}->{topo1[2]}",
                f"volume={topo0[3]:.9f}->{topo1[3]:.9f}",
                f"rounded_edges={brace.get('rigo_slot_rounded_edges', 0)}",
                f"anterior_cut={front_result} "
                f"chi={topo1[0]}->{topo2[0]} "
                f"boundary={topo1[1]}->{topo2[1]} "
                f"nonmanifold={topo1[2]}->{topo2[2]}",
                f"self_intersections={intersections}",
                f"PASS={passed}",
            )
        )
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()


if bpy.app.background:
    _run()
else:
    bpy.app.timers.register(_run, first_interval=0.5)
