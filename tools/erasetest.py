"""Installed-copy test: Box Erase selects through the complete model depth."""

import bmesh
import bpy


_OUT = r"C:\Projects\Blender Add-on Braces\erasetest_result.txt"
_TRIES = {"n": 0}


def _view_context():
    area = next(a for a in bpy.context.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return area, region, area.spaces.active


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1

    lines = []
    try:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        obj.name = "Patient Scan"
        bpy.context.scene.rigo_brace.scan_object = obj

        area, region, space = _view_context()
        space.shading.show_xray = False
        result_on = bpy.ops.rigo.erase_toggle()
        xray_on = space.shading.show_xray

        # Cover the entire viewport.  In face mode, normal solid selection sees
        # only the near face; X-ray selection must catch all six cube faces.
        with bpy.context.temp_override(
            window=bpy.context.window,
            screen=bpy.context.window.screen,
            area=area,
            region=region,
            space_data=space,
        ):
            bpy.ops.view3d.view_axis(type="BACK")
            bpy.ops.view3d.view_selected(use_all_regions=False)
            bpy.ops.view3d.select_box(
                xmin=0,
                xmax=region.width,
                ymin=0,
                ymax=region.height,
                wait_for_input=False,
                mode="SET",
            )

        bm = bmesh.from_edit_mesh(obj.data)
        selected_faces = sum(1 for face in bm.faces if face.select)
        delete_result = bpy.ops.rigo.erase_delete()
        remaining_faces = len(bmesh.from_edit_mesh(obj.data).faces)
        result_off = bpy.ops.rigo.erase_toggle()
        xray_restored = not space.shading.show_xray
        passed = (
            result_on == {"FINISHED"}
            and result_off == {"FINISHED"}
            and xray_on
            and selected_faces == 6
            and delete_result == {"FINISHED"}
            and remaining_faces == 0
            and xray_restored
        )
        lines.extend(
            (
                f"result_on={result_on}",
                f"xray_on={xray_on}",
                f"selected_faces={selected_faces}",
                f"delete_result={delete_result}",
                f"remaining_faces={remaining_faces}",
                f"result_off={result_off}",
                f"xray_restored={xray_restored}",
                f"PASS={passed}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={exc!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")

    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
