"""Screenshot the Mesh Edit tab with the Select Area tools + mask painted."""
import bpy
from mathutils import Vector

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
        settings.brace_stage = "MESH"
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan

        # Paint a visible mask band on a flank.
        me = scan.data
        attr = me.attributes.get(".sculpt_mask") or me.attributes.new(
            ".sculpt_mask", "FLOAT", "POINT"
        )
        bb = [Vector(c) for c in scan.bound_box]
        radius = (bb[6] - bb[0]).length * 0.14
        sidx = max(range(len(me.vertices)), key=lambda i: me.vertices[i].co.x)
        center = me.vertices[sidx].co.copy()
        for i, v in enumerate(me.vertices):
            d = (v.co - center).length
            if d < radius:
                attr.data[i].value = max(0.0, 1.0 - d / radius)
        me.update()

        bpy.ops.rigo.paint_select()
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
