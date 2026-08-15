"""#49 step 5 prep: scout region sites/amounts on the A model that commit
(refined where intended) AND keep the brace chain green.  Evidence only."""

import os
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN, _fixture_landmarks, _place  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\downstreamscout_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _import_scan():
    bpy.ops.wm.stl_import(filepath=A_SCAN)
    obj = bpy.context.active_object
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = obj
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    return obj


def _anchor(obj, which):
    cos = [obj.matrix_world @ v.co for v in obj.data.vertices]
    z_min = min(c.z for c in cos)
    z_max = max(c.z for c in cos)
    y_min, y_max = min(c.y for c in cos), max(c.y for c in cos)
    x_min, x_max = min(c.x for c in cos), max(c.x for c in cos)
    cx = (x_min + x_max) * 0.5
    dz = z_max - z_min
    dy = y_max - y_min
    targets = {
        "front_waist": (cx, y_min + 0.10 * dy, z_min + 0.45 * dz),
        "back_mid": (cx, y_max - 0.10 * dy, z_min + 0.50 * dz),
        "side_waist": (x_max - 0.05 * (x_max - x_min),
                       (y_min + y_max) * 0.5, z_min + 0.45 * dz),
        "armpit": (x_max - 0.02 * (x_max - x_min),
                   (y_min + y_max) * 0.5, z_min + 0.82 * dz),
    }
    kd = kdtree.KDTree(len(obj.data.vertices))
    for v in obj.data.vertices:
        kd.insert(obj.matrix_world @ v.co, v.index)
    kd.balance()
    from mathutils import Vector
    _co, idx, _d = kd.find(Vector(targets[which]))
    return idx


def _paint(obj, seed_vertex, count):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    seed = bm.verts[seed_vertex].link_faces[0]
    patch = {seed}
    frontier = [seed]
    while len(patch) < count and frontier:
        nxt = []
        for f in frontier:
            for e in f.edges:
                for lf in e.link_faces:
                    if lf not in patch:
                        patch.add(lf)
                        nxt.append(lf)
        frontier = nxt
    for f in patch:
        f.select = True
    bmesh.update_edit_mesh(obj.data)


def _chain(tag, obj):
    settings = bpy.context.scene.rigo_brace
    for landmark, location in _fixture_landmarks(obj).items():
        _place(settings, landmark, location)
    settings.trim_type = "A"
    settings.opening_width = 40.0
    st = bpy.ops.rigo.auto_trimline()
    if st != {"FINISHED"}:
        _mark(f"  {tag}: trimline {st}")
        return False
    settings.design_style = "CHENEAU"
    settings.corset_thickness = 4.0
    settings.corset_offset = 3.0
    settings.corset_smooth = 5
    settings.trim_top = 30.0
    settings.trim_bottom = 30.0
    t0 = time.perf_counter()
    try:
        st = bpy.ops.rigo.generate_curve_corset()
    except RuntimeError as exc:
        _mark(f"  {tag}: corset REFUSED {str(exc).strip()[:120]}")
        return False
    brace = bpy.data.objects.get("Rigo Corset")
    _mark(f"  {tag}: corset {st} dt={time.perf_counter() - t0:.1f}s "
          f"faces={0 if brace is None else len(brace.data.polygons)}")
    return st == {"FINISHED"}


def _cleanup(before):
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        if obj.name not in before:
            bpy.data.objects.remove(obj, do_unlink=True)
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)
    for cu in list(bpy.data.curves):
        if cu.users == 0:
            bpy.data.curves.remove(cu)


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    settings = bpy.context.scene.rigo_brace
    try:
        # Control: untouched A model through the chain.
        before = {o.name for o in bpy.data.objects}
        obj = _import_scan()
        _chain("control", obj)
        _cleanup(before)

        for tag, site, amount, feather in (
            ("paint_front_10_12", "front_waist", 10.0, 12.0),
            ("paint_back_10_12", "back_mid", 10.0, 12.0),
            ("paint_front_15_15", "front_waist", 15.0, 15.0),
        ):
            before = {o.name for o in bpy.data.objects}
            obj = _import_scan()
            seed = _anchor(obj, site)
            _paint(obj, seed, 240)
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = amount
            settings.region_feather = feather
            settings.region_falloff = "SMOOTH"
            bpy.ops.rigo.region_add()
            region = obj.rigo_regions[obj.rigo_region_index]
            st = bpy.ops.rigo.region_apply()
            _mark(f"{tag}: commit={st} refined={region.refined_added}")
            if st == {"FINISHED"}:
                _chain(tag, obj)
            _cleanup(before)

        # Refusal scouting: a press must hit the opposite sheet somewhere —
        # the armpit/underarm concavity is the candidate on this wide torso.
        for amount, radius, site in (
            (40.0, 25.0, "armpit"), (60.0, 18.0, "side_waist"),
            (120.0, 30.0, "side_waist"),
        ):
            before = {o.name for o in bpy.data.objects}
            obj = _import_scan()
            seed = _anchor(obj, site)
            bpy.context.scene.cursor.location = (
                obj.matrix_world @ obj.data.vertices[seed].co
            )
            settings.region_radius = radius
            settings.region_magnitude = amount
            settings.region_kind = "PRESSURE"
            settings.region_falloff = "SMOOTH"
            bpy.ops.rigo.region_add_circle()
            try:
                st = bpy.ops.rigo.region_apply()
            except RuntimeError as exc:
                st = {"CANCELLED"}
                _mark(f"refuse_{site}_{amount:.0f}_{radius:.0f}: CANCELLED "
                      f"{str(exc).strip()[:100]}")
            else:
                region = obj.rigo_regions[obj.rigo_region_index]
                _mark(f"refuse_{site}_{amount:.0f}_{radius:.0f}: {st} "
                      f"refined={region.refined_added}")
            _cleanup(before)
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
