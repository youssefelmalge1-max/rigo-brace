"""Deterministic before/after captures for the trimline patches (P1-P4).

Same fixture, same framing, same shading for every run; the tag names the
pipeline state so runs are comparable pixel for pixel:

    RIGO_SHOT_TAG=baseline  (or p1, p2, p3, p4)

Writes trimshot_<tag>_{front,side,oblique,trimview}.png plus
trimshot_<tag>.txt carrying the corset positional hash - the display-only
patches must keep that hash identical to the baseline.
"""

import hashlib
import math
import os
import sys
import traceback

import bpy
from mathutils import Euler, Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

TAG = os.environ.get("RIGO_SHOT_TAG", "baseline")
ROOT = r"C:\Projects\Blender Add-on Braces"
TRIES = {"n": 0}

VIEWS = (
    ("front", Euler((math.radians(90.0), 0.0, 0.0), "XYZ")),
    ("side", Euler((math.radians(90.0), 0.0, math.radians(90.0)), "XYZ")),
    ("oblique", Euler((math.radians(75.0), 0.0, math.radians(35.0)), "XYZ")),
)


def _mesh_hash(mesh):
    ordered = [tuple(round(c, 9) for c in v.co) for v in mesh.vertices]
    return hashlib.sha256(repr(ordered).encode()).hexdigest()[:16]


def _apply_style(space):
    shading = space.shading
    shading.type = "SOLID"
    shading.light = "STUDIO"
    shading.color_type = "OBJECT"
    shading.show_xray = False
    space.overlay.show_floor = False
    space.overlay.show_axis_x = False
    space.overlay.show_axis_y = False
    space.overlay.show_cursor = False
    space.overlay.show_object_origins = False
    space.overlay.show_relationship_lines = False
    space.overlay.show_outline_selected = False
    space.overlay.show_extras = False


def _frame(space, center, distance, rotation):
    region_3d = space.region_3d
    region_3d.view_perspective = "ORTHO"
    region_3d.view_location = center
    region_3d.view_rotation = rotation.to_quaternion()
    region_3d.view_distance = distance
    region_3d.update()


def _capture(area, space, path):
    region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(area=area, region=region):
        bpy.context.scene.render.filepath = path
        bpy.context.scene.render.resolution_x = 1400
        bpy.context.scene.render.resolution_y = 1000
        bpy.ops.render.opengl(write_still=True)


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    log = [f"tag={TAG}"]
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        bpy.ops.rigo.generate_curve_corset()
        corset = bpy.data.objects["Rigo Corset"]
        log.append(
            f"corset verts={len(corset.data.vertices)} "
            f"hash={_mesh_hash(corset.data)}"
        )
        visible = sorted(
            obj.name
            for obj in bpy.context.view_layer.objects
            if obj is not None and not obj.hide_get()
        )
        log.append(f"visible_in_brace_view={visible}")

        corners = [corset.matrix_world @ Vector(c) for c in corset.bound_box]
        center = sum(corners, Vector()) / 8.0
        distance = (
            max((corner - center).length for corner in corners) * 2.1
        )
        area = next(
            a for a in bpy.context.screen.areas if a.type == "VIEW_3D"
        )
        space = area.spaces.active
        _apply_style(space)
        for view_name, rotation in VIEWS:
            _frame(space, center, distance, rotation)
            _capture(
                area, space, rf"{ROOT}\trimshot_{TAG}_{view_name}.png"
            )
        if hasattr(settings, "show_trim_overlay"):
            settings.show_trim_overlay = True
            _frame(space, center, distance, VIEWS[0][1])
            _capture(area, space, rf"{ROOT}\trimshot_{TAG}_overlayon.png")
            settings.show_trim_overlay = False
        from bl_ext.user_default.rigo_brace.operators import design_ops

        design_ops._set_design_view(bpy.context, "TRIM")
        _frame(space, center, distance, VIEWS[0][1])
        _capture(area, space, rf"{ROOT}\trimshot_{TAG}_trimview.png")
        visible = sorted(
            obj.name
            for obj in bpy.context.view_layer.objects
            if obj is not None and not obj.hide_get()
        )
        log.append(f"visible_in_trim_view={visible}")
    except Exception as error:  # noqa: BLE001
        log.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(
        rf"{ROOT}\trimshot_{TAG}.txt", "w", encoding="utf-8"
    ) as handle:
        handle.write("\n".join(log))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
