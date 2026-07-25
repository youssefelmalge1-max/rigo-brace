"""Remold tools — reshape the body surface by hand (sculpt) before correction.

"Remold" is the digital version of adding/removing plaster: the orthotist pushes
or pulls the surface to relieve bony prominences and prepare the trim areas.

We keep this dead simple for low-3D-skill users: one button drops into Blender's
Sculpt mode with a comfortable brush size/strength taken from the panel sliders.
The same button brings them back to normal (Object) mode. The orthotist then
picks Draw (push out / add) or Grab/Smooth from the brush bar at the top.
"""

import bpy
from bpy.types import Operator


def _unified_paint_settings(context):
    """Return the unified brush settings on any Blender version.

    Blender 5.0 removed ``tool_settings.unified_paint_settings`` and moved it
    onto the per-mode Paint struct (``tool_settings.sculpt``), which only
    exists after Sculpt mode has been entered at least once — so callers must
    switch modes *before* asking for it. Verified empirically on 5.0.1.
    """
    ts = context.scene.tool_settings
    ups = getattr(ts, "unified_paint_settings", None)  # Blender <= 4.x
    if ups is None and ts.sculpt is not None:
        ups = ts.sculpt.unified_paint_settings
    return ups


class RIGO_OT_remold_toggle(Operator):
    """Enter or leave Remold (Sculpt) mode on the active mesh"""

    bl_idname = "rigo.remold_toggle"
    bl_label = "Remold (Sculpt) On/Off"
    bl_options = {"REGISTER"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}

        if obj.mode == "SCULPT":
            bpy.ops.object.mode_set(mode="OBJECT")
            self.report({"INFO"}, "Left Remold mode")
            return {"FINISHED"}

        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        settings = context.scene.rigo_brace
        # Enter Sculpt mode FIRST: on 5.0 the unified settings hang off
        # tool_settings.sculpt, which is created on first Sculpt entry.
        bpy.ops.object.mode_set(mode="SCULPT")
        ups = _unified_paint_settings(context)
        if ups is not None:
            ups.use_unified_size = True
            ups.size = settings.remold_brush_size
            ups.use_unified_strength = True
            ups.strength = settings.remold_brush_strength
        self.report({"INFO"}, "Remold mode: pick a brush from the top bar")
        return {"FINISHED"}


class RIGO_OT_remold_apply_sliders(Operator):
    """Push the panel brush size/strength into the active Sculpt brush"""

    bl_idname = "rigo.remold_apply_sliders"
    bl_label = "Apply Brush Settings"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.rigo_brace
        ups = _unified_paint_settings(context)
        if ups is None:
            self.report({"WARNING"}, "Enter Remold mode first")
            return {"CANCELLED"}
        ups.use_unified_size = True
        ups.size = settings.remold_brush_size
        ups.use_unified_strength = True
        ups.strength = settings.remold_brush_strength
        self.report({"INFO"}, "Brush settings applied")
        return {"FINISHED"}


_CLASSES = (RIGO_OT_remold_toggle, RIGO_OT_remold_apply_sliders)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
