"""Painted manufacturing lattices for ventilation and reinforcement."""

import math
from dataclasses import dataclass

import bmesh
import bpy
from bpy.types import Operator
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..core import CORSET_NAME, brace_ready_for_finishing, invalidate_brace_qa
from .design_ops import _apply, _mesh_volume, _restore_slot_cut_mesh
from .vent_ops import _band_weight_lookup

_CUTTER_NAME = "Rigo Lattice Tool"
_MAX_CELLS = 250


@dataclass(frozen=True)
class _PaintedRegion:
    face_indices: set
    coordinates: list
    center: Vector
    normal: Vector
    tangent_u: Vector
    tangent_v: Vector


class LatticeBuildError(RuntimeError):
    """The selected region cannot produce a valid manufacturing lattice."""


def _brace():
    candidate = bpy.data.objects.get(CORSET_NAME)
    return candidate if candidate is not None and candidate.type == "MESH" else None


def _tangent_basis(normal):
    tangent_u = normal.cross(Vector((0.0, 0.0, 1.0)))
    if tangent_u.length_squared < 1.0e-12:
        tangent_u = normal.cross(Vector((0.0, 1.0, 0.0)))
    tangent_u.normalize()
    return tangent_u, normal.cross(tangent_u).normalized()


def _painted_region(brace):
    bm = bmesh.from_edit_mesh(brace.data)
    bm.faces.ensure_lookup_table()
    selected_faces = [face for face in bm.faces if face.select]
    selected_vertices = [vertex.co.copy() for vertex in bm.verts if vertex.select]
    if not selected_faces or not selected_vertices:
        raise LatticeBuildError("Paint the lattice area on the brace first")
    normal = sum((face.normal for face in selected_faces), Vector())
    if normal.length_squared < 1.0e-12:
        raise LatticeBuildError("Could not determine the painted area's direction")
    normal.normalize()
    tangent_u, tangent_v = _tangent_basis(normal)
    return _PaintedRegion(
        {face.index for face in selected_faces},
        selected_vertices,
        sum(selected_vertices, Vector()) / len(selected_vertices),
        normal,
        tangent_u,
        tangent_v,
    )


def _grid_bounds(region):
    coordinates_u = [(point - region.center).dot(region.tangent_u) for point in region.coordinates]
    coordinates_v = [(point - region.center).dot(region.tangent_v) for point in region.coordinates]
    return min(coordinates_u), max(coordinates_u), min(coordinates_v), max(coordinates_v)


def _safe_face(brace, face_index, trim_weights):
    if face_index is None:
        return False
    return not any(trim_weights.get(index, 0.0) > 0.0 for index in brace.data.polygons[face_index].vertices)


def _cell_hits(brace, region, pitch):
    minimum_u, maximum_u, minimum_v, maximum_v = _grid_bounds(region)
    start_u = minimum_u + pitch * 0.5
    start_v = minimum_v + pitch * 0.5
    count_u = max(0, int(math.floor((maximum_u - start_u) / pitch)) + 1)
    count_v = max(0, int(math.floor((maximum_v - start_v) / pitch)) + 1)
    if count_u * count_v > 20000:
        raise LatticeBuildError("Painted area is too large for this cell size")
    surface_bmesh = bmesh.new()
    surface_bmesh.from_mesh(brace.data)
    surface_bmesh.faces.ensure_lookup_table()
    bvh = BVHTree.FromBMesh(surface_bmesh)
    trim_weights = _band_weight_lookup(brace)
    hits = []
    try:
        for row in range(count_v):
            offset = pitch * 0.5 if row % 2 else 0.0
            for column in range(count_u):
                u = start_u + column * pitch + offset
                v = start_v + row * pitch
                if u > maximum_u - pitch * 0.5:
                    continue
                origin = region.center + region.tangent_u * u + region.tangent_v * v + region.normal * 0.25
                location, normal, face_index, _distance = bvh.ray_cast(origin, -region.normal, 0.5)
                if location is None or face_index not in region.face_indices:
                    continue
                if not _safe_face(brace, face_index, trim_weights):
                    continue
                hits.append((location, normal))
                if len(hits) > _MAX_CELLS:
                    raise LatticeBuildError(f"More than {_MAX_CELLS} cells; increase Cell Size")
    finally:
        surface_bmesh.free()
    if not hits:
        raise LatticeBuildError("No lattice cell landed inside the painted safe area")
    return hits


def _unit_outline(pattern):
    if pattern == "SQUARE":
        return [Vector((-1.0, -1.0)), Vector((1.0, -1.0)), Vector((1.0, 1.0)), Vector((-1.0, 1.0))]
    if pattern == "HEX":
        return [Vector((math.cos(math.tau * index / 6), math.sin(math.tau * index / 6))) for index in range(6)]
    return [Vector((0.0, -1.0)), Vector((1.0, 0.0)), Vector((0.0, 1.0)), Vector((-1.0, 0.0))]


def _surface_frame(reference_u, normal):
    tangent_u = reference_u - normal * reference_u.dot(normal)
    if tangent_u.length_squared < 1.0e-12:
        tangent_u, _unused = _tangent_basis(normal)
    tangent_u.normalize()
    return tangent_u, normal.cross(tangent_u).normalized()


def _append_solid(mesh, center, normal, tangent_u, outline, lower, upper):
    tangent_u, tangent_v = _surface_frame(tangent_u, normal)
    count = len(outline)
    bottom = [mesh.verts.new(center + tangent_u * point.x + tangent_v * point.y + normal * lower) for point in outline]
    top = [mesh.verts.new(center + tangent_u * point.x + tangent_v * point.y + normal * upper) for point in outline]
    mesh.faces.new(tuple(reversed(bottom)))
    mesh.faces.new(tuple(top))
    for index in range(count):
        following = (index + 1) % count
        mesh.faces.new((bottom[index], bottom[following], top[following], top[index]))


def _append_ring(mesh, center, normal, tangent_u, outer, inner, lower, upper):
    tangent_u, tangent_v = _surface_frame(tangent_u, normal)
    count = len(outer)
    loops = []
    for height, outline in ((lower, outer), (upper, outer), (lower, inner), (upper, inner)):
        loops.append([mesh.verts.new(center + tangent_u * point.x + tangent_v * point.y + normal * height) for point in outline])
    outer_bottom, outer_top, inner_bottom, inner_top = loops
    for index in range(count):
        following = (index + 1) % count
        mesh.faces.new((outer_bottom[index], outer_bottom[following], outer_top[following], outer_top[index]))
        mesh.faces.new((inner_bottom[following], inner_bottom[index], inner_top[index], inner_top[following]))
        mesh.faces.new((outer_top[index], outer_top[following], inner_top[following], inner_top[index]))
        mesh.faces.new((outer_bottom[following], outer_bottom[index], inner_bottom[index], inner_bottom[following]))


def _scaled_outline(pattern, radius):
    return [point * radius for point in _unit_outline(pattern)]


def _lattice_mesh(settings, hits, reference_u):
    lattice_bmesh = bmesh.new()
    cell_radius = settings.lattice_cell_size * 0.0005
    bar_m = settings.lattice_bar_width * 0.001
    for center, normal in hits:
        if settings.lattice_finish_mode == "CUT":
            _append_solid(lattice_bmesh, center, normal, reference_u, _scaled_outline(settings.lattice_pattern, cell_radius), -0.03, 0.03)
            continue
        outer_radius = cell_radius + bar_m * 0.5 + 0.0001
        inner_radius = max(cell_radius - bar_m * 0.5, cell_radius * 0.2)
        _append_ring(
            lattice_bmesh,
            center,
            normal,
            reference_u,
            _scaled_outline(settings.lattice_pattern, outer_radius),
            _scaled_outline(settings.lattice_pattern, inner_radius),
            -0.0005,
            settings.lattice_height * 0.001,
        )
    mesh = bpy.data.meshes.new(_CUTTER_NAME)
    lattice_bmesh.to_mesh(mesh)
    lattice_bmesh.free()
    mesh.update()
    return mesh


def _topology_errors(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        return sum(edge.is_boundary for edge in bm.edges), sum(not edge.is_manifold for edge in bm.edges)
    finally:
        bm.free()


def _apply_lattice_boolean(context, brace, tool, mode):
    if mode == "ADD":
        remesh = tool.modifiers.new(name="Lattice Tool Remesh", type="REMESH")
        remesh.mode = "VOXEL"
        remesh.voxel_size = 0.00045
        remesh.adaptivity = 0.0
        remesh.use_remove_disconnected = False
        _apply(context, tool, remesh.name)
    modifier = brace.modifiers.new(name="Manufacturing Lattice", type="BOOLEAN")
    modifier.operation = "DIFFERENCE" if mode == "CUT" else "UNION"
    modifier.solver = "EXACT"
    modifier.object = tool
    _apply(context, brace, modifier.name)


class RIGO_OT_lattice_paint(Operator):
    """Paint the brace region that will receive a manufacturing lattice."""

    bl_idname = "rigo.lattice_paint"
    bl_label = "Paint Lattice Area"

    @classmethod
    def poll(cls, context):
        return brace_ready_for_finishing(context)

    def execute(self, context):
        brace = _brace()
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        brace.hide_set(False)
        brace.select_set(True)
        context.view_layer.objects.active = brace
        return bpy.ops.rigo.paint_select()


class RIGO_OT_build_lattice(Operator):
    """Cut or add the selected measured lattice pattern."""

    bl_idname = "rigo.build_lattice_pattern"
    bl_label = "Build Lattice"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return brace_ready_for_finishing(context)

    def execute(self, context):
        brace = _brace()
        settings = context.scene.rigo_brace
        if context.mode != "EDIT_MESH" or context.active_object is not brace:
            self.report({"ERROR"}, "Paint the lattice area on the brace first")
            return {"CANCELLED"}
        try:
            region = _painted_region(brace)
            pitch = (settings.lattice_cell_size + settings.lattice_bar_width) * 0.001
            hits = _cell_hits(brace, region, pitch)
        except LatticeBuildError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        bpy.ops.object.mode_set(mode="OBJECT")
        return self._build(context, brace, settings, region, hits)

    def _build(self, context, brace, settings, region, hits):
        original_mesh = brace.data.copy()
        initial_volume = _mesh_volume(brace.data)
        tool_mesh = _lattice_mesh(settings, hits, region.tangent_u)
        tool = bpy.data.objects.new(_CUTTER_NAME, tool_mesh)
        tool.matrix_world = brace.matrix_world.copy()
        context.scene.collection.objects.link(tool)
        try:
            _apply_lattice_boolean(context, brace, tool, settings.lattice_finish_mode)
            self._validate_result(brace, settings.lattice_finish_mode, initial_volume)
        except (RuntimeError, LatticeBuildError) as error:
            _restore_slot_cut_mesh(brace, original_mesh)
            self.report({"ERROR"}, f"Lattice cancelled; previous brace kept ({error})")
            return {"CANCELLED"}
        finally:
            if bpy.data.objects.get(tool.name) is not None:
                bpy.data.objects.remove(tool, do_unlink=True)
            if tool_mesh.users == 0:
                bpy.data.meshes.remove(tool_mesh)
        if original_mesh.users == 0:
            bpy.data.meshes.remove(original_mesh)
        brace["rigo_lattice_cells"] = len(hits)
        brace["rigo_lattice_pattern"] = settings.lattice_pattern
        brace["rigo_lattice_mode"] = settings.lattice_finish_mode
        invalidate_brace_qa(brace, "Manufacturing lattice changed")
        action = "Cut" if settings.lattice_finish_mode == "CUT" else "Added"
        self.report({"INFO"}, f"{action} {len(hits)} {settings.lattice_pattern.lower()} lattice cells")
        return {"FINISHED"}

    @staticmethod
    def _validate_result(brace, mode, initial_volume):
        final_volume = _mesh_volume(brace.data)
        changed = final_volume < initial_volume if mode == "CUT" else final_volume > initial_volume
        if not changed or abs(final_volume - initial_volume) <= max(1.0e-12, initial_volume * 1.0e-8):
            raise LatticeBuildError("the lattice did not intersect the brace")
        boundary, nonmanifold = _topology_errors(brace.data)
        if boundary or nonmanifold:
            raise LatticeBuildError(f"result has {boundary} open and {nonmanifold} non-manifold edges")


_CLASSES = (RIGO_OT_lattice_paint, RIGO_OT_build_lattice)


def register():
    for operator_class in _CLASSES:
        bpy.utils.register_class(operator_class)


def unregister():
    for operator_class in reversed(_CLASSES):
        bpy.utils.unregister_class(operator_class)
