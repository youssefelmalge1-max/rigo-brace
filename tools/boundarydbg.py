"""#49g: does rounding the painted OUTLINE before authoring actually help?

Part 1 - the small-patch regression: the 4-row feather ramp swallowed small
painted areas whole, so Smooth Area cancelled and did nothing.  Measured
across patch sizes, on a FRESH scan each time (no prior commit moving the
surface away from the probe's anchor).

Part 2 - Round Edge: a circle brush paints whole triangles, so a painted
border is ragged at the face scale.  Measures the outline itself (its length,
its one-face spikes and notches, the area it encloses) before and after.

Part 3 - the payoff: identical patch, identical amount and feather, committed
WITH and WITHOUT the rounding step, compared on the transition wall.  This is
the same discriminator used in #49e - only one thing differs between arms.

Evidence only.
"""

import importlib
import math
import os
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\boundarydbg_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _fresh(settings):
    bpy.ops.wm.stl_import(filepath=A_SCAN)
    obj = bpy.context.active_object
    settings.scan_object = obj
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    me = obj.data
    cos = [obj.matrix_world @ v.co for v in me.vertices]
    z_min, z_max = min(c.z for c in cos), max(c.z for c in cos)
    y_min, y_max = min(c.y for c in cos), max(c.y for c in cos)
    x_min, x_max = min(c.x for c in cos), max(c.x for c in cos)
    kd = kdtree.KDTree(len(me.vertices))
    for v in me.vertices:
        kd.insert(obj.matrix_world @ v.co, v.index)
    kd.balance()
    _co, seed, _d = kd.find(Vector((
        (x_min + x_max) * 0.5,
        y_min + 0.10 * (y_max - y_min),
        z_min + 0.45 * (z_max - z_min),
    )))
    return obj, me.vertices[seed].co.copy()


def _paint(obj, centre, radius_mm):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    n = 0
    for f in bm.faces:
        if (f.calc_center_median() - centre).length < radius_mm * 0.001:
            f.select = True
            n += 1
    bmesh.update_edit_mesh(obj.data)
    return n


def _outline(obj):
    """Length of the painted border, the area it encloses, and the one-face
    spikes/notches that make it ragged."""
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    selected = {f.index for f in bm.faces if f.select}
    length = 0.0
    for e in bm.edges:
        faces = e.link_faces
        if len(faces) == 2 and (faces[0].index in selected) != (
            faces[1].index in selected
        ):
            length += e.calc_length()
    area = sum(bm.faces[i].calc_area() for i in selected)
    spikes = notches = 0
    for f in bm.faces:
        near = [
            o.index for e in f.edges for o in e.link_faces if o is not f
        ]
        agree = sum(1 for n in near if n in selected)
        if f.index in selected and agree <= 1:
            spikes += 1
        if f.index not in selected and agree >= 2:
            notches += 1
    # LOCAL raggedness: mean absolute turning angle along the boundary
    # polyline.  A global length/area ratio cannot see this — a geodesic
    # patch on a curved torso is not a flat disc, so that ratio carries a
    # large constant offset that swamps the effect.
    loop = {}
    for e in bm.edges:
        faces = e.link_faces
        if len(faces) == 2 and (faces[0].index in selected) != (
            faces[1].index in selected
        ):
            a, b = e.verts[0], e.verts[1]
            loop.setdefault(a.index, []).append(b.index)
            loop.setdefault(b.index, []).append(a.index)
    turns = []
    for index, near in loop.items():
        if len(near) != 2:
            continue
        here = bm.verts[index].co
        first = (bm.verts[near[0]].co - here)
        second = (bm.verts[near[1]].co - here)
        if first.length < 1e-9 or second.length < 1e-9:
            continue
        cosine = max(-1.0, min(1.0, first.normalized().dot(
            second.normalized()
        )))
        turns.append(180.0 - math.degrees(math.acos(cosine)))
    turns.sort()
    mean_turn = sum(turns) / len(turns) if turns else 0.0
    hard = sum(1 for t in turns if t > 60.0)
    return (
        f"faces={len(selected)} outline={length*1000:.0f}mm "
        f"area={area*1e6:.0f}mm2 turn_mean={mean_turn:.1f}deg "
        f"p95={turns[int(len(turns)*0.95)] if turns else 0.0:.1f} "
        f"corners>60deg={hard} spikes={spikes} notches={notches}"
    )


def _wall(me, weights):
    bm = bmesh.new()
    bm.from_mesh(me)
    angles = []
    ridges = 0
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        if len(e.link_faces) != 2:
            continue
        try:
            signed = math.degrees(e.calc_face_angle_signed())
        except ValueError:
            signed = 180.0
        angles.append(abs(signed))
        if signed > 10.0:
            ridges += 1
    bm.free()
    if not angles:
        return "wall n=0"
    angles.sort()
    return (
        f"wall n={len(angles)} mean={sum(angles)/len(angles):.1f} "
        f"p95={angles[int(len(angles)*0.95)]:.1f} max={angles[-1]:.1f} "
        f">30deg={sum(1 for a in angles if a > 30.0)} ridges={ridges}"
    )


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.select_ops"
    )
    settings = bpy.context.scene.rigo_brace
    settings.select_smooth_factor = 0.5
    settings.select_smooth_iters = 5
    settings.select_boundary_smooth_mm = 6.0
    try:
        # ---- PART 1: small-patch regression ----
        _mark("PART 1 - Smooth Area across patch sizes (fresh scan each time)")
        for radius_mm in (10.0, 15.0, 25.0, 40.0, 60.0):
            obj, centre = _fresh(settings)
            n = _paint(obj, centre, radius_mm)
            me = obj.data
            bpy.ops.object.mode_set(mode="OBJECT")
            before = [v.co.copy() for v in me.vertices]
            bpy.ops.object.mode_set(mode="EDIT")
            st = bpy.ops.rigo.smooth_selection()
            bpy.ops.object.mode_set(mode="OBJECT")
            moved = max(
                (obj.data.vertices[i].co - before[i]).length
                for i in range(len(before))
            ) * 1000.0
            _mark(
                f"  r={radius_mm:>4.0f}mm faces={n:>5} -> {st} "
                f"max_move={moved:.3f}mm"
            )
            bpy.data.objects.remove(obj, do_unlink=True)

        # ---- PART 2: the outline itself ----
        _mark("")
        _mark("PART 2 - the painted outline, before and after Round Edge")
        obj, centre = _fresh(settings)
        _paint(obj, centre, 59.0)
        _mark(f"  brush-painted : {_outline(obj)}")
        for mm in (4.0, 6.0, 10.0):
            settings.select_boundary_smooth_mm = mm
            _paint(obj, centre, 59.0)
            bpy.ops.rigo.smooth_boundary()
            _mark(f"  Round Edge {mm:>4.0f}mm: {_outline(obj)}")
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.data.objects.remove(obj, do_unlink=True)

        # ---- PART 3: does it improve the committed correction? ----
        _mark("")
        _mark("PART 3 - same patch, same 20mm/15mm press, committed with and "
              "without the rounding step")
        settings.select_boundary_smooth_mm = 6.0
        for arm in ("raw outline", "rounded outline"):
            obj, centre = _fresh(settings)
            _paint(obj, centre, 59.0)
            if arm == "rounded outline":
                bpy.ops.rigo.smooth_boundary()
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 20.0
            settings.region_feather = 15.0
            settings.region_falloff = "SMOOTH"
            bpy.ops.rigo.region_add()
            region = obj.rigo_regions[obj.rigo_region_index]
            group = obj.vertex_groups.get(region.surface_mask)
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.rigo.region_apply()
            me = obj.data
            weights = {}
            for v in me.vertices:
                for g in v.groups:
                    if g.group == group.index:
                        weights[v.index] = g.weight
                        break
            _mark(
                f"  [{arm}] refined_added={region.refined_added} "
                f"{_wall(me, weights)}"
            )
            bpy.data.objects.remove(obj, do_unlink=True)
        _mark("")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
