"""Close-up rim captures, same camera, old sine arch vs tangent bullnose.

RIGO_SHOT_PROFILE=sine restores the retired sine-arch cross-section before
generating, so the before/after pair differs only in the profile - same
fixture, same camera, same lighting, same shading.

RIGO_SHOT_STYLE=solid|matcap|wire selects the viewport shading.
"""

import math
import os
import sys
import traceback

import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import curve_build_ops  # noqa: E402

PROFILE = os.environ.get("RIGO_SHOT_PROFILE", "bullnose")
STYLE = os.environ.get("RIGO_SHOT_STYLE", "solid")
OUT = (
    r"C:\Projects\Blender Add-on Braces\rimshot_"
    f"{PROFILE}_{STYLE}.png"
)
TRIES = {"n": 0}


def _sine_profile(coordinates, topology, vertex):
    """The retired cross-section: linear across the wall, sinusoidal bulge."""
    inner = coordinates[vertex.index]
    outer = coordinates[vertex.index + topology.vertex_count]
    profile = [vertex.index]
    for step in range(1, topology.segments):
        fraction = step / topology.segments
        profile.append(len(coordinates))
        centre = inner.lerp(outer, fraction)
        coordinates.append(
            centre
            + vertex.outward * vertex.radius * math.sin(math.pi * fraction)
        )
    profile.append(vertex.index + topology.vertex_count)
    return profile


def _apply_style(space):
    shading = space.shading
    shading.show_xray = False
    if STYLE == "wire":
        shading.type = "SOLID"
        shading.light = "FLAT"
        shading.color_type = "SINGLE"
        shading.single_color = (0.82, 0.85, 0.90)
        space.overlay.show_wireframes = True
        space.overlay.wireframe_threshold = 1.0
        space.overlay.wireframe_opacity = 1.0
    elif STYLE == "matcap":
        shading.type = "SOLID"
        shading.light = "MATCAP"
        shading.studio_light = "check_rim_dark.exr"
        space.overlay.show_wireframes = False
    else:
        shading.type = "SOLID"
        shading.light = "STUDIO"
        shading.color_type = "SINGLE"
        shading.single_color = (0.80, 0.83, 0.88)
        space.overlay.show_wireframes = False
    space.overlay.show_floor = False
    space.overlay.show_axis_x = False
    space.overlay.show_axis_y = False
    space.overlay.show_cursor = False
    space.overlay.show_object_origins = False
    space.overlay.show_relationship_lines = False
    space.overlay.show_outline_selected = False


def _worst_hairpin(corset):
    """Boundary-ring point whose local turn is tightest - the hard case."""
    mesh = corset.data
    group = corset.vertex_groups.get("RIGO_RIM_BOUNDARY")
    if group is None:
        return None
    rim = [
        vertex.co.copy()
        for vertex in mesh.vertices
        if any(entry.group == group.index for entry in vertex.groups)
    ]
    if len(rim) < 3:
        return None
    # Cheapest robust proxy for "tight turn": the rim point with the most
    # rim neighbours crowded inside a small radius.
    best, best_count = None, -1
    step = max(1, len(rim) // 400)
    for point in rim[::step]:
        count = sum(1 for other in rim[::step] if (other - point).length < 0.004)
        if count > best_count:
            best, best_count = point, count
    return best


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    try:
        if PROFILE == "sine":
            curve_build_ops._rim_profile = _sine_profile
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        bpy.ops.rigo.generate_curve_corset()
        corset = bpy.data.objects["Rigo Corset"]
        for obj in bpy.context.scene.objects:
            obj.hide_set(obj is not corset)
        corset.hide_set(False)

        target = _worst_hairpin(corset) or Vector((0.0, 0.0, 0.0))
        world = corset.matrix_world @ target

        area = next(
            a for a in bpy.context.screen.areas if a.type == "VIEW_3D"
        )
        space = area.spaces.active
        _apply_style(space)
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.view3d.view_axis(type="FRONT")
            bpy.context.scene.cursor.location = world
            bpy.ops.view3d.view_center_cursor()
            space.region_3d.view_distance = 0.035
            space.region_3d.update()
            bpy.context.scene.render.filepath = OUT
            bpy.context.scene.render.resolution_x = 1400
            bpy.context.scene.render.resolution_y = 1000
            bpy.ops.render.opengl(write_still=True)
        with open(OUT + ".txt", "w", encoding="utf-8") as handle:
            handle.write(
                f"profile={PROFILE} style={STYLE} target={tuple(world)}\n"
            )
    except Exception as error:  # noqa: BLE001
        with open(OUT + ".txt", "w", encoding="utf-8") as handle:
            handle.write(f"ERROR={error!r}\n{traceback.format_exc()}")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
