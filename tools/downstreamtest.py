"""#49 step 5: downstream end-to-end validation on refined committed patients.

Runs the FULL production chain on the A-type model (the brace pipeline's
patient fixture — the wrinkled paint sample scan is a REGION fixture whose
own creases fold any liner offset even untouched; measured, corsetparamdbg):

    region commit -> landmarks -> auto trimline -> curve corset generation
    -> brace QA (manifold / self-intersections / sampled wall thickness)
    -> STL export (re-runs QA, checks provenance).

Comparative-control design: the UNTOUCHED patient is run first and sets the
bar — a committed correction must never make the chain WORSE than the
untouched patient reaches (at the time of writing the untouched A model
already fails at the trim-rim stage: a PRE-EXISTING brace-generator bug,
zero regions involved, designtest red at baseline — recorded in issues.md).
The #49 acceptance gate proper is `refined_green`: at least one REFINED
patient must run fully green through export.  When the pre-existing rim bug
is fixed the control goes green and every case is then required to be green.

Cases: untouched control · no-op circle commit · refined painted commit
(clean zone, 15/15) · second refined painted commit (back, 15/15) ·
refusal (the sample scan's hostile armpit paint — the proven opposite-wall
refusal — must refuse, leave the scan untouched, and reach at least the
stage the untouched sample scan reaches; its own control runs first).

Writes downstreamtest_result.txt (PASS=True/False) then quits.  GUI only.
"""

import os
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bracefixture import A_SCAN, _fixture_landmarks, _place  # noqa: E402

_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"

_OUT = r"C:\Projects\Blender Add-on Braces\downstreamtest_result.txt"
_STL = r"C:\Projects\Blender Add-on Braces\_downstreamtest_%s.stl"
_TRIES = {"n": 0}
_log = []
_fails = []

# Chain stages, in order; a case's score is the last stage it completed.
_STAGES = ("commit", "trimline", "corset", "qa", "export")


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _gate(name, ok, detail=""):
    if not ok:
        _fails.append(name)
    _mark(f"GATE {name}={'ok' if ok else 'FAIL'} {detail}")


def _import_scan(path=A_SCAN):
    bpy.ops.wm.stl_import(filepath=path)
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
    dz, dy = z_max - z_min, y_max - y_min
    targets = {
        "front_waist": (cx, y_min + 0.10 * dy, z_min + 0.45 * dz),
        "back_mid": (cx, y_max - 0.10 * dy, z_min + 0.50 * dz),
    }
    kd = kdtree.KDTree(len(obj.data.vertices))
    for v in obj.data.vertices:
        kd.insert(obj.matrix_world @ v.co, v.index)
    kd.balance()
    _co, idx, _d = kd.find(Vector(targets[which]))
    return idx


def _paint_patch(obj, seed_vertex, count, seed_face=None):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    if seed_face is not None:
        bm.faces.ensure_lookup_table()
        seed = bm.faces[seed_face]
    else:
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


def _topo_sig(me):
    return (len(me.vertices), len(me.edges), len(me.polygons))


def _downstream(tag, scan, qa_ops):
    """Landmarks -> trimline -> corset -> QA -> export.  Returns the index
    of the last completed stage (see _STAGES; 'commit' is stage 0 and is
    scored by the caller)."""
    settings = bpy.context.scene.rigo_brace
    for landmark, location in _fixture_landmarks(scan).items():
        _place(settings, landmark, location)
    settings.trim_type = "A"
    settings.opening_width = 40.0
    st = bpy.ops.rigo.auto_trimline()
    _mark(f"[{tag}] trimline={st}")
    if st != {"FINISHED"}:
        return 0
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
        _mark(f"[{tag}] corset REFUSED {str(exc).strip()[:140]}")
        return 1
    dt = time.perf_counter() - t0
    brace = bpy.data.objects.get("Rigo Corset")
    faces = 0 if brace is None else len(brace.data.polygons)
    _mark(f"[{tag}] corset={st} dt={dt:.1f}s faces={faces}")
    if st != {"FINISHED"} or brace is None or faces <= 100:
        return 1
    report = qa_ops.evaluate_brace_qa(bpy.context, brace)
    _mark(
        f"[{tag}] qa passed={report['passed']} "
        f"boundary={report.get('boundary_edges')} "
        f"nonman={report.get('nonmanifold_edges')} "
        f"selfx={report.get('self_intersections')} "
        f"min_wall={report.get('min_thickness_mm', 0.0):.2f}mm "
        f"coverage={report.get('thickness_coverage', 0.0):.2f} "
        f"reasons={report.get('reasons')}"
    )
    if not report["passed"]:
        return 2
    stl = _STL % tag
    if os.path.exists(stl):
        os.remove(stl)
    try:
        st = bpy.ops.rigo.export_brace(filepath=stl)
    except RuntimeError as exc:
        _mark(f"[{tag}] export REFUSED {str(exc).strip()[:140]}")
        return 3
    written = os.path.isfile(stl) and os.path.getsize(stl) > 0
    qa_pass = bool(brace.get("rigo_qa_pass", False))
    _mark(f"[{tag}] export={st} written={written} qa_pass={qa_pass}")
    if os.path.exists(stl):
        os.remove(stl)
    return 4 if (st == {"FINISHED"} and written and qa_pass) else 3


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
    import importlib
    qa_ops = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.qa_ops"
    )
    settings = bpy.context.scene.rigo_brace
    stages = {}

    def _safe(name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _mark(f"[{name}] CASE ERROR={exc!r}\n{traceback.format_exc()}")
            _gate(f"{name}.completed", False, "exception")

    def control():
        before = {o.name for o in bpy.data.objects}
        obj = _import_scan()
        stages["control"] = _downstream("control", obj, qa_ops)
        _mark(f"[control] reached stage "
              f"{_STAGES[stages['control']]} ({stages['control']}/4)")
        _cleanup(before)

    def noop_circle():
        before = {o.name for o in bpy.data.objects}
        obj = _import_scan()
        me = obj.data
        bpy.context.scene.cursor.location = (
            obj.matrix_world @ me.vertices[_anchor(obj, "front_waist")].co
        )
        settings.region_radius = 30.0
        settings.region_magnitude = 15.0
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        region = obj.rigo_regions[obj.rigo_region_index]
        st = bpy.ops.rigo.region_apply()
        _gate("noop_circle.commit", st == {"FINISHED"}, f"returned {st}")
        _gate("noop_circle.noop", region.refined_added == 0,
              f"refined_added={region.refined_added}")
        stages["noop_circle"] = _downstream("noop_circle", obj, qa_ops)
        _gate("noop_circle.not_worse",
              stages["noop_circle"] >= stages.get("control", 0),
              f"reached {stages['noop_circle']} vs control "
              f"{stages.get('control', 0)}")
        _cleanup(before)

    def refined_paint(tag, site, gate_green):
        before = {o.name for o in bpy.data.objects}
        obj = _import_scan()
        _paint_patch(obj, _anchor(obj, site), 240)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 15.0
        settings.region_feather = 15.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        region = obj.rigo_regions[obj.rigo_region_index]
        st = bpy.ops.rigo.region_apply()
        _gate(f"{tag}.commit", st == {"FINISHED"}, f"returned {st}")
        _gate(f"{tag}.refined", region.refined_added > 0,
              f"refined_added={region.refined_added} "
              f"edge={region.refined_edge_mm:.1f}mm")
        stages[tag] = _downstream(tag, obj, qa_ops)
        if gate_green:
            # THE #49 acceptance: a refined patient fully green to export.
            _gate(f"{tag}.refined_green", stages[tag] == 4,
                  f"reached {_STAGES[stages[tag]]} ({stages[tag]}/4)")
        else:
            _gate(f"{tag}.not_worse",
                  stages[tag] >= stages.get("control", 0),
                  f"reached {stages[tag]} vs control "
                  f"{stages.get('control', 0)}")
        _cleanup(before)

    def sample_control():
        before = {o.name for o in bpy.data.objects}
        obj = _import_scan(_SAMPLE)
        stages["sample_control"] = _downstream("sample_control", obj, qa_ops)
        _mark(f"[sample_control] reached stage "
              f"{_STAGES[stages['sample_control']]} "
              f"({stages['sample_control']}/4)")
        _cleanup(before)

    def refusal():
        # The PROVEN refusal fixture: the sample scan's hostile armpit paint
        # presses through the opposite body surface (regionqualtest
        # paint15_hostile).  Refusal must leave the patient EXACTLY as
        # brace-able as before — compared against sample_control.
        before = {o.name for o in bpy.data.objects}
        obj = _import_scan(_SAMPLE)
        sig0 = _topo_sig(obj.data)
        _paint_patch(obj, None, 300, seed_face=5000)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 15.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        try:
            st = bpy.ops.rigo.region_apply()
        except RuntimeError:
            st = {"CANCELLED"}
        _gate("refusal.refused", st == {"CANCELLED"}, f"returned {st}")
        _gate("refusal.untouched", _topo_sig(obj.data) == sig0,
              f"{sig0} -> {_topo_sig(obj.data)}")
        stages["refusal"] = _downstream("refusal", obj, qa_ops)
        _gate("refusal.not_worse",
              stages["refusal"] >= stages.get("sample_control", 0),
              f"reached {stages['refusal']} vs sample_control "
              f"{stages.get('sample_control', 0)}")
        _cleanup(before)

    try:
        t_all = time.perf_counter()
        _safe("control", control)
        _safe("noop_circle", noop_circle)
        _safe("refined_paint",
              lambda: refined_paint("refined_paint", "front_waist", True))
        _safe("refined_paint_b",
              lambda: refined_paint("refined_paint_b", "back_mid", False))
        _safe("sample_control", sample_control)
        _safe("refusal", refusal)
        _mark(f"total_time={time.perf_counter() - t_all:.1f}s")
        _mark(f"stages={stages}")
        _mark(f"failed_gates={_fails}")
        _mark(f"PASS={not _fails}")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
        _mark("PASS=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
