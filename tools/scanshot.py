"""Screenshot the trimmed Scan stage panel (visual check of the cleanup)."""
import bpy

_SHOT = r"c:\Projects\Blender Add-on Braces\scan_preview.png"
_SAMPLE = r"c:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}


def _go():
    _TRIES["n"] += 1
    if not (hasattr(bpy.types, "RIGO_PT_main") and len(bpy.data.workspaces) == 1):
        if _TRIES["n"] < 60:
            return 0.2
    try:
        settings = bpy.context.scene.rigo_brace
        settings.brace_stage = "SCAN"
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        for area in bpy.context.window.screen.areas:
            area.tag_redraw()
    except Exception:
        import traceback
        traceback.print_exc()
    bpy.app.timers.register(_shot, first_interval=1.0)
    return None


def _shot():
    try:
        bpy.ops.screen.screenshot(filepath=_SHOT)
    except Exception:
        import traceback
        traceback.print_exc()
    bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=0.5)
    return None


bpy.app.timers.register(_go, first_interval=1.5)
