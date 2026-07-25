"""Baseline audit: current generated A brace versus the clinic A reference STL."""

import collections
import math

import bmesh
import bpy
from mathutils import Vector, kdtree


_OUT = r"C:\Projects\Blender Add-on Braces\generatoraudit_result.txt"
_MODEL = r"C:\Projects\Blender Add-on Braces\A type model.stl"
_REFERENCE = r"C:\Projects\Blender Add-on Braces\A type Brace.stl"
_IMAGE = r"C:\Projects\Blender Add-on Braces\generatoraudit.png"
_TRIES = {"n": 0}


def _place(settings, ident, location):
    settings.active_landmark = ident
    bpy.context.scene.cursor.location = location
    bpy.ops.rigo.place_landmark()


def _automatic_landmarks(scan, settings):
    vertices = scan.data.vertices
    z_values = [vertex.co.z for vertex in vertices]
    z_min, z_max = min(z_values), max(z_values)
    slabs = collections.defaultdict(list)
    for vertex in vertices:
        slabs[round(vertex.co.z / 0.01)].append(vertex.co)
    waist_z, narrowest = None, float("inf")
    for key, coordinates in slabs.items():
        z = key * 0.01
        if z_min + 0.25 * (z_max - z_min) < z < z_min + 0.75 * (z_max - z_min):
            width = max(co.x for co in coordinates) - min(co.x for co in coordinates)
            if width < narrowest:
                narrowest, waist_z = width, z
    xs = [vertex.co.x for vertex in vertices]
    ys = [vertex.co.y for vertex in vertices]
    center_x = (min(xs) + max(xs)) * 0.5
    center_y = (min(ys) + max(ys)) * 0.5
    front_y = min(ys) + 0.25 * (max(ys) - min(ys))
    back_y = max(ys) - 0.25 * (max(ys) - min(ys))
    anchors = {
        "TROCHANTER_L": (center_x - 0.10, center_y, z_min + 0.02),
        "TROCHANTER_R": (center_x + 0.10, center_y, z_min + 0.02),
        "WAISTLINE": (center_x, center_y, waist_z),
        "ACROMION_L": (center_x - 0.08, center_y, z_max - 0.015),
        "ACROMION_R": (center_x + 0.08, center_y, z_max - 0.015),
        "ASIS_L": (center_x - 0.05, front_y, z_min + 0.06),
        "ASIS_R": (center_x + 0.05, front_y, z_min + 0.06),
        "PSIS_L": (center_x - 0.04, back_y, z_min + 0.08),
        "PSIS_R": (center_x + 0.04, back_y, z_min + 0.08),
    }
    for ident, location in anchors.items():
        _place(settings, ident, location)
    return waist_z


def _mesh_metrics(mesh_object, waist_z):
    mesh = mesh_object.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    edge_lengths = sorted(edge.calc_length() * 1000.0 for edge in bm.edges)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
    aspects = []
    for face in bm.faces:
        lengths = [edge.calc_length() for edge in face.edges]
        area = face.calc_area()
        if area > 1e-12:
            aspects.append(
                sum(length * length for length in lengths)
                / (4.0 * math.sqrt(3.0) * area)
            )
    aspects.sort()
    bm.free()

    bounds = [mesh_object.matrix_world @ Vector(corner) for corner in mesh_object.bound_box]
    center_x = (min(point.x for point in bounds) + max(point.x for point in bounds)) * 0.5
    center_y = (min(point.y for point in bounds) + max(point.y for point in bounds)) * 0.5
    angles = []
    for vertex in mesh.vertices:
        world = mesh_object.matrix_world @ vertex.co
        if abs(world.z - waist_z) <= 0.005:
            angles.append(math.atan2(world.x - center_x, center_y - world.y))
    angles.sort()
    gaps = [b - a for a, b in zip(angles, angles[1:])]
    if len(angles) > 1:
        gaps.append(angles[0] + 2.0 * math.pi - angles[-1])
    dimensions = tuple(round(axis * 1000.0, 2) for axis in mesh_object.dimensions)
    return {
        "verts": len(mesh.vertices),
        "faces": len(mesh.polygons),
        "dimensions_mm": dimensions,
        "boundary_edges": boundary,
        "non_manifold_edges": non_manifold,
        "edge_p95_mm": edge_lengths[int(0.95 * (len(edge_lengths) - 1))],
        "edge_max_mm": edge_lengths[-1],
        "aspect_p95": aspects[int(0.95 * (len(aspects) - 1))],
        "aspect_max": aspects[-1],
        "waist_max_gap_deg": math.degrees(max(gaps)) if gaps else 360.0,
    }


def _rms_to_reference(source, reference):
    tree = kdtree.KDTree(len(reference.data.vertices))
    for vertex in reference.data.vertices:
        tree.insert(reference.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    squared = []
    stride = max(1, len(source.data.vertices) // 20000)
    for vertex_index in range(0, len(source.data.vertices), stride):
        vertex = source.data.vertices[vertex_index]
        nearest, _index, _distance = tree.find(source.matrix_world @ vertex.co)
        squared.append((nearest - source.matrix_world @ vertex.co).length_squared)
    return math.sqrt(sum(squared) / len(squared)) * 1000.0


def _render_comparison(generated, reference):
    for scene_object in bpy.context.scene.objects:
        scene_object.hide_render = scene_object not in {generated, reference}
    for mesh_object, target_x, color in (
        (generated, -0.21, (0.85, 0.20, 0.12, 1.0)),
        (reference, 0.21, (0.12, 0.38, 0.85, 1.0)),
    ):
        bounds = [mesh_object.matrix_world @ Vector(corner) for corner in mesh_object.bound_box]
        center = sum(bounds, Vector()) / 8.0
        mesh_object.location += Vector((target_x - center.x, -center.y, 0.30 - center.z))
        mesh_object.color = color

    camera_data = bpy.data.cameras.new("Generator Audit Camera")
    camera = bpy.data.objects.new("Generator Audit Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = (0.0, -2.0, 0.30)
    camera.rotation_euler = Vector((0.0, 1.0, 0.0)).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 0.70
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "OBJECT"
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.filepath = _IMAGE
    bpy.ops.render.render(write_still=True)


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    lines = []
    try:
        bpy.ops.wm.stl_import(filepath=_MODEL)
        scan = bpy.context.object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        waist_z = _automatic_landmarks(scan, settings)
        settings.trim_type = "A"
        bpy.ops.rigo.auto_trimline()
        from bl_ext.user_default.rigo_brace.operators.design_ops import _trim_perimeter_uv

        perimeter_polygon = _trim_perimeter_uv(bpy.context)[0]
        waist_intersections = []
        previous = perimeter_polygon[-1]
        for current in perimeter_polygon:
            if (previous[1] > waist_z) != (current[1] > waist_z):
                fraction = (waist_z - previous[1]) / (current[1] - previous[1])
                angle = previous[0] + (current[0] - previous[0]) * fraction
                waist_intersections.append(math.degrees(angle))
            previous = current
        bpy.ops.rigo.generate_corset()
        generated = bpy.data.objects["Rigo Corset"]

        bpy.ops.wm.stl_import(filepath=_REFERENCE)
        reference = bpy.context.object
        reference.name = "Clinic A Reference"
        reference.scale *= 0.001
        bpy.context.view_layer.objects.active = reference
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        generated_metrics = _mesh_metrics(generated, waist_z)
        reference_metrics = _mesh_metrics(reference, waist_z)
        rms_mm = _rms_to_reference(generated, reference)
        _render_comparison(generated, reference)
        lines.extend(
            (
                f"generated={generated_metrics}",
                f"reference={reference_metrics}",
                f"generated_to_reference_rms_mm={rms_mm:.3f}",
                f"perimeter_waist_intersections_deg={waist_intersections}",
                "BASELINE_ONLY=True",
            )
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={exc!r}\n{traceback.format_exc()}")
    with open(_OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
