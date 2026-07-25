"""Anatomical landmark placement.

Landmarks are empties placed on the patient scan. They live in their own
collection so they are easy to show/hide, and they are named LM_<ID> so later
tools (automatic pad and relief placement, curve measurement) can find them.

Workflow for the orthotist:
    1. Pick a landmark from the dropdown.
    2. Move the 3D cursor onto the spot (Shift + Right Click on the scan).
    3. Press "Place Landmark".
The empty is created at the 3D cursor. Placing the same landmark again moves the
existing one instead of creating a duplicate.
"""

import bpy
from bpy.types import Operator
from bpy_extras import view3d_utils

from ..core import (
    LANDMARK_COLLECTION,
    LANDMARK_PREFIX,
    LANDMARKS,
)


def _get_landmark_collection(context):
    """Return (creating if needed) the collection that holds landmark empties."""
    coll = bpy.data.collections.get(LANDMARK_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(LANDMARK_COLLECTION)
        context.scene.collection.children.link(coll)
    return coll


def _label_for(identifier):
    for ident, label, _desc in LANDMARKS:
        if ident == identifier:
            return label
    return identifier


def _place_landmark(context, identifier, location):
    """Create or move the empty for ``identifier`` to ``location``."""
    name = f"{LANDMARK_PREFIX}{identifier}"
    empty = bpy.data.objects.get(name)
    if empty is None:
        empty = bpy.data.objects.new(name, None)
        empty.empty_display_type = "SPHERE"
        empty.empty_display_size = 0.01
        empty.show_name = True
        _get_landmark_collection(context).objects.link(empty)
    empty.location = location
    return empty


class RIGO_OT_place_landmark(Operator):
    """Place the selected anatomical landmark at the 3D cursor"""

    bl_idname = "rigo.place_landmark"
    bl_label = "Place Landmark"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.rigo_brace
        identifier = settings.active_landmark
        location = context.scene.cursor.location.copy()
        _place_landmark(context, identifier, location)
        self.report({"INFO"}, f"Placed: {_label_for(identifier)}")
        return {"FINISHED"}


class RIGO_OT_pick_landmark(Operator):
    """Click directly on the scan to drop each landmark in order.

    Left-click places the current landmark on the surface under the cursor and
    advances to the next one in the list. Right-click or Esc stops.
    """

    bl_idname = "rigo.pick_landmark"
    bl_label = "Pick Landmarks on Scan"

    _region = None
    _rv3d = None

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        # Find the 3D viewport's WINDOW region for raycasting.
        for region in context.area.regions:
            if region.type == "WINDOW":
                self._region = region
                break
        self._rv3d = context.area.spaces.active.region_3d
        if self._region is None or self._rv3d is None:
            self.report({"WARNING"}, "Open this from the 3D viewport")
            return {"CANCELLED"}
        context.window.cursor_modal_set("EYEDROPPER")
        context.workspace.status_text_set(
            "Left-click on the scan to place a landmark  |  Right-click / Esc to finish"
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)

    def _ray(self, context, event):
        region, rv3d = self._region, self._rv3d
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        if not (0 <= coord[0] <= region.width and 0 <= coord[1] <= region.height):
            return None
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        depsgraph = context.evaluated_depsgraph_get()
        hit, location, _normal, _idx, _obj, _mat = context.scene.ray_cast(
            depsgraph, origin, direction
        )
        return location if hit else None

    def _advance(self, context):
        settings = context.scene.rigo_brace
        ids = [i for i, _l, _d in LANDMARKS]
        i = ids.index(settings.active_landmark)
        if i + 1 < len(ids):
            settings.active_landmark = ids[i + 1]
            return True
        return False  # placed the last one

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._finish(context)
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            location = self._ray(context, event)
            if location is None:
                self.report({"WARNING"}, "Click on the scan surface")
                return {"RUNNING_MODAL"}
            settings = context.scene.rigo_brace
            current = settings.active_landmark
            _place_landmark(context, current, location)
            self.report({"INFO"}, f"Placed: {_label_for(current)}")
            if not self._advance(context):
                self._finish(context)
                self.report({"INFO"}, "All landmarks placed")
                return {"FINISHED"}
            return {"RUNNING_MODAL"}

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}  # let the user orbit/zoom while picking

        return {"RUNNING_MODAL"}


class RIGO_OT_clear_landmarks(Operator):
    """Delete all placed landmarks"""

    bl_idname = "rigo.clear_landmarks"
    bl_label = "Clear All Landmarks"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = 0
        for obj in list(bpy.data.objects):
            if obj.name.startswith(LANDMARK_PREFIX):
                bpy.data.objects.remove(obj, do_unlink=True)
                removed += 1
        self.report({"INFO"}, f"Removed {removed} landmark(s)")
        return {"FINISHED"}


_CLASSES = (RIGO_OT_place_landmark, RIGO_OT_pick_landmark, RIGO_OT_clear_landmarks)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
