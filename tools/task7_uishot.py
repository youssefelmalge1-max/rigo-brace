"""#54 Task 7 UI validation: drive the real panel workflow in GUI Blender and
save viewport screenshots of the drawn outlines.

B scan x1 subdivide, elongated paint (40 x 80 mm), PRESSURE 20 mm Smooth:
Feather 5 -> screenshot, Feather 25 -> screenshot, Feather 50 -> screenshot,
Commit -> screenshot (outline must be gone).  Also a second region made
active -> screenshot (first outline gone).  Writes task7_ui_<step>.png next
to the project and task7_uishot_result.txt.  GUI only.
"""

import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import B_SCAN  # noqa: E402

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "task7_uishot_result.txt")
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _view3d():
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return win, area, region


def _paint_ellipse(obj, frac_z, half_x_m, half_z_m):
    me = obj.data
    cos = [v.co for v in me.vertices]
    lo = Vector((min(c.x for c in cos), min(c.y for c in cos), min(c.z for c in cos)))
    hi = Vector((max(c.x for c in cos), max(c.y for c in cos), max(c.z for c in cos)))
    kd = kdtree.KDTree(len(me.vertices))
    for v in me.vertices:
        kd.insert(v.co, v.index)
    kd.balance()
    _co, seed, _d = kd.find(Vector((
        (lo.x + hi.x) * 0.5, lo.y + 0.10 * (hi.y - lo.y),
        lo.z + frac_z * (hi.z - lo.z),
    )))
    centre = me.vertices[seed].co.copy()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(me)
    for f in bm.faces:
        d = f.calc_center_median() - centre
        lateral = (d.x * d.x + d.y * d.y) ** 0.5
        if (lateral / half_x_m) ** 2 + (d.z / half_z_m) ** 2 <= 1.0:
            f.select = True
    bmesh.update_edit_mesh(me)
    return centre


def _look_at(area, region, centre, distance=0.35):
    r3d = area.spaces.active.region_3d
    r3d.view_location = centre
    r3d.view_distance = distance
    r3d.view_perspective = "PERSP"
    # look from -Y (the front of the torso in this fixture) slightly from the side
    from mathutils import Euler
    r3d.view_rotation = Euler((1.35, 0.0, -0.35)).to_quaternion()
    space = area.spaces.active
    space.shading.type = "SOLID"
    space.shading.light = "MATCAP"
    space.shading.color_type = "OBJECT"
    try:
        space.shading.wireframe_color_type = "OBJECT"
    except AttributeError:
        pass
    space.overlay.show_overlays = True
    space.overlay.show_floor = False
    space.overlay.show_axis_x = False
    space.overlay.show_axis_y = False


def _shot(name):
    win, area, region = _view3d()
    path = os.path.join(_ROOT, f"task7_ui_{name}.png")
    with bpy.context.temp_override(window=win, area=area, region=region,
                                   screen=win.screen, scene=win.scene):
        bpy.ops.screen.screenshot_area(filepath=path)
    _mark(f"shot {name}: {path} exists={os.path.exists(path)}")


def _outline_state(obj):
    names = [o.name for o in bpy.data.objects
             if o.name.endswith(".outline") and o.parent == obj]
    return names


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        from bl_ext.user_default.rigo_brace.operators.scan_ops import (  # noqa
            shade_smooth_scan,
        )
        win, area, region = _view3d()
        with bpy.context.temp_override(window=win, area=area, region=region,
                                       screen=win.screen, scene=win.scene):
            settings = bpy.context.scene.rigo_brace
            bpy.ops.wm.stl_import(filepath=B_SCAN)
            obj = bpy.context.view_layer.objects.active
            settings.scan_object = obj
            settings.scan_units = "mm"
            bpy.ops.rigo.apply_units()
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.subdivide(number_cuts=1, smoothness=1.0)
            bpy.ops.object.mode_set(mode="OBJECT")
            shade_smooth_scan(obj.data)
            obj.color = (0.85, 0.85, 0.85, 1.0)

            centre = _paint_ellipse(obj, 0.45, 0.020, 0.040)
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 20.0
            settings.region_feather = 5.0
            settings.region_falloff = "SMOOTH"
            bpy.ops.rigo.region_add()
            bpy.ops.object.mode_set(mode="OBJECT")
            reg = obj.rigo_regions[obj.rigo_region_index]
            _look_at(area, region, centre)
            _mark(f"region {reg.name} outside={reg.feather_outside} outlines={_outline_state(obj)}")
            _shot("f05")
            reg.feather_mm = 25.0
            _mark(f"feather 25 outlines={_outline_state(obj)}")
            _shot("f25")
            reg.feather_mm = 50.0
            _mark(f"feather 50 outlines={_outline_state(obj)}")
            _shot("f50")
            reg.feather_mm = 25.0
            # second region, active -> the first outline must go away
            centre2 = _paint_ellipse(obj, 0.70, 0.020, 0.030)
            bpy.ops.rigo.region_add()
            bpy.ops.object.mode_set(mode="OBJECT")
            _mark(f"second active outlines={_outline_state(obj)}")
            _look_at(area, region, (Vector(centre) + Vector(centre2)) * 0.5, 0.5)
            _shot("second_active")
            obj.rigo_region_index = 0
            _mark(f"first active again outlines={_outline_state(obj)}")
            _look_at(area, region, centre)
            bpy.ops.rigo.region_apply()
            _mark(f"committed outlines={_outline_state(obj)} note='{reg.commit_note}'")
            _shot("committed")
        _mark("PASS=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=1.0)
