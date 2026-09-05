"""Time and profile every finishing operation on a real 4 mm brace.

Generates the reference brace once, snapshots its mesh, then runs each
finishing operator on a fresh copy of that snapshot so the timings are
independent:  cut_slots, cut_rivets, emboss_text, vent_grid,
build_lattice_pattern.

For each: wall-clock, the time spent inside Blender's own boolean
(modifier_apply -> not reachable from Python), and the hottest add-on
functions by SELF time.

Writes finishtimedbg_result.txt.  GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/finishtimedbg.py
"""

import cProfile
import io
import os
import pstats
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import kdtree

_PREFIX = os.path.join(
    os.environ["APPDATA"], "Blender Foundation", "Blender", "5.0",
    "extensions", "user_default", "rigo_brace") + os.sep

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bracefixture  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\finishtimedbg_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _mod(name):
    import importlib
    return importlib.import_module(f"bl_ext.user_default.rigo_brace.operators.{name}")


def _largest_component_faces(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    seen = set()
    best = set()
    for start in bm.faces:
        if start in seen:
            continue
        comp = {start}
        stack = [start]
        seen.add(start)
        while stack:
            f = stack.pop()
            for e in f.edges:
                for lf in e.link_faces:
                    if lf not in seen:
                        seen.add(lf)
                        comp.add(lf)
                        stack.append(lf)
        if len(comp) > len(best):
            best = comp
    out = {f.index for f in best}
    bm.free()
    return out


def _rim_distance(brace):
    """Callable: face -> distance to the nearest RIGO_RIM_BOUNDARY vertex."""
    group = brace.vertex_groups.get("RIGO_RIM_BOUNDARY")
    rim = []
    if group is not None:
        for v in brace.data.vertices:
            if any(g.group == group.index and g.weight > 0.5 for g in v.groups):
                rim.append(v.co.copy())
    tree = kdtree.KDTree(len(rim))
    for i, co in enumerate(rim):
        tree.insert(co, i)
    tree.balance()
    if not rim:
        return lambda p: 1.0
    return lambda p: tree.find(p.center)[2]


def _pick_face(brace, main, predicate, key):
    mesh = brace.data
    zs = [v.co.z for v in mesh.vertices]
    z_mid = (min(zs) + max(zs)) * 0.5
    span = max(zs) - min(zs)
    cands = [p for p in mesh.polygons
             if p.index in main and abs(p.center.z - z_mid) < span * 0.12
             and predicate(p)]
    p = max(cands, key=key)
    return p.center.copy(), p.normal.copy()


def _paint_patch(brace, side_key, count=400):
    bpy.ops.object.select_all(action="DESELECT")
    brace.select_set(True)
    bpy.context.view_layer.objects.active = brace
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(brace.data)
    bm.faces.ensure_lookup_table()
    zs = [f.calc_center_median().z for f in bm.faces]
    z_mid = (max(zs) + min(zs)) * 0.5
    seed = max((f for f in bm.faces if abs(f.calc_center_median().z - z_mid) < 0.05),
               key=side_key)
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
    bm.select_flush_mode()
    bmesh.update_edit_mesh(brace.data)


def _timed(label, fn):
    prof = cProfile.Profile()
    t0 = time.perf_counter()
    prof.enable()
    try:
        result = fn()
    except RuntimeError as exc:
        result = f"FAILED {str(exc).strip()[:160]}"
    finally:
        prof.disable()
    wall = time.perf_counter() - t0
    st = pstats.Stats(prof)
    boolean = 0.0
    for (_file, _line, name), (_cc, _nc, _tt, ct, _callers) in st.stats.items():
        # every bpy.ops.* call (the boolean, mode switches, ...) funnels
        # through bpy/ops.py _op_call -> its cumulative time is Blender C.
        if name == "_op_call":
            boolean += ct
    _mark("")
    _mark(f"### {label}: result={result} WALL={wall:.2f}s  "
          f"blender_boolean(modifier_apply cum)={boolean:.2f}s  "
          f"python_reachable={wall - boolean:.2f}s")
    buf = io.StringIO()
    st2 = pstats.Stats(prof, stream=buf)
    st2.sort_stats("tottime").print_stats("rigo_brace", 12)
    for line in buf.getvalue().splitlines():
        if "rigo_brace" in line or line.strip().startswith("ncalls"):
            _mark("  " + line.replace(_PREFIX, ""))
    buf = io.StringIO()
    st3 = pstats.Stats(prof, stream=buf)
    st3.sort_stats("cumtime").print_stats("rigo_brace", 10)
    _mark("  -- cumulative --")
    for line in buf.getvalue().splitlines():
        if "rigo_brace" in line:
            _mark("  " + line.replace(_PREFIX, ""))
    return wall, boolean


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    try:
        do = _mod("design_ops")
        ro = _mod("rivet_ops")
        ctx = bpy.context
        scan, settings = bracefixture.prepare_reference_design()
        settings.corset_thickness = 4.0
        t0 = time.perf_counter()
        gen = bpy.ops.rigo.generate_curve_corset()
        _mark(f"generate 4mm -> {gen} {time.perf_counter() - t0:.2f}s")
        brace = bpy.data.objects["Rigo Corset"]
        _mark(f"brace faces={len(brace.data.polygons)} verts={len(brace.data.vertices)}")
        snapshot = brace.data.copy()
        snapshot.name = "Rigo Snapshot"
        main = _largest_component_faces(brace.data)
        rim_dist = _rim_distance(brace)
        summary = []

        def restore():
            if ctx.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            old = brace.data
            brace.data = snapshot.copy()
            if old.users == 0:
                bpy.data.meshes.remove(old)
            bpy.ops.object.select_all(action="DESELECT")
            brace.select_set(True)
            ctx.view_layer.objects.active = brace
            settings.brace_dirty = False
            brace["rigo_brace_dirty"] = False

        # 1. strap slot (lateral, like slotbracetest)
        loc, nrm = _pick_face(brace, main, lambda p: p.normal.x > 0.55,
                              lambda p: p.center.x)
        settings.slot_width, settings.slot_height = 30.0, 10.0
        settings.slot_edge_radius, settings.symmetrical = 0.6, False
        do._new_slot_marker(ctx, do._SlotPlacement(
            "SLOT_T", brace.matrix_world @ loc,
            (brace.matrix_world.to_3x3() @ nrm).normalized(), 30.0, 10.0))
        summary.append(("cut_slots (1 slot)",) + _timed(
            "cut_slots", lambda: bpy.ops.rigo.cut_slots()))
        _mark(f"  status={brace.get('rigo_slot_status')}")
        restore()

        # 2. rivet hole (anterior)
        loc, nrm = _pick_face(brace, main, lambda p: p.normal.y < -0.65,
                              rim_dist)
        settings.rivet_diameter, settings.rivet_edge_radius = 4.0, 0.35
        ro._new_rivet_marker(ctx, "RIVET_T", brace.matrix_world @ loc,
                             (brace.matrix_world.to_3x3() @ nrm).normalized(), 4.0)
        summary.append(("cut_rivets (1 hole)",) + _timed(
            "cut_rivets", lambda: bpy.ops.rigo.cut_rivets()))
        _mark(f"  status={brace.get('rigo_rivet_status')}")
        restore()

        # 3. emboss (anterior, raised)
        loc, nrm = _pick_face(brace, main, lambda p: p.normal.y < -0.65,
                              rim_dist)
        settings.emboss_text, settings.emboss_depth = "RIGO", 1.0
        settings.emboss_size, settings.emboss_mode = 12.0, "RAISED"
        do._new_emboss_preview(ctx, brace, "RIGO", loc, nrm, 12.0)
        summary.append(("emboss_text RIGO raised",) + _timed(
            "emboss_text", lambda: bpy.ops.rigo.emboss_text()))
        restore()

        # 4. ventilation grid (back patch, 6 / 15 mm)
        _paint_patch(brace, lambda f: f.calc_center_median().y)
        settings.vent_diameter, settings.vent_spacing = 6.0, 15.0
        summary.append(("vent_grid (400-face patch)",) + _timed(
            "vent_grid", lambda: bpy.ops.rigo.vent_grid()))
        restore()

        # 5. lattice CUT diamond (back patch)
        _paint_patch(brace, lambda f: f.calc_center_median().y)
        settings.lattice_finish_mode, settings.lattice_pattern = "CUT", "DIAMOND"
        settings.lattice_cell_size, settings.lattice_bar_width = 18.0, 4.0
        settings.lattice_height = 1.2
        summary.append(("build_lattice_pattern CUT diamond",) + _timed(
            "build_lattice_pattern", lambda: bpy.ops.rigo.build_lattice_pattern()))
        _mark(f"  cells={brace.get('rigo_lattice_cells')}")
        restore()

        _mark("")
        _mark("=== SUMMARY (seconds) ===")
        _mark(f"{'operation':36s} {'wall':>7s} {'blender bool':>13s} {'python':>8s}")
        for name, wall, boolean in summary:
            _mark(f"{name:36s} {wall:7.2f} {boolean:13.2f} {wall - boolean:8.2f}")
        _mark("(blender = cumulative time inside every bpy.ops call: the boolean, "
              "mode switches; python = everything the add-on itself runs)")
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


if __name__ == "__main__":  # finishequivdbg imports the pickers
    bpy.app.timers.register(_run, first_interval=0.5)
