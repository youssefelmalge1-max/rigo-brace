"""Bake the Rigo Brace startup.blend in a *real* GUI session.

The headless make_startup.py cannot configure the screen (no window exists in
--background), and doing the same work from the application template at runtime
means fighting Blender's restricted context every launch. Instead we build the
finished layout ONCE here, in a normal GUI Blender, and save it as the template's
startup.blend:

    * empty scene (no cube/camera/light)
    * a single workspace renamed "Rigo Brace"
    * a single full 3D viewport with the N-side-panel open on the Rigo Brace tab
    * the top tool-header visible (where the step bar draws) and Solid shading

Run by install.ps1 via:
    blender --factory-startup --python tools/build_startup_gui.py -- <out.blend>

The script works on an app timer (so the window/context is fully ready), saves,
then quits.
"""

import sys

import bpy
import addon_utils

_ADDON_CANDIDATES = ("bl_ext.user_default.rigo_brace", "rigo_brace")
_KEEP = "Rigo Brace"
_ticks = 0


def _output_path():
    argv = sys.argv
    if "--" in argv:
        extra = argv[argv.index("--") + 1:]
        if extra:
            return extra[0]
    raise SystemExit("No output path given after '--'")


def _clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def _enable_addon():
    for name in _ADDON_CANDIDATES:
        try:
            addon_utils.enable(name, default_set=True, persistent=True)
        except Exception:
            continue
        if hasattr(bpy.types, "RIGO_PT_main"):
            return name
    return None


def _strip_and_collapse():
    wm = bpy.context.window_manager
    workspaces = bpy.data.workspaces
    keeper = workspaces.get(_KEEP) or workspaces.get("Layout") or workspaces[0]
    keeper.name = _KEEP

    window = wm.windows[0]
    for ws in list(workspaces):
        if ws is keeper:
            continue
        try:
            window.workspace = ws
            with bpy.context.temp_override(window=window, workspace=ws):
                bpy.ops.workspace.delete()
        except Exception:
            pass
    window.workspace = keeper

    # Collapse the kept screen to a single viewport.
    screen = window.screen
    for _ in range(12):
        if len(screen.areas) <= 1:
            break
        target = min(screen.areas, key=lambda a: a.width * a.height)
        try:
            with bpy.context.temp_override(window=window, screen=screen, area=target):
                bpy.ops.screen.area_close()
        except Exception:
            break
    if screen.areas and screen.areas[0].type != "VIEW_3D":
        screen.areas[0].type = "VIEW_3D"


def _setup_viewport():
    window = bpy.context.window_manager.windows[0]
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        with bpy.context.temp_override(window=window, area=area, space=space):
            space.show_region_tool_header = True
            space.show_region_ui = True
        space.shading.type = "SOLID"
        space.clip_end = 100000.0
        for region in area.regions:
            if region.type == "UI":
                try:
                    region.active_panel_category = "Rigo Brace"
                except Exception:
                    pass


def _build():
    global _ticks
    _ticks += 1
    wm = bpy.context.window_manager
    ready = (
        wm is not None
        and wm.windows
        and len(wm.windows[0].screen.areas) > 0
    )
    if not ready and _ticks < 40:
        return 0.2

    _clear_scene()
    name = _enable_addon()
    _strip_and_collapse()
    _setup_viewport()

    # Set scene units to millimetres so interactive operators (shrink_fatten etc.)
    # display their readout in mm rather than metres.
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"

    out = _output_path()
    bpy.ops.wm.save_as_mainfile(filepath=out)
    n_ws = len(bpy.data.workspaces)
    n_area = len(wm.windows[0].screen.areas)
    print(f"[build_startup_gui] addon={name} workspaces={n_ws} areas={n_area} -> {out}")

    bpy.app.timers.register(_quit, first_interval=0.3)
    return None


def _quit():
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_build, first_interval=1.0)
