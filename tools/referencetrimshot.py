"""Render four orthographic views of the reference-oriented generated shell."""

import sys

import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402


OUT = r"C:\Projects\Blender Add-on Braces\referencetrimshot.png"
TRIES = {"count": 0}


def _center_at(obj, x, z):
    bounds = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    center = sum(bounds, Vector()) / 8.0
    obj.location += Vector((x - center.x, -center.y, z - center.z))


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["count"] < 30:
        return 0.1
    try:
        scan, settings = prepare_reference_design()
        settings.corset_smooth = 11
        bpy.ops.rigo.generate_curve_corset()
        corset = bpy.data.objects["Rigo Corset"]
        for obj in bpy.context.scene.objects:
            obj.hide_render = True
        views = []
        for index, (angle, x, z) in enumerate(
            (
                (0.0, -0.30, 0.60),
                (1.5707963268, 0.30, 0.60),
                (3.1415926536, -0.30, 0.00),
                (-1.5707963268, 0.30, 0.00),
            )
        ):
            view = corset.copy()
            view.data = corset.data.copy()
            view.name = f"Reference Trim View {index + 1}"
            bpy.context.scene.collection.objects.link(view)
            view.rotation_euler.z += angle
            view.color = (0.74, 0.80, 0.88, 1.0)
            view.hide_render = False
            bpy.context.view_layer.update()
            _center_at(view, x, z)
            views.append(view)
        corset.hide_render = True
        scan.hide_render = True

        camera_data = bpy.data.cameras.new("Reference Trim Camera")
        camera = bpy.data.objects.new("Reference Trim Camera", camera_data)
        bpy.context.scene.collection.objects.link(camera)
        camera.location = (0.0, -3.0, 0.30)
        camera.rotation_euler = (
            Vector((0.0, 0.0, 0.30)) - camera.location
        ).to_track_quat("-Z", "Y").to_euler()
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = 1.22
        scene = bpy.context.scene
        scene.camera = camera
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "OBJECT"
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
        scene.render.resolution_x = 1400
        scene.render.resolution_y = 1400
        scene.render.resolution_percentage = 100
        scene.render.filepath = OUT
        bpy.ops.render.render(write_still=True)
    except Exception:
        import traceback

        with open(
            r"C:\Projects\Blender Add-on Braces\referencetrimshot_error.txt",
            "w",
            encoding="utf-8",
        ) as error_file:
            error_file.write(traceback.format_exc())
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
