"""Bake the LEGACY (inward-feather, pre-Task-7) region fixture.

Run ONCE with the pre-Task-7 installed add-on (2026-09-09, DEC-0070):
B scan x1 subdivide, circle r 35 mm at 45 % height, 15 mm PRESSURE,
Feather 10, Smooth, region_add, then saved as
``legacy_inward_region.blend`` in the project root (gitignored: patient
data).  tools/featherlifecycletest.py opens it to prove that stored
regions keep their inward semantics after the outward feather lands.
Writes makelegacyfixture_result.txt.  GUI only.
"""

import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import B_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\makelegacyfixture_result.txt"
_BLEND = r"C:\Projects\Blender Add-on Braces\legacy_inward_region.blend"
_TRIES = {"n": 0}


def _paint_circle(obj, frac_z, r_m):
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
        if (f.calc_center_median() - centre).length < r_m:
            f.select = True
    bmesh.update_edit_mesh(me)


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    lines = []
    try:
        from bl_ext.user_default.rigo_brace.operators.scan_ops import (  # noqa
            shade_smooth_scan,
        )
        settings = bpy.context.scene.rigo_brace
        bpy.ops.wm.stl_import(filepath=B_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.subdivide(number_cuts=1, smoothness=1.0)
        bpy.ops.object.mode_set(mode="OBJECT")
        shade_smooth_scan(obj.data)
        _paint_circle(obj, 0.45, 0.035)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 15.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        bpy.ops.object.mode_set(mode="OBJECT")
        region = obj.rigo_regions[obj.rigo_region_index]
        vg = obj.vertex_groups.get(region.surface_mask)
        n = sum(1 for v in obj.data.vertices
                if any(g.group == vg.index for g in v.groups))
        has_contact = (region.surface_mask + ".contact") in obj.data.attributes
        lines.append(f"scan={obj.name} verts={len(obj.data.vertices)} mask={region.surface_mask} "
                     f"members={n} feather={region.feather_mm} depth={region.depth_mm:.1f} "
                     f"feather_outside={getattr(region, 'feather_outside', 'absent')} "
                     f"contact_attr={has_contact}")
        bpy.ops.wm.save_as_mainfile(filepath=_BLEND, compress=True)
        lines.append(f"saved={_BLEND} size={os.path.getsize(_BLEND)}")
        lines.append("PASS=True")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
