"""Editable, measured rivet-hole placement and transactional cutting."""

import bpy
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Vector

from ..core import CORSET_NAME, brace_ready_for_finishing, invalidate_brace_qa
from .design_ops import (
    SlotCutError,
    TrimRimQualityError,
    _apply,
    _capsule_prism_mesh,
    _mesh_volume,
    _remove_object_and_orphan_mesh,
    _remove_slot_slivers,
    _restore_slot_cut_mesh,
    _rounded_cut_edges,
    _surface_euler_characteristic,
    _validate_finished_rim,
    _vertical_surface_rotation,
)

_COLLECTION_NAME = "Rigo Rivet Holes"
_CUTTER_NAME = "Rigo Rivet Cutter"
_PREFIX = "RIVET_"


def _rivet_collection(context):
    collection = bpy.data.collections.get(_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(_COLLECTION_NAME)
        context.scene.collection.children.link(collection)
    return collection


def _new_rivet_marker(context, name, location, normal, diameter_mm):
    diameter_m = diameter_mm * 0.001
    mesh = _capsule_prism_mesh(f"{name} Preview", diameter_m, diameter_m, 0.0006)
    marker = bpy.data.objects.new(name, mesh)
    marker.location = location
    marker.rotation_mode = "QUATERNION"
    marker.rotation_quaternion = _vertical_surface_rotation(normal)
    marker["rigo_normal"] = tuple(normal.normalized())
    marker["rigo_w"] = diameter_mm
    marker["rigo_h"] = diameter_mm
    marker["rigo_rivet_diameter_mm"] = diameter_mm
    marker.display_type = "WIRE"
    marker.show_in_front = True
    _rivet_collection(context).objects.link(marker)
    bpy.ops.object.select_all(action="DESELECT")
    marker.select_set(True)
    context.view_layer.objects.active = marker
    context.view_layer.update()
    return marker


def _rivet_markers():
    return [obj for obj in bpy.data.objects if obj.name.startswith(_PREFIX)]


def _wall_thickness_m(context, brace):
    measured = brace.get("rigo_requested_thickness_mm")
    if measured is None:
        measured = context.scene.rigo_brace.corset_thickness
    return float(measured) * 0.001


def _rivet_cutter(context, brace, marker):
    diameter_m = float(marker.get("rigo_rivet_diameter_mm", 4.0)) * 0.001
    wall_m = _wall_thickness_m(context, brace)
    depth = max(0.012, wall_m * 2.0 + 0.004)
    mesh = _capsule_prism_mesh(_CUTTER_NAME, diameter_m, diameter_m, depth)
    cutter = bpy.data.objects.new(_CUTTER_NAME, mesh)
    context.scene.collection.objects.link(cutter)
    cutter.matrix_world = marker.matrix_world.copy()
    normal = Vector(marker["rigo_normal"]).normalized()
    cutter.location -= normal * wall_m
    return cutter


def _restore_failed_rivets(brace, original_mesh, message):
    _restore_slot_cut_mesh(brace, original_mesh)
    brace["rigo_rivet_status"] = f"FAILED: {message}"


class RIGO_OT_place_rivet(Operator):
    """Click the brace to place an editable circular rivet contour."""

    bl_idname = "rigo.place_rivet"
    bl_label = "Place Rivet Hole"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and brace_ready_for_finishing(context)

    def invoke(self, context, event):
        self._region = next(region for region in context.area.regions if region.type == "WINDOW")
        self._rv3d = context.area.spaces.active.region_3d
        context.window.cursor_modal_set("EYEDROPPER")
        context.workspace.status_text_set("Click brace to place rivet contour | Right-click / Esc finishes")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _surface_hit(self, context, event):
        coordinate = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
        if not (0 <= coordinate[0] <= self._region.width and 0 <= coordinate[1] <= self._region.height):
            return None, None
        direction = view3d_utils.region_2d_to_vector_3d(self._region, self._rv3d, coordinate)
        origin = view3d_utils.region_2d_to_origin_3d(self._region, self._rv3d, coordinate)
        brace = bpy.data.objects.get(CORSET_NAME)
        inverse = brace.matrix_world.inverted()
        local_origin = inverse @ origin
        local_direction = (inverse.to_3x3() @ direction).normalized()
        hit, location, normal, _face = brace.ray_cast(local_origin, local_direction)
        if not hit:
            return None, None
        world_location = brace.matrix_world @ location
        world_normal = (inverse.transposed().to_3x3() @ normal).normalized()
        return world_location, world_normal

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            context.window.cursor_modal_restore()
            context.workspace.status_text_set(None)
            return {"FINISHED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            location, normal = self._surface_hit(context, event)
            if location is None:
                self.report({"WARNING"}, "Click directly on the brace")
                return {"RUNNING_MODAL"}
            number = len(_rivet_markers())
            diameter = context.scene.rigo_brace.rivet_diameter
            _new_rivet_marker(context, f"{_PREFIX}{number}", location, normal, diameter)
            return {"RUNNING_MODAL"}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}


class RIGO_OT_cut_rivets(Operator):
    """Cut all placed rivet contours and round their entrance loops."""

    bl_idname = "rigo.cut_rivets"
    bl_label = "Cut Rivet Holes"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return brace_ready_for_finishing(context)

    def execute(self, context):
        brace = bpy.data.objects.get(CORSET_NAME)
        markers = _rivet_markers()
        if not markers:
            self.report({"WARNING"}, "Place at least one rivet contour first")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        context.view_layer.update()
        original_mesh = brace.data.copy()
        initial_volume = _mesh_volume(brace.data)
        initial_chi = _surface_euler_characteristic(brace.data)
        try:
            self._cut_markers(context, brace, markers)
            self._validate_cut(context, brace, markers, initial_volume, initial_chi)
        except (SlotCutError, TrimRimQualityError) as error:
            _restore_failed_rivets(brace, original_mesh, error)
            self.report({"ERROR"}, f"Rivet cut cancelled; previous brace kept ({error})")
            return {"CANCELLED"}
        if original_mesh.users == 0:
            bpy.data.meshes.remove(original_mesh)
        for marker in markers:
            _remove_object_and_orphan_mesh(marker)
        brace["rigo_rivet_count"] = len(markers)
        brace["rigo_rivet_status"] = f"CUT: {len(markers)} rounded rivet hole(s)"
        invalidate_brace_qa(brace, "Rivet holes changed")
        self.report({"INFO"}, brace["rigo_rivet_status"])
        return {"FINISHED"}

    @staticmethod
    def _cut_markers(context, brace, markers):
        for index, marker in enumerate(markers):
            cutter = _rivet_cutter(context, brace, marker)
            modifier = brace.modifiers.new(name=f"Rivet Hole {index + 1}", type="BOOLEAN")
            modifier.operation = "DIFFERENCE"
            modifier.solver = "EXACT"
            modifier.object = cutter
            try:
                _apply(context, brace, modifier.name)
            except RuntimeError as error:
                raise SlotCutError("Blender could not resolve the circular cut") from error
            finally:
                if bpy.data.objects.get(cutter.name) is not None:
                    _remove_object_and_orphan_mesh(cutter)

    @staticmethod
    def _validate_cut(context, brace, markers, initial_volume, initial_chi):
        if initial_volume - _mesh_volume(brace.data) <= max(1.0e-12, initial_volume * 1.0e-8):
            raise SlotCutError("the rivet contours do not intersect the brace")
        settings = context.scene.rigo_brace
        rounded, radius = _rounded_cut_edges(
            brace, markers, settings.rivet_edge_radius, settings.corset_thickness
        )
        if settings.rivet_edge_radius > 0.0 and rounded == 0:
            raise SlotCutError("the rivet rims could not be identified for rounding")
        _remove_slot_slivers(brace, markers)
        final_chi = _surface_euler_characteristic(brace.data)
        expected_chi = initial_chi - 2 * len(markers)
        if final_chi != expected_chi:
            measured = (initial_chi - final_chi) // 2
            raise SlotCutError(
                "each rivet contour must cross exactly one brace wall; "
                f"expected {len(markers)} opening(s), measured {measured} "
                f"(surface Euler {initial_chi}->{final_chi})"
            )
        _validate_finished_rim(brace)
        brace["rigo_rivet_fillet_radius_mm"] = radius
        brace["rigo_rivet_rounded_edges"] = rounded


class RIGO_OT_clear_rivets(Operator):
    """Remove uncut rivet contours."""

    bl_idname = "rigo.clear_rivets"
    bl_label = "Clear Rivet Holes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        markers = _rivet_markers()
        for marker in markers:
            _remove_object_and_orphan_mesh(marker)
        self.report({"INFO"}, f"Removed {len(markers)} rivet contour(s)")
        return {"FINISHED"}


_CLASSES = (RIGO_OT_place_rivet, RIGO_OT_cut_rivets, RIGO_OT_clear_rivets)


def register():
    for operator_class in _CLASSES:
        bpy.utils.register_class(operator_class)


def unregister():
    for operator_class in reversed(_CLASSES):
        bpy.utils.unregister_class(operator_class)
