"""Inspect the internal SpinalTech GLB fixtures without modifying their geometry.

Run with Blender in background mode. The report is deterministic JSON so later
generator tests can consume the same measurements.
"""

import json
import os

import bmesh
import bpy
from mathutils import Vector


ROOT = r"C:\Projects\Blender Add-on Braces"
ASSET_DIR = os.path.join(ROOT, "reference_assets", "spinaltech_trimlines")
OUT = os.path.join(ROOT, "referenceaudit_result.json")


def _clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _mesh_report(obj):
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    pending = set(bm.faces)
    components = 0
    while pending:
        components += 1
        stack = [pending.pop()]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for linked in edge.link_faces:
                    if linked in pending:
                        pending.remove(linked)
                        stack.append(linked)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
    bm.free()

    world_points = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    minimum = Vector((
        min(point.x for point in world_points),
        min(point.y for point in world_points),
        min(point.z for point in world_points),
    ))
    maximum = Vector((
        max(point.x for point in world_points),
        max(point.y for point in world_points),
        max(point.z for point in world_points),
    ))
    dimensions = (maximum - minimum) * 1000.0
    return {
        "name": obj.name,
        "mesh": mesh.name,
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "polygons": len(mesh.polygons),
        "components": components,
        "boundary_edges": boundary,
        "non_manifold_edges": non_manifold,
        "dimensions_mm": [round(value, 3) for value in dimensions],
        "bounds_min_m": [round(value, 6) for value in minimum],
        "bounds_max_m": [round(value, 6) for value in maximum],
        "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
    }


def _audit(path):
    _clear_scene()
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    reports = [_mesh_report(obj) for obj in meshes if len(obj.data.vertices)]
    reports.sort(key=lambda item: item["polygons"], reverse=True)
    return {
        "file": os.path.basename(path),
        "object_count": len(bpy.context.scene.objects),
        "mesh_count": len(reports),
        "meshes": reports,
    }


def main():
    result = {
        "units": "GLB metres; dimensions reported in millimetres",
        "fixtures": [],
    }
    for index in range(1, 5):
        result["fixtures"].append(
            _audit(os.path.join(ASSET_DIR, f"spinaltech_base{index}.glb"))
        )
    with open(OUT, "w", encoding="utf-8") as report_file:
        json.dump(result, report_file, indent=2)


main()
