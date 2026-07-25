"""UI navigation operators: workflow tabs, viewport options, and the
optional 'Top Tabs' (Blender workspace) layout that mirrors LeoSpinal.

These are pure interface helpers — they never touch the patient mesh.
"""

import bpy
from bpy.types import Operator

from ..core import WORKFLOW_TABS, WORKSPACE_TAB_MAP


# --------------------------------------------------------------------------- #
# Tab navigation (Option B: side-panel tab buttons)
# --------------------------------------------------------------------------- #
class RIGO_OT_set_tab(Operator):
    """Switch the active workflow stage"""

    bl_idname = "rigo.set_tab"
    bl_label = "Set Stage"
    bl_options = {"INTERNAL"}

    tab: bpy.props.StringProperty()

    def execute(self, context):
        stage_ids = {stage[0] for stage in WORKFLOW_TABS}
        if self.tab not in stage_ids:
            self.report({"ERROR"}, f"Unknown workflow stage: {self.tab}")
            return {"CANCELLED"}
        context.scene.rigo_brace.brace_stage = self.tab
        return {"FINISHED"}


class RIGO_OT_step_tab(Operator):
    """Move to the next or previous workflow stage"""

    bl_idname = "rigo.step_tab"
    bl_label = "Change Stage"
    bl_options = {"INTERNAL"}

    direction: bpy.props.EnumProperty(
        items=(("NEXT", "Next", ""), ("PREV", "Previous", "")),
        default="NEXT",
    )

    def execute(self, context):
        settings = context.scene.rigo_brace
        stage_ids = [stage[0] for stage in WORKFLOW_TABS]
        stage_index = stage_ids.index(settings.brace_stage)
        stage_index += 1 if self.direction == "NEXT" else -1
        stage_index = max(0, min(len(stage_ids) - 1, stage_index))
        settings.brace_stage = stage_ids[stage_index]
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Viewport options (the LeoSpinal lower-right floating HUD)
# --------------------------------------------------------------------------- #
def _find_view3d(context):
    """Return the 3D view space + region data, or (None, None)."""
    if getattr(context, "space_data", None) and context.space_data.type == "VIEW_3D":
        return context.space_data, context.space_data.region_3d
    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            return space, space.region_3d
    return None, None


def _view3d_full(context):
    """Return (area, window_region, space) for a VIEW_3D, or (None, None, None).
    Prefers the area the click came from (the N-panel lives in the 3D area)."""
    candidates = []
    if getattr(context, "area", None) and context.area.type == "VIEW_3D":
        candidates.append(context.area)
    # During screen_full_area Blender swaps window.screen to a temporary screen;
    # context.screen can still refer to the screen that initiated the operator.
    screen = context.window.screen if getattr(context, "window", None) else context.screen
    for area in screen.areas:
        if area.type == "VIEW_3D" and area not in candidates:
            candidates.append(area)
    for area in candidates:
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is not None:
            return area, region, area.spaces.active
    return None, None, None


class RIGO_OT_toggle_ground(Operator):
    """Show or hide the ground plane and grid"""

    bl_idname = "rigo.toggle_ground"
    bl_label = "Ground Plane"

    def execute(self, context):
        space, _ = _find_view3d(context)
        if space is None:
            self.report({"WARNING"}, "No 3D view found")
            return {"CANCELLED"}
        ov = space.overlay
        show = not ov.show_floor
        ov.show_floor = show
        ov.show_axis_x = show
        ov.show_axis_y = show
        return {"FINISHED"}


class RIGO_OT_toggle_landmarks(Operator):
    """Show or hide the placed landmark markers"""

    bl_idname = "rigo.toggle_landmarks"
    bl_label = "Show Landmarks"

    def execute(self, context):
        from ..core import LANDMARK_COLLECTION

        coll = bpy.data.collections.get(LANDMARK_COLLECTION)
        if coll is None:
            self.report({"INFO"}, "No landmarks placed yet")
            return {"CANCELLED"}
        coll.hide_viewport = not coll.hide_viewport
        return {"FINISHED"}


class RIGO_OT_toggle_ortho(Operator):
    """Toggle between perspective and orthographic view"""

    bl_idname = "rigo.toggle_ortho"
    bl_label = "Orthographic"

    def execute(self, context):
        _, rv3d = _find_view3d(context)
        if rv3d is None:
            self.report({"WARNING"}, "No 3D view found")
            return {"CANCELLED"}
        rv3d.view_perspective = (
            "ORTHO" if rv3d.view_perspective == "PERSP" else "PERSP"
        )
        return {"FINISHED"}


class RIGO_OT_toggle_measure(Operator):
    """Turn the Blender Measure tool on so you can read distances"""

    bl_idname = "rigo.toggle_measure"
    bl_label = "Measure"

    def execute(self, context):
        try:
            bpy.ops.wm.tool_set_by_id(name="builtin.measure")
        except RuntimeError:
            self.report({"WARNING"}, "Measure tool unavailable here")
            return {"CANCELLED"}
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# View modes (uFit-style): fixed view angles, quad view, full screen, align
# --------------------------------------------------------------------------- #
_VIEW_AXES = (
    ("TOP", "Top", "Look down the Z axis"),
    ("BOTTOM", "Bottom", "Look up the Z axis"),
    ("FRONT", "Front", "Look down the -Y axis"),
    ("BACK", "Back", "Look down the +Y axis"),
    ("LEFT", "Left", "Look down the -X axis"),
    ("RIGHT", "Right", "Look down the +X axis"),
)


class RIGO_OT_view_axis(Operator):
    """Look at the model from a fixed direction"""

    bl_idname = "rigo.view_axis"
    bl_label = "View Axis"
    bl_options = {"INTERNAL"}

    axis: bpy.props.EnumProperty(items=_VIEW_AXES, default="FRONT")

    def execute(self, context):
        area, region, space = _view3d_full(context)
        if area is None:
            self.report({"WARNING"}, "No 3D view found")
            return {"CANCELLED"}
        with context.temp_override(area=area, region=region, space_data=space):
            bpy.ops.view3d.view_axis(type=self.axis)
        return {"FINISHED"}


class RIGO_OT_toggle_quadview(Operator):
    """Toggle the four-up Top/Front/Right/User layout (great for alignment)"""

    bl_idname = "rigo.toggle_quadview"
    bl_label = "Quad View"

    def execute(self, context):
        area, region, space = _view3d_full(context)
        if area is None:
            self.report({"WARNING"}, "No 3D view found")
            return {"CANCELLED"}
        with context.temp_override(area=area, region=region, space_data=space):
            bpy.ops.screen.region_quadview()
        return {"FINISHED"}


class RIGO_OT_toggle_fullscreen(Operator):
    """Toggle a clean viewport while keeping the Rigo controls visible"""

    bl_idname = "rigo.toggle_fullscreen"
    bl_label = "Full Screen"

    def execute(self, context):
        area, region, space = _view3d_full(context)
        if area is None:
            self.report({"WARNING"}, "No 3D view found")
            return {"CANCELLED"}

        scene = context.scene
        state_key = "_rigo_focus_view"
        if scene.get(state_key, False):
            space.show_region_header = bool(scene["_rigo_focus_header"])
            space.show_region_tool_header = bool(scene["_rigo_focus_tool_header"])
            space.show_region_toolbar = bool(scene["_rigo_focus_toolbar"])
            space.show_region_ui = bool(scene["_rigo_focus_sidebar"])
            for key in tuple(scene.keys()):
                if key.startswith("_rigo_focus_"):
                    del scene[key]
            return {"FINISHED"}

        scene["_rigo_focus_header"] = space.show_region_header
        scene["_rigo_focus_tool_header"] = space.show_region_tool_header
        scene["_rigo_focus_toolbar"] = space.show_region_toolbar
        scene["_rigo_focus_sidebar"] = space.show_region_ui
        scene[state_key] = True

        # Preserve both add-on surfaces: the right sidebar and top stage bar.
        space.show_region_header = False
        space.show_region_tool_header = True
        space.show_region_toolbar = False
        space.show_region_ui = True
        return {"FINISHED"}


class RIGO_OT_align_quad(Operator):
    """Open Quad View and the Rotate tool to align the scan to the body axes"""

    bl_idname = "rigo.align_quad"
    bl_label = "Align in Quad View"

    def execute(self, context):
        area, region, space = _view3d_full(context)
        if area is None:
            self.report({"WARNING"}, "No 3D view found")
            return {"CANCELLED"}
        # Turn quad view ON only if it is currently off (the op is a toggle).
        if not space.region_quadviews:
            with context.temp_override(area=area, region=region, space_data=space):
                bpy.ops.screen.region_quadview()
        try:
            bpy.ops.wm.tool_set_by_id(name="builtin.rotate")
        except RuntimeError:
            pass
        self.report({"INFO"}, "Quad view on — rotate the scan to face the front")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Option A: 'Top Tabs' using Blender workspaces
# --------------------------------------------------------------------------- #
class RIGO_OT_setup_workspaces(Operator):
    """Create the five workflow tabs across the top of the window.

    This duplicates the current workspace once per stage and renames it, so the
    orthotist can flip stages from the top bar instead of the side panel.
    """

    bl_idname = "rigo.setup_workspaces"
    bl_label = "Create Top Tabs"

    def execute(self, context):
        existing = set(bpy.data.workspaces.keys())
        wanted = list(WORKSPACE_TAB_MAP.keys())
        created = 0
        for name in wanted:
            if name in existing:
                continue
            # Duplicate the active workspace, then rename the new one.
            before = set(bpy.data.workspaces.keys())
            try:
                bpy.ops.workspace.duplicate()
            except RuntimeError:
                self.report({"WARNING"}, "Run this from the main window")
                return {"CANCELLED"}
            new_name = (set(bpy.data.workspaces.keys()) - before).pop()
            bpy.data.workspaces[new_name].name = name
            created += 1

        context.scene.rigo_brace.ui_mode = "WORKSPACE"
        _subscribe_workspace_sync()
        self.report({"INFO"}, f"Created {created} workflow tabs")
        return {"FINISHED"}


# --- msgbus: keep the panel's tab in sync with the active workspace -------- #
_msgbus_owner = object()


def _on_workspace_change(*_args):
    win = bpy.context.window
    if win is None:
        return
    tab = WORKSPACE_TAB_MAP.get(win.workspace.name)
    if tab is None:
        return
    scene = bpy.context.scene
    if scene and scene.rigo_brace.brace_stage != tab:
        scene.rigo_brace.brace_stage = tab


def _subscribe_workspace_sync():
    bpy.msgbus.clear_by_owner(_msgbus_owner)
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.Window, "workspace"),
        owner=_msgbus_owner,
        args=(),
        notify=_on_workspace_change,
    )


def _unsubscribe_workspace_sync():
    bpy.msgbus.clear_by_owner(_msgbus_owner)


_CLASSES = (
    RIGO_OT_set_tab,
    RIGO_OT_step_tab,
    RIGO_OT_toggle_ground,
    RIGO_OT_toggle_landmarks,
    RIGO_OT_toggle_ortho,
    RIGO_OT_toggle_measure,
    RIGO_OT_view_axis,
    RIGO_OT_toggle_quadview,
    RIGO_OT_toggle_fullscreen,
    RIGO_OT_align_quad,
    RIGO_OT_setup_workspaces,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    _subscribe_workspace_sync()


def unregister():
    _unsubscribe_workspace_sync()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
