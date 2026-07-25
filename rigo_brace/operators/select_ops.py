"""Painted-region selection — Edit-Mode native brush tools.

The orthotist uses Blender's circle-select brush (like Meshmixer's sphere
Select) to paint faces directly on the mesh in Edit Mode.  The native face
selection IS the region — no sculpt mask needed.  Every action reads the
current face selection directly, so all operations are 100% undo-safe:

    Push Out / In   -> shrink/fatten along normals (interactive drag, mm live readout)
    Thicken         -> solidify the selected patch (local wall thickness)
    Smooth          -> vertex-smooth the selected region
    Delete          -> punch a hole (arm-hole / trim line)

Works on whichever mesh is active — the body scan in Scan, or the corset in Design.
"""

import bmesh
import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _active_mesh(context):
    """Return the mesh being worked on (active object or the registered scan)."""
    obj = context.active_object
    if obj is not None and obj.type == "MESH":
        return obj
    try:
        scan = context.scene.rigo_brace.scan_object
        if scan is not None and scan.type == "MESH":
            return scan
    except Exception:
        pass
    return None


def _find_view3d(context):
    """Return (area, region) for a VIEW_3D, or (None, None)."""
    try:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        return area, region
    except Exception:
        pass
    return None, None


def _ensure_edit_face_mode(context, obj):
    """Guarantee the object is in Edit Mode with face-select mode active."""
    if context.view_layer.objects.active is not obj:
        context.view_layer.objects.active = obj
    if context.mode != "EDIT_MESH":
        bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)


def _has_face_selection(obj):
    """True if at least one face is selected.  Call only while in Edit Mode."""
    bm = bmesh.from_edit_mesh(obj.data)
    return any(f.select for f in bm.faces)


def _set_xray(context, on: bool):
    """Enable/disable X-ray in every VIEW_3D (controls face-through painting)."""
    try:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.show_xray = on
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Paint / grow / shrink / clear / invert
# --------------------------------------------------------------------------- #
class RIGO_OT_paint_select(Operator):
    """Enter face-brush mode: drag on the mesh to select faces"""

    bl_idname = "rigo.paint_select"
    bl_label = "Paint Area"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        context.view_layer.objects.active = obj
        _ensure_edit_face_mode(context, obj)

        # Disable X-ray so Circle Select only paints visible front faces —
        # NOT the hollow back of a body scan (which was the old Box Erase flaw).
        _set_xray(context, False)

        # Keep any existing painted region so re-pressing the button continues
        # the selection ("paint stays until you Clear it").  Only wipe when the
        # whole mesh is selected — that is never a painted region, just
        # Blender's everything-selected state after a fresh import.
        bm = bmesh.from_edit_mesh(obj.data)
        if all(f.select for f in bm.faces):
            bpy.ops.mesh.select_all(action="DESELECT")

        # Activate the circle-select brush cursor.
        area, region = _find_view3d(context)
        try:
            if area is not None:
                with context.temp_override(area=area, region=region):
                    bpy.ops.wm.tool_set_by_id(name="builtin.select_circle")
            else:
                bpy.ops.wm.tool_set_by_id(name="builtin.select_circle")
        except Exception:
            pass

        # Blender's circle select defaults to "Set" mode, which REPLACES the
        # selection on every new drag — wiping the region painted so far.
        # Force "Extend" so each stroke adds to the region (Ctrl+drag still
        # subtracts via the tool's keymap).
        try:
            tool = context.workspace.tools.from_space_view3d_mode(
                "EDIT_MESH", create=False
            )
            if tool is not None and tool.idname == "builtin.select_circle":
                tool.operator_properties("view3d.select_circle").mode = "ADD"
        except Exception:
            pass

        self.report(
            {"INFO"},
            "Drag to select faces  •  Scroll = brush size  •  Ctrl+drag = deselect",
        )
        return {"FINISHED"}


class RIGO_OT_select_grow(Operator):
    """Expand the face selection to neighbouring faces"""

    bl_idname = "rigo.select_grow"
    bl_label = "Grow"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        _ensure_edit_face_mode(context, obj)
        steps = context.scene.rigo_brace.select_grow_steps
        try:
            for _ in range(max(1, steps)):
                bpy.ops.mesh.select_more()
        except Exception as exc:
            self.report({"WARNING"}, f"Grow failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class RIGO_OT_select_shrink(Operator):
    """Contract the face selection inward"""

    bl_idname = "rigo.select_shrink"
    bl_label = "Shrink"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        _ensure_edit_face_mode(context, obj)
        steps = context.scene.rigo_brace.select_grow_steps
        try:
            for _ in range(max(1, steps)):
                bpy.ops.mesh.select_less()
        except Exception as exc:
            self.report({"WARNING"}, f"Shrink failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class RIGO_OT_select_clear(Operator):
    """Deselect all faces"""

    bl_idname = "rigo.select_clear"
    bl_label = "Clear"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        _ensure_edit_face_mode(context, obj)
        bpy.ops.mesh.select_all(action="DESELECT")
        return {"FINISHED"}


class RIGO_OT_select_invert(Operator):
    """Invert the face selection"""

    bl_idname = "rigo.select_invert"
    bl_label = "Invert"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        _ensure_edit_face_mode(context, obj)
        bpy.ops.mesh.select_all(action="INVERT")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Region-driven actions
# --------------------------------------------------------------------------- #
class RIGO_OT_push_selection(Operator):
    """Push the selected faces along their normals.
    Click the button, then drag in the viewport to set the amount interactively,
    then left-click to confirm.  Esc cancels.  Hold Shift for fine control."""

    bl_idname = "rigo.push_selection"
    bl_label = "Push Selection"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction",
        items=(
            ("OUT", "Out", "Inflate outward (pressure pad / build-up)"),
            ("IN",  "In",  "Deflate inward (relief / expansion room)"),
        ),
        default="OUT",
    )

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def invoke(self, context, event):
        obj = _active_mesh(context)
        _ensure_edit_face_mode(context, obj)

        if not _has_face_selection(obj):
            self.report({"WARNING"}, "Paint faces first (use Paint Area)")
            return {"CANCELLED"}

        # Launch native interactive shrink/fatten.
        # The user drags right/left to set the exact amount; left-click confirms.
        # This is 100% undo-safe because it is a built-in modal transform operator.
        area, region = _find_view3d(context)
        try:
            if area is not None:
                with context.temp_override(area=area, region=region):
                    bpy.ops.transform.shrink_fatten(
                        "INVOKE_DEFAULT", use_proportional_edit=False
                    )
            else:
                bpy.ops.transform.shrink_fatten(
                    "INVOKE_DEFAULT", use_proportional_edit=False
                )
        except Exception as exc:
            self.report({"WARNING"}, f"Push failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}

    def execute(self, context):
        """Static path: headless tests, keyboard redo, plain button click."""
        obj = _active_mesh(context)
        _ensure_edit_face_mode(context, obj)

        if not _has_face_selection(obj):
            self.report({"WARNING"}, "Paint faces first (use Paint Area)")
            return {"CANCELLED"}

        settings = context.scene.rigo_brace
        sign  = 1.0 if self.direction == "OUT" else -1.0
        value = sign * settings.select_depth * 0.001   # mm → m (Blender internal)

        # Try native transform op first (requires 3D viewport in context).
        area, region = _find_view3d(context)
        try:
            if area is not None:
                with context.temp_override(area=area, region=region):
                    bpy.ops.transform.shrink_fatten(
                        value=value, use_proportional_edit=False
                    )
            else:
                bpy.ops.transform.shrink_fatten(
                    value=value, use_proportional_edit=False
                )
            verb = "outward" if sign > 0 else "inward"
            self.report({"INFO"}, f"Pushed {settings.select_depth:.1f} mm {verb}")
            return {"FINISHED"}
        except Exception:
            pass

        # BMesh fallback: direct vertex offset (works in timer/headless context).
        bm = bmesh.from_edit_mesh(obj.data)
        bm.normal_update()
        for vert in bm.verts:
            if vert.select:
                vert.co += vert.normal * value
        bmesh.update_edit_mesh(obj.data)
        verb = "outward" if sign > 0 else "inward"
        self.report({"INFO"}, f"Pushed {settings.select_depth:.1f} mm {verb}")
        return {"FINISHED"}


class RIGO_OT_thicken_selection(Operator):
    """Add wall thickness over the selected faces only"""

    bl_idname = "rigo.thicken_selection"
    bl_label = "Thicken Selection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        _ensure_edit_face_mode(context, obj)

        if not _has_face_selection(obj):
            self.report({"WARNING"}, "Paint faces first (use Paint Area)")
            return {"CANCELLED"}

        settings = context.scene.rigo_brace
        thickness = settings.select_thickness * 0.001   # mm → m

        try:
            bpy.ops.mesh.solidify(thickness=thickness)
        except Exception as exc:
            self.report({"WARNING"}, f"Thicken failed: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Thickened {settings.select_thickness:.1f} mm")
        return {"FINISHED"}


class RIGO_OT_smooth_selection(Operator):
    """Smooth the mesh surface within the selected faces"""

    bl_idname = "rigo.smooth_selection"
    bl_label = "Smooth Selection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        _ensure_edit_face_mode(context, obj)

        if not _has_face_selection(obj):
            self.report({"WARNING"}, "Paint faces first (use Paint Area)")
            return {"CANCELLED"}

        settings = context.scene.rigo_brace
        try:
            bpy.ops.mesh.vertices_smooth(
                factor=settings.select_smooth_factor,
                repeat=settings.select_smooth_iters,
            )
        except Exception as exc:
            self.report({"WARNING"}, f"Smooth failed: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Smoothed selected area")
        return {"FINISHED"}


class RIGO_OT_delete_selection(Operator):
    """Delete the selected faces (punch a hole / trim line)"""

    bl_idname = "rigo.delete_selection"
    bl_label = "Delete Selection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        _ensure_edit_face_mode(context, obj)

        if not _has_face_selection(obj):
            self.report({"WARNING"}, "Paint faces first (use Paint Area)")
            return {"CANCELLED"}

        try:
            bpy.ops.mesh.delete(type="FACE")
        except Exception as exc:
            self.report({"WARNING"}, f"Delete failed: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, "Deleted selected faces")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_paint_select,
    RIGO_OT_select_grow,
    RIGO_OT_select_shrink,
    RIGO_OT_select_clear,
    RIGO_OT_select_invert,
    RIGO_OT_push_selection,
    RIGO_OT_thicken_selection,
    RIGO_OT_smooth_selection,
    RIGO_OT_delete_selection,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
