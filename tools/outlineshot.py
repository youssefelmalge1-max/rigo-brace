"""Generate a corset, enter trim-line edit, screenshot the blue/green points."""
import bpy

_SHOT = r"c:\Projects\Blender Add-on Braces\ui_preview.png"
_SAMPLE = r"c:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}


def _go():
    _TRIES["n"] += 1
    if not (hasattr(bpy.types, "RIGO_PT_main") and len(bpy.data.workspaces) == 1):
        if _TRIES["n"] < 60:
            return 0.2
    try:
        settings = bpy.context.scene.rigo_brace
        settings.brace_stage = "DESIGN"
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings.scan_object = scan
        settings.trim_top = 30.0
        settings.trim_bottom = 30.0
        settings.opening_width = 40.0
        bpy.ops.rigo.generate_corset()
        bpy.ops.rigo.edit_outline()
        # Frame the model.
        for area in bpy.context.window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        with bpy.context.temp_override(area=area, region=region):
                            bpy.ops.view3d.view_all()
    except Exception:
        import traceback
        traceback.print_exc()
    bpy.app.timers.register(_shot, first_interval=1.0)
    return None


def _shot():
    try:
        bpy.ops.screen.screenshot(filepath=_SHOT)
    except Exception:
        pass
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender(), first_interval=0.5)
    return None


bpy.app.timers.register(_go, first_interval=1.5)
