"""Scan preparation: unit scaling, realignment, and cleaning.

These cover the LeoSpinal "Scale", "Transform" and "Clean" groups using native
Blender operations so the raw scan is correctly sized, stood upright, centred,
and free of holes before landmarking and design.
"""

import bpy
from bpy.types import Operator

# Scale factor to turn the scan's stored units into scene units where the rest
# of the add-on treats 1 scene unit = 1 metre (sliders use mm * 0.001).
_UNIT_SCALE = {"mm": 0.001, "cm": 0.01, "m": 1.0}


def _active_mesh(context):
    """The mesh to operate on: the active object, else the registered scan."""
    obj = context.active_object
    if obj is None or obj.type != "MESH":
        scan = getattr(context.scene.rigo_brace, "scan_object", None)
        obj = scan if (scan is not None and scan.type == "MESH") else None
    if obj is None:
        return None
    context.view_layer.objects.active = obj
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def _frame_object(context, obj):
    """Zoom every 3D viewport onto the object so a rescale never leaves it
    off-screen (the camera does not follow scale changes by itself)."""
    try:
        obj.select_set(True)
        for area in context.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    with context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_selected()
                    break
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Scale
# --------------------------------------------------------------------------- #
class RIGO_OT_apply_units(Operator):
    """Rescale the scan from its real-world units into the working scale"""

    bl_idname = "rigo.apply_units"
    bl_label = "Apply Scan Units"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}
        units = context.scene.rigo_brace.scan_units
        factor = _UNIT_SCALE[units]

        if factor == 1.0:
            self.report({"INFO"}, "Scan is already in metres — nothing to rescale")
            return {"FINISHED"}

        # A real mm/cm scan measures hundreds of units before conversion. If the
        # model is already body-sized in metres, the units were applied before —
        # shrinking again would make it microscopic ("the model disappears").
        if max(obj.dimensions) < 3.0:
            self.report(
                {"WARNING"},
                "Units look applied already (model is body-sized) — not scaling again",
            )
            return {"CANCELLED"}

        obj.scale = [s * factor for s in obj.scale]
        context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        # Re-frame the view: the model just changed size by 100-1000x, so the
        # old zoom level would show it sub-pixel small.
        _frame_object(context, obj)

        self.report(
            {"INFO"},
            f"Scaled from {units} — model is now {obj.dimensions.z * 1000:.0f} mm tall",
        )
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Transform / realign
# --------------------------------------------------------------------------- #
class RIGO_OT_recenter_floor(Operator):
    """Centre the scan over the origin and drop it onto the ground plane"""

    bl_idname = "rigo.recenter_floor"
    bl_label = "Recenter & Drop to Floor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}
        context.view_layer.objects.active = obj
        # Origin to geometry centre, then move to world origin.
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
        obj.location = (0.0, 0.0, 0.0)
        # Lift so the lowest point sits on z = 0.
        zs = [(obj.matrix_world @ v.co).z for v in obj.data.vertices]
        if zs:
            obj.location.z -= min(zs)
        self.report({"INFO"}, "Recentred on the floor")
        return {"FINISHED"}


class RIGO_OT_realign_tool(Operator):
    """Turn on the Rotate tool so you can stand the scan upright"""

    bl_idname = "rigo.realign_tool"
    bl_label = "Rotate Tool"

    def execute(self, context):
        try:
            bpy.ops.wm.tool_set_by_id(name="builtin.rotate")
        except RuntimeError:
            self.report({"WARNING"}, "Run this from the 3D viewport")
            return {"CANCELLED"}
        return {"FINISHED"}


class RIGO_OT_move_tool(Operator):
    """Turn on the Move tool so you can reposition the scan"""

    bl_idname = "rigo.move_tool"
    bl_label = "Move Tool"

    def execute(self, context):
        try:
            bpy.ops.wm.tool_set_by_id(name="builtin.move")
        except RuntimeError:
            self.report({"WARNING"}, "Run this from the 3D viewport")
            return {"CANCELLED"}
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #
class RIGO_OT_fill_holes(Operator):
    """Close gaps and holes left by the scanner"""

    bl_idname = "rigo.fill_holes"
    bl_label = "Fill Holes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.fill_holes(sides=0)  # 0 = fill holes of any size
        bpy.ops.object.mode_set(mode="OBJECT")
        self.report({"INFO"}, "Holes filled")
        return {"FINISHED"}


class RIGO_OT_erase_toggle(Operator):
    """Box-select through the complete mesh, then delete unwanted faces"""

    bl_idname = "rigo.erase_toggle"
    bl_label = "Box Erase"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}
        if obj.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
            previous_xray = bool(obj.get("_rigo_erase_previous_xray", False))
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.spaces.active.shading.show_xray = previous_xray
            if "_rigo_erase_previous_xray" in obj:
                del obj["_rigo_erase_previous_xray"]
            context.workspace.status_text_set(None)
            return {"FINISHED"}

        # A cleanup box must cut through the body along the current viewing
        # direction.  Normal solid selection only catches the visible skin.
        view_spaces = [
            area.spaces.active
            for area in context.screen.areas
            if area.type == "VIEW_3D"
        ]
        obj["_rigo_erase_previous_xray"] = bool(
            view_spaces[0].shading.show_xray if view_spaces else False
        )
        for space in view_spaces:
            space.shading.show_xray = True
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        try:
            bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
        except RuntimeError:
            pass
        context.workspace.status_text_set(
            "THROUGH-MODE: draw one box, then click Delete Box Selection in the panel"
        )
        self.report({"INFO"}, "Through-model Box Erase active (X-ray selection)")
        return {"FINISHED"}


class RIGO_OT_erase_delete(Operator):
    """Delete the selected through-model Box Erase faces"""

    bl_idname = "rigo.erase_delete"
    bl_label = "Delete Box-Erase Selection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        active = context.active_object
        return (
            active is not None
            and active.type == "MESH"
            and active.mode == "EDIT"
            and "_rigo_erase_previous_xray" in active
        )

    def execute(self, context):
        result = bpy.ops.rigo.delete_selection()
        if result == {"FINISHED"}:
            self.report({"INFO"}, "Box selection deleted — continue or finish Box Erase")
        return result


_CLASSES = (
    RIGO_OT_apply_units,
    RIGO_OT_recenter_floor,
    RIGO_OT_realign_tool,
    RIGO_OT_move_tool,
    RIGO_OT_fill_holes,
    RIGO_OT_erase_toggle,
    RIGO_OT_erase_delete,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
