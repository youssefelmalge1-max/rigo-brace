"""Subdivision Surface before a library pressure: does it smooth the wall?

Runs the orthotist's chain once per Blender process (import -> units ->
optional SUBSURF apply -> paint circle -> live region -> commit) and writes a
close-up render plus wall metrics.  RIGO_SUBDIV=0|1|2 picks the Catmull-Clark
level applied to the scan BEFORE painting (0 = production, no subdivision).

Outputs (project root):
  subdivshot_L<levels>_solid.png   studio-lit close-up of the committed pad
  subdivshot_L<levels>_wire.png    same camera with wireframe overlay
  subdivshot_L<levels>.txt         face counts, timings, wall dihedral spectrum
"""

import math
import os
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN, B_SCAN  # noqa: E402

LEVELS = int(os.environ.get("RIGO_SUBDIV", "0"))
MODE = os.environ.get("RIGO_SUBDIV_MODE", "editsub")  # editsub | subsurf
PROFILE = os.environ.get("RIGO_PROFILE", "0") == "1"  # cProfile the commit
SCAN = os.environ.get("RIGO_SCAN", "A")  # A | B fixture scan
AMOUNT_MM = float(os.environ.get("RIGO_AMOUNT", "15"))
FEATHER_MM = float(os.environ.get("RIGO_FEATHER", "10"))
ROOT = r"C:\Projects\Blender Add-on Braces"
TAG = (
    f"subdivshot_{SCAN}_L{LEVELS}" + ("" if LEVELS == 0 else f"_{MODE}")
    + f"_a{AMOUNT_MM:g}_f{FEATHER_MM:g}"
)
PATCH_R = 0.045
TRIES = {"n": 0}
LOG = []


def _log(msg):
    LOG.append(msg)
    print("[subdivshot]", msg)


def _spectrum(values):
    if not values:
        return "n=0"
    values = sorted(values)

    def p(q):
        return values[min(len(values) - 1, int(q * len(values)))]

    over30 = sum(1 for v in values if v > 30.0)
    return (
        f"n={len(values)} p50={p(0.5):.2f} p95={p(0.95):.2f} "
        f"max={values[-1]:.2f} >30deg={over30}"
    )


def _wall(me, weights):
    """Dihedral spectrum of the transition band (what the eye reads)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    angles = []
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        if len(e.link_faces) != 2:
            continue
        try:
            angles.append(abs(math.degrees(e.calc_face_angle_signed())))
        except ValueError:
            angles.append(180.0)
    bm.free()
    return _spectrum(angles)


def _speck_census(me, weights):
    """Cheap discriminators for dark specks on a smooth-shaded wall: sharp-
    flagged edges inside the band (set_sharp_from_angle leftovers), zero-area
    faces, and faces whose normal disagrees with every neighbour by >90 deg
    (a flip)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    band_edges = 0
    sharp_band = 0
    for e in bm.edges:
        a, b = e.verts[0].index, e.verts[1].index
        if weights.get(a, 0.0) > 0.0 or weights.get(b, 0.0) > 0.0:
            band_edges += 1
            if not e.smooth:
                sharp_band += 1
    zero_area = 0
    flipped = 0
    for f in bm.faces:
        if not any(weights.get(v.index, 0.0) > 0.0 for v in f.verts):
            continue
        if f.calc_area() < 1e-10:
            zero_area += 1
            continue
        nbrs = [g for e in f.edges for g in e.link_faces if g is not f]
        if nbrs and all(f.normal.dot(g.normal) < 0.0 for g in nbrs):
            flipped += 1
    bm.free()
    return (f"specks: band_edges={band_edges} sharp_flagged={sharp_band} "
            f"zero_area_faces={zero_area} flipped_faces={flipped}")


def _style(space, wire):
    shading = space.shading
    shading.type = "SOLID"
    shading.light = "STUDIO"
    shading.color_type = "SINGLE"
    shading.single_color = (0.80, 0.83, 0.88)
    shading.show_xray = False
    # The template strips overlays; the wire shot needs them back on.
    space.overlay.show_overlays = wire
    space.overlay.show_wireframes = wire
    space.overlay.wireframe_threshold = 1.0
    space.overlay.wireframe_opacity = 1.0
    for flag in ("show_floor", "show_axis_x", "show_axis_y", "show_cursor",
                 "show_object_origins", "show_relationship_lines",
                 "show_outline_selected"):
        setattr(space.overlay, flag, False)


def _shoot(centre_world, normal_world):
    area = next(a for a in bpy.context.screen.areas if a.type == "VIEW_3D")
    space = area.spaces.active
    region = next(r for r in area.regions if r.type == "WINDOW")
    # Look at the pad from outside along its surface normal, slightly
    # raised so the wall reads as relief and not a flat disc.
    look = (-normal_world).normalized()
    up = Vector((0.0, 0.0, 1.0))
    if abs(look.dot(up)) > 0.9:
        up = Vector((0.0, 1.0, 0.0))
    look = (look + up * 0.35).normalized()
    quat = look.to_track_quat("-Z", "Y")
    for wire in (False, True):
        _style(space, wire)
        name = "wire" if wire else "solid"
        with bpy.context.temp_override(area=area, region=region):
            rv3d = space.region_3d
            rv3d.view_perspective = "PERSP"
            rv3d.view_rotation = quat
            rv3d.view_location = centre_world
            rv3d.view_distance = 0.16
            rv3d.update()
            bpy.context.scene.render.resolution_x = 1400
            bpy.context.scene.render.resolution_y = 1000
            bpy.context.scene.render.resolution_percentage = 100
            bpy.context.scene.render.filepath = os.path.join(
                ROOT, f"{TAG}_{name}.png"
            )
            bpy.ops.render.opengl(write_still=True)


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 60:
        return 0.25
    from bl_ext.user_default.rigo_brace.operators.scan_ops import (  # noqa
        shade_smooth_scan,
    )
    settings = bpy.context.scene.rigo_brace
    try:
        bpy.ops.wm.stl_import(filepath=B_SCAN if SCAN == "B" else A_SCAN)
        obj = bpy.context.active_object
        settings.scan_object = obj
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        me = obj.data
        _log(f"import: verts={len(me.vertices)} faces={len(me.polygons)}")

        if LEVELS > 0:
            t0 = time.perf_counter()
            if MODE == "subsurf":
                # Blender 5.0.1's SUBSURF modifier dies with a C++ exception
                # in deg_evaluate_on_refresh on ANY mesh above ~22k faces
                # here (ico sphere too, headless, no add-on) - kept as an
                # arm so the crash stays reproducible, not the default.
                mod = obj.modifiers.new("Subdiv", "SUBSURF")
                mod.levels = LEVELS
                bpy.ops.object.modifier_apply(modifier=mod.name)
            else:
                # Edit-mode Subdivide with smoothness=1: each triangle splits
                # into four with the new vertices lifted onto a curved
                # interpolant, no OpenSubdiv evaluator involved.
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.mesh.subdivide(number_cuts=LEVELS, smoothness=1.0)
                bpy.ops.object.mode_set(mode="OBJECT")
            me = obj.data
            shade_smooth_scan(me)
            _log(
                f"{MODE} L{LEVELS} applied in {time.perf_counter() - t0:.2f}s: "
                f"verts={len(me.vertices)} faces={len(me.polygons)}"
            )

        # Same anatomical target every arm: mid-height, front-ish, centred.
        mw = obj.matrix_world
        cos = [mw @ v.co for v in me.vertices]
        lo = Vector((min(c.x for c in cos), min(c.y for c in cos), min(c.z for c in cos)))
        hi = Vector((max(c.x for c in cos), max(c.y for c in cos), max(c.z for c in cos)))
        kd = kdtree.KDTree(len(me.vertices))
        for v in me.vertices:
            kd.insert(mw @ v.co, v.index)
        kd.balance()
        target = Vector((
            (lo.x + hi.x) * 0.5,
            lo.y + 0.10 * (hi.y - lo.y),
            lo.z + 0.45 * (hi.z - lo.z),
        ))
        _co, seed, _d = kd.find(target)
        centre_local = me.vertices[seed].co.copy()
        centre_world = mw @ centre_local
        normal_world = (mw.to_3x3() @ me.vertices[seed].normal).normalized()

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        painted = 0
        for f in bm.faces:
            if (f.calc_center_median() - centre_local).length < PATCH_R:
                f.select = True
                painted += 1
        bmesh.update_edit_mesh(me)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = AMOUNT_MM
        settings.region_feather = FEATHER_MM
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        region = obj.rigo_regions[obj.rigo_region_index]
        group = obj.vertex_groups.get(region.surface_mask)
        bpy.ops.object.mode_set(mode="OBJECT")
        _log(f"painted {painted} faces -> live region {region.name}")

        t0 = time.perf_counter()
        if PROFILE:
            import cProfile
            import pstats
            prof = cProfile.Profile()
            prof.enable()
            result = bpy.ops.rigo.region_apply()
            prof.disable()
            with open(os.path.join(ROOT, f"{TAG}_profile.txt"), "w",
                      encoding="utf-8") as fh:
                st = pstats.Stats(prof, stream=fh)
                st.sort_stats("tottime").print_stats(45)
                st.sort_stats("cumulative").print_stats(45)
        else:
            result = bpy.ops.rigo.region_apply()
        me = obj.data
        weights = {}
        for v in me.vertices:
            for g in v.groups:
                if g.group == group.index:
                    weights[v.index] = g.weight
                    break
        _log(
            f"commit {result} in {time.perf_counter() - t0:.2f}s: "
            f"refined_added={region.refined_added} verts={len(me.vertices)} "
            f"faces={len(me.polygons)}"
        )
        _log(f"wall {_wall(me, weights)}")
        _log(_speck_census(me, weights))

        for other in bpy.context.scene.objects:
            other.hide_set(other is not obj)
        _shoot(centre_world, normal_world)
        _log("shots written")
    except Exception as error:  # noqa: BLE001
        _log(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(os.path.join(ROOT, f"{TAG}.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG) + "\n")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
