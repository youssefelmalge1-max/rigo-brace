"""Rigo Brace — Blender Application Template.

An application template is Blender's official way to ship a custom, stripped-down
experience. When Blender is launched with this template it:

    * opens the plain startup scene bundled here (startup.blend) — no default
      cube, camera or light, just an empty stage ready for a patient scan;
    * makes sure the Rigo Brace add-on is enabled so the side panel is present.

The orthotist never sees the template machinery — they just double-click the
"Rigo Brace" desktop icon created by install.ps1 and land straight in the tool.

Note: the template's register() runs very early, before Blender's extension
system (bl_pkg) is initialized, so enabling the add-on directly here can fail.
We therefore defer enabling onto an app timer that retries until the extension
system is ready.
"""

import addon_utils
import bpy

# Candidate module names for the Rigo Brace add-on, most-preferred first.
# Installed as an extension it is "bl_ext.user_default.rigo_brace"; installed as
# a legacy add-on it is simply "rigo_brace".
_ADDON_CANDIDATES = (
    "bl_ext.user_default.rigo_brace",
    "rigo_brace",
)
_QUAD_REMESHER_ADDON = "quad_remesher_1_4"

# How many times the deferred timer retries before giving up.
_MAX_ATTEMPTS = 80
_attempts = 0
_cleaned = False
_finished = False

# Default Blender workspace tabs the orthotist never needs.
_KEEP_WORKSPACE = "Rigo Brace"


def _addon_active():
    return hasattr(bpy.types, "RIGO_PT_main")


def _quad_remesher_active():
    return hasattr(bpy.types, "QREMESHER_OT_remesh")


def _enable_quad_remesher():
    if _quad_remesher_active():
        return
    try:
        addon_utils.enable(_QUAD_REMESHER_ADDON, default_set=True, persistent=True)
    except (ImportError, ModuleNotFoundError):
        return


def _strip_workspaces():
    """Leave only the pre-baked "Rigo Brace" workspace (whose screen already has
    the single full viewport + open N-panel from startup.blend). We ONLY delete
    the other workspace tabs — we never touch areas/regions, because the baked
    screen is already correct and area surgery at runtime corrupts it.

    Deletion is spread over several timer ticks: assigning window.workspace is
    deferred (applied on the next event-loop pass), and workspace.delete removes
    the window's *active* workspace. So each pass we either (a) switch the window
    onto a doomed workspace, or (b) delete the doomed workspace that is now
    active. This avoids accidentally deleting the keeper."""
    global _cleaned
    if _cleaned or bpy.app.background:
        return
    wm = bpy.context.window_manager
    if wm is None or not wm.windows:
        return  # no real window yet — try again next tick

    try:
        workspaces = bpy.data.workspaces
        keeper = workspaces.get(_KEEP_WORKSPACE)
    except AttributeError:
        return  # bpy.data still restricted (early register) — retry next tick
    if keeper is None:
        return

    window = wm.windows[0]
    doomed = [w for w in workspaces if w is not keeper]
    if not doomed:
        try:
            window.workspace = keeper
        except Exception:
            pass
        _cleaned = True
        return

    active = window.workspace
    if active is not keeper:
        # The deferred switch has taken effect — delete this doomed workspace.
        try:
            with bpy.context.temp_override(window=window, workspace=active):
                bpy.ops.workspace.delete()
        except Exception:
            pass
    else:
        # Request a switch onto a doomed workspace; it deletes next tick.
        try:
            window.workspace = doomed[0]
        except Exception:
            pass


def _finish_setup():
    """The baked startup.blend already has the single viewport, open N-panel,
    tool-header and SOLID shading. At runtime we only need to apply the clinical
    theme and make the side panel default to the "Rigo Brace" category (touching
    regions at runtime corrupts the baked screen, so we only set the category)."""
    global _finished
    if _finished or bpy.app.background:
        return
    wm = bpy.context.window_manager
    if wm is None or not wm.windows:
        return
    # Show the Rigo Brace tab in the N-panel rather than Blender's Tool tab.
    # The category only "takes" once the region has been drawn (its category
    # list is populated then), so we keep trying until it sticks.
    category_ok = True
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "UI":
                    try:
                        region.active_panel_category = _KEEP_WORKSPACE
                        region.tag_redraw()
                    except Exception:
                        pass
                    if region.active_panel_category != _KEEP_WORKSPACE:
                        category_ok = False
    _apply_theme()
    _finished = category_ok


def _apply_theme():
    """Apply a light, clinical viewport palette (brand blue accent)."""
    try:
        theme = bpy.context.preferences.themes[0]
    except Exception:
        return
    try:
        grad = theme.view_3d.space.gradients
        grad.background_type = "LINEAR"
        grad.high_gradient = (0.93, 0.95, 0.97)   # soft light top
        grad.gradient = (0.82, 0.86, 0.90)        # cool clinical bottom
    except Exception:
        pass
    # Trim-line editing: blue position points, green roundness handles, to match
    # the LeoSpinal "Outline" tool.
    try:
        v3d = theme.view_3d
        v3d.vertex = (0.15, 0.45, 0.95)
        v3d.vertex_select = (0.30, 0.65, 1.0)
        v3d.handle_auto = (0.20, 0.80, 0.35)
        v3d.handle_sel_auto = (0.40, 0.95, 0.50)
        v3d.handle_free = (0.20, 0.80, 0.35)
        v3d.handle_sel_free = (0.40, 0.95, 0.50)
    except Exception:
        pass

def _try_enable():
    """Timer callback. Order matters: tidy the screen FIRST (before the add-on
    adds its tool-header draw callback, so closing areas can't crash), then
    enable the add-on, then reveal its regions and theme."""
    global _attempts
    _attempts += 1

    # 1) Screen / workspace surgery (independent of the add-on).
    _strip_workspaces()

    # 2) Enable the add-on.
    if not _addon_active():
        for name in _ADDON_CANDIDATES:
            try:
                addon_utils.enable(name, default_set=True, persistent=True)
            except Exception:
                continue
            if _addon_active():
                break

    if _addon_active():
        _enable_quad_remesher()
        # 3) Reveal regions + theme now that the UI is registered.
        _finish_setup()
        if (_cleaned and _finished) or bpy.app.background or _attempts >= _MAX_ATTEMPTS:
            return None
        return 0.1

    if _attempts >= _MAX_ATTEMPTS:
        return None  # give up quietly
    return 0.1  # not ready yet — try again shortly


def register():
    global _attempts, _cleaned, _finished
    _attempts = 0
    _cleaned = False
    _finished = False
    # Always defer onto the app timer. Running enable()/screen surgery directly
    # in register() executes during Blender's restricted-context phase (bpy.data
    # locked) and can double-register or crash, so we never do it synchronously.
    if not bpy.app.timers.is_registered(_try_enable):
        bpy.app.timers.register(_try_enable, first_interval=0.0)


def unregister():
    if bpy.app.timers.is_registered(_try_enable):
        bpy.app.timers.unregister(_try_enable)

