"""Screenshot the deform-plane rings on the scan (visual check)."""
import bpy

_SHOT = r"c:\Projects\Blender Add-on Braces\planes_preview.png"
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

        bpy.ops.rigo.deform_start(method="STRETCH")
        z_min = scan["rigo_deform_zmin"]
        height = scan["rigo_deform_zspan"]
        bpy.data.objects["Rigo Lower Ring"].location.z = z_min + height * 0.1
        bpy.data.objects["Rigo Middle Ring"].location.z = z_min + height * 0.45
        bpy.data.objects["Rigo Upper Ring"].location.z = z_min + height * 0.9
        bpy.ops.rigo.deform_segment(segment="UPPER")
        settings.stretch_mm = 50.0

        bpy.ops.object.select_all(action="DESELECT")
        scan.select_set(True)
        bpy.context.view_layer.objects.active = scan
        for area in bpy.context.window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        with bpy.context.temp_override(area=area, region=region):
                            bpy.ops.view3d.view_axis(type="FRONT")
                            bpy.ops.view3d.view_selected()
                            # 3/4 view, otherwise the flat discs are edge-on.
                            bpy.ops.view3d.view_orbit(angle=0.5, type="ORBITUP")
                            bpy.ops.view3d.view_orbit(angle=0.4, type="ORBITLEFT")
    except Exception:
        import traceback
        traceback.print_exc()
    bpy.app.timers.register(_shot, first_interval=2.0)
    return None


def _shot():
    try:
        lines = []
        for name in (
            "Rigo Lower Ring", "Rigo Middle Ring", "Rigo Upper Ring", "Rigo Bend Axis"
        ):
            obj = bpy.data.objects.get(name)
            if obj is None:
                lines.append(f"{name}: MISSING")
                continue
            lines.append(
                f"{name}: loc={tuple(round(v, 3) for v in obj.location)} "
                f"visible={obj.visible_get()} color={tuple(round(c, 2) for c in obj.color)}"
            )
        for area in bpy.context.window.screen.areas:
            if area.type == "VIEW_3D":
                sh = area.spaces.active.shading
                lines.append(f"shading type={sh.type} color_type={sh.color_type}")
        with open(r"c:\Projects\Blender Add-on Braces\planeshot_debug.txt", "w") as fh:
            fh.write("\n".join(lines))
        bpy.ops.screen.screenshot(filepath=_SHOT)
    except Exception:
        import traceback
        traceback.print_exc()
    bpy.app.timers.register(_quit, first_interval=0.5)
    return None


def _quit():
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(_go, first_interval=1.5)
