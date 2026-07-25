"""Screenshot a placed pad outline on the scan (visual check)."""
import bpy

_SHOT = r"c:\Projects\Blender Add-on Braces\pad_preview.png"
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
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()

        # Place a pressure shape on the upper face (+Z of the lying scan).
        mw = scan.matrix_world
        verts = [mw @ v.co for v in scan.data.vertices]
        idx = max(range(len(verts)), key=lambda i: verts[i].z)
        settings.pad_type = "BLANK_OVAL"
        bpy.ops.rigo.add_pad(location=verts[idx], use_location=True)

        bpy.ops.object.select_all(action="DESELECT")
        scan.select_set(True)
        for area in bpy.context.window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        with bpy.context.temp_override(area=area, region=region):
                            bpy.ops.view3d.view_axis(type="TOP")
                            bpy.ops.view3d.view_selected()
                            bpy.ops.view3d.view_orbit(angle=0.4, type="ORBITUP")
    except Exception:
        import traceback
        traceback.print_exc()
    bpy.app.timers.register(_shot, first_interval=2.0)
    return None


def _shot():
    try:
        bpy.ops.screen.screenshot(filepath=_SHOT)
    except Exception:
        pass
    bpy.app.timers.register(_quit, first_interval=0.5)
    return None


def _quit():
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_go, first_interval=1.5)
