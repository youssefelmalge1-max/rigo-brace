"""Extract measurable trimline data from the internal base4 reference.

The script reads only the exterior-material surface. It finds the largest connected
exterior face island (the shell, excluding straps/hardware), then reports its boundary
loops. No reference vertices are imported into production add-on code.
"""

import json
import math
import os

import bmesh
import bpy
from mathutils import Vector


ROOT = r"C:\Projects\Blender Add-on Braces"
SOURCE = os.path.join(
    ROOT, "reference_assets", "spinaltech_trimlines", "spinaltech_base4.glb"
)
OUT = os.path.join(ROOT, "referenceprofile_result.json")
INCH_TO_METRE = 0.0254


def _face_components(faces):
    remaining = set(faces)
    components = []
    while remaining:
        component = set()
        stack = [remaining.pop()]
        while stack:
            face = stack.pop()
            component.add(face)
            for edge in face.edges:
                for linked in edge.link_faces:
                    if linked in remaining:
                        remaining.remove(linked)
                        stack.append(linked)
        components.append(component)
    return components


def _edge_components(edges):
    by_vertex = {}
    for edge in edges:
        for vertex in edge.verts:
            by_vertex.setdefault(vertex, set()).add(edge)
    remaining = set(edges)
    components = []
    while remaining:
        component = set()
        stack = [remaining.pop()]
        while stack:
            edge = stack.pop()
            component.add(edge)
            for vertex in edge.verts:
                for linked in by_vertex[vertex]:
                    if linked in remaining:
                        remaining.remove(linked)
                        stack.append(linked)
        components.append((component, by_vertex))
    return components


def _ordered_vertices(edge_component, by_vertex):
    component_edges = set(edge_component)
    adjacency = {}
    for edge in component_edges:
        first, second = edge.verts
        adjacency.setdefault(first, []).append((second, edge))
        adjacency.setdefault(second, []).append((first, edge))
    degrees = sorted(len(neighbours) for neighbours in adjacency.values())
    if not degrees or degrees[0] != 2 or degrees[-1] != 2:
        return [], degrees
    start = min(adjacency, key=lambda vertex: vertex.index)
    ordered = [start]
    previous = None
    current = start
    for _index in range(len(component_edges) - 1):
        neighbours = adjacency[current]
        following = neighbours[0][0]
        if following == previous:
            following = neighbours[1][0]
        ordered.append(following)
        previous, current = current, following
    return ordered, degrees


def _length(points):
    return sum(
        (points[(index + 1) % len(points)] - point).length
        for index, point in enumerate(points)
    )


def _bounds(points):
    minimum = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
    maximum = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
    return minimum, maximum


def _largest_angular_gap(points, axis):
    angles = sorted(math.atan2(point.y - axis.y, point.x - axis.x) for point in points)
    wrapped = angles + [angles[0] + 2.0 * math.pi]
    gaps = [wrapped[index + 1] - wrapped[index] for index in range(len(angles))]
    index = max(range(len(gaps)), key=gaps.__getitem__)
    midpoint = wrapped[index] + 0.5 * gaps[index]
    return ((midpoint + math.pi) % (2.0 * math.pi)) - math.pi, gaps[index]


def _wrap_angle(angle):
    return ((angle + math.pi) % (2.0 * math.pi)) - math.pi


def _estimate_waist_z(points, minimum_z, maximum_z):
    """Return the narrowest well-populated transverse slice in the middle 50%."""
    bin_count = 60
    bins = [[] for _index in range(bin_count)]
    height = maximum_z - minimum_z
    for point in points:
        index = min(bin_count - 1, int((point.z - minimum_z) / height * bin_count))
        bins[index].append(point)
    candidates = []
    for index, slab in enumerate(bins):
        fraction = (index + 0.5) / bin_count
        if not 0.25 <= fraction <= 0.75 or len(slab) < 20:
            continue
        width = max(point.x for point in slab) - min(point.x for point in slab)
        depth = max(point.y for point in slab) - min(point.y for point in slab)
        candidates.append((width * depth, minimum_z + fraction * height))
    return min(candidates)[1]


def _angular_profiles(points, axis, opening_angle, waist_z, bottom_z, top_z):
    bin_count = 72
    bins = [[] for _index in range(bin_count)]
    for point in points:
        theta = _wrap_angle(math.atan2(point.y - axis.y, point.x - axis.x) - opening_angle)
        index = min(bin_count - 1, int((theta + math.pi) / (2.0 * math.pi) * bin_count))
        bins[index].append(point.z)

    def normalize(z):
        if z <= waist_z:
            return (z - waist_z) / (waist_z - bottom_z)
        return (z - waist_z) / (top_z - waist_z)

    top = []
    bottom = []
    counts = []
    for values in bins:
        counts.append(len(values))
        top.append(round(normalize(max(values)), 4) if values else None)
        bottom.append(round(normalize(min(values)), 4) if values else None)
    return top, bottom, counts


def main():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=SOURCE)
    obj = max(
        (item for item in bpy.context.scene.objects if item.type == "MESH"),
        key=lambda item: len(item.data.polygons),
    )
    material_names = [
        slot.material.name.lower() if slot.material else "" for slot in obj.material_slots
    ]
    outside_indices = {
        index for index, name in enumerate(material_names) if name.startswith("outside")
    }
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    exterior_faces = [face for face in bm.faces if face.material_index in outside_indices]
    components = _face_components(exterior_faces)
    components.sort(key=len, reverse=True)
    shell_faces = components[0]
    shell_vertices = {vertex for face in shell_faces for vertex in face.verts}
    boundary_edges = [
        edge
        for edge in {edge for face in shell_faces for edge in face.edges}
        if sum(linked in shell_faces for linked in edge.link_faces) == 1
    ]
    matrix = obj.matrix_world

    loop_reports = []
    ordered_loops = []
    for edge_component, by_vertex in _edge_components(boundary_edges):
        ordered, degrees = _ordered_vertices(edge_component, by_vertex)
        if not ordered:
            loop_reports.append({
                "edges": len(edge_component),
                "ordered": False,
                "degree_min": min(degrees) if degrees else 0,
                "degree_max": max(degrees) if degrees else 0,
            })
            continue
        points = [(matrix @ vertex.co) * INCH_TO_METRE for vertex in ordered]
        minimum, maximum = _bounds(points)
        report = {
            "vertices": len(points),
            "ordered": True,
            "length_mm": round(_length(points) * 1000.0, 3),
            "dimensions_mm": [round(value * 1000.0, 3) for value in maximum - minimum],
            "bounds_min_mm": [round(value * 1000.0, 3) for value in minimum],
            "bounds_max_mm": [round(value * 1000.0, 3) for value in maximum],
        }
        loop_reports.append(report)
        ordered_loops.append((report["length_mm"], points))
    loop_reports.sort(key=lambda item: item.get("length_mm", 0.0), reverse=True)
    ordered_loops.sort(key=lambda item: item[0], reverse=True)

    shell_points = [(matrix @ vertex.co) * INCH_TO_METRE for vertex in shell_vertices]
    shell_minimum, shell_maximum = _bounds(shell_points)
    axis = Vector((
        0.5 * (shell_minimum.x + shell_maximum.x),
        0.5 * (shell_minimum.y + shell_maximum.y),
        0.0,
    ))
    opening_angle, opening_gap = _largest_angular_gap(shell_points, axis)

    outer_points = ordered_loops[0][1]
    trim_minimum, trim_maximum = _bounds(outer_points)
    waist_z = _estimate_waist_z(
        shell_points, trim_minimum.z, trim_maximum.z
    )
    profile_top, profile_bottom, profile_counts = _angular_profiles(
        outer_points,
        axis,
        opening_angle,
        waist_z,
        trim_minimum.z,
        trim_maximum.z,
    )
    result = {
        "source": os.path.basename(SOURCE),
        "unit_assumption": "source coordinates are inches; multiplied by 0.0254",
        "materials": material_names,
        "outside_material_indices": sorted(outside_indices),
        "outside_faces": len(exterior_faces),
        "outside_face_components": [len(component) for component in components],
        "shell_faces": len(shell_faces),
        "shell_vertices": len(shell_vertices),
        "shell_dimensions_mm": [
            round(value * 1000.0, 3) for value in shell_maximum - shell_minimum
        ],
        "boundary_loops": loop_reports,
        "outer_perimeter": {
            "point_count": len(outer_points),
            "height_mm": round((trim_maximum.z - trim_minimum.z) * 1000.0, 3),
            "opening_angle_deg": round(math.degrees(opening_angle), 3),
            "largest_surface_angle_gap_deg": round(math.degrees(opening_gap), 3),
            "waist_z_mm": round(waist_z * 1000.0, 3),
            "bottom_to_waist_mm": round((waist_z - trim_minimum.z) * 1000.0, 3),
            "waist_to_top_mm": round((trim_maximum.z - waist_z) * 1000.0, 3),
            "theta_zero": "centre of the largest shell-surface angular gap (opening)",
            "profile_top_norm_72": profile_top,
            "profile_bottom_norm_72": profile_bottom,
            "profile_sample_counts_72": profile_counts,
        },
    }
    with open(OUT, "w", encoding="utf-8") as report_file:
        json.dump(result, report_file, indent=2)
    bm.free()


main()
