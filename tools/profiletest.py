"""#54 Task 2 — ROUNDED transition profile (width + two corner radii, mm).

Gates:
1. evaluator maths: w(0)=0, w(f)=1, monotone, slope continuous at both
   fillet/wall junctions, discrete curvature radius at each corner within 5 %
   of the requested radius, height identity; infeasible radii are scaled down
   together and never raise.
2. Add ROUNDED (A 10, f 10, r_t 4, r_b 3): mask weights == evaluator(d);
   magnitude 14 re-evaluates the weights (they change, and match the
   evaluator at 14) — a ROUNDED weight depends on the amount.
3. `_authored_rim_field` reconstructs the live region (not None) and matches
   the mask weights (p95 <= 0.01): commit samples the profile.
4. commit: core depth within 10 % of A, nothing outside moved.
5. style save/import round-trips feather / top / bottom.
Writes profiletest_result.txt (last line PASS=True/False).  GUI only.
"""

import math
import traceback

import bpy
import bmesh
import numpy as np
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\profiletest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []
_GATES = {}
_STYLE = "QA Rounded Profile"


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _gate(name, ok, detail=""):
    _GATES[name] = bool(ok)
    _mark(f"GATE {name}={'ok' if ok else 'FAIL'} {detail}")


def _weights(obj, mask):
    vg = obj.vertex_groups.get(mask)
    gi = vg.index
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi:
                out[v.index] = g.weight
                break
    return out


def _contact(obj, mask):
    """#54 Task 7: the painted set of an outward region (None for legacy)."""
    attribute = obj.data.attributes.get(f"{mask}.contact")
    if attribute is None:
        return None
    values = np.empty(len(obj.data.vertices), dtype=bool)
    attribute.data.foreach_get("value", values)
    return values


def _distance(obj, mask):
    attr = obj.data.attributes.get(f"{mask}.dist")
    if attr is None:
        return None
    values = np.empty(len(obj.data.vertices), dtype=np.float32)
    attr.data.foreach_get("value", values)
    return values.astype(np.float64)


def _max_dw(a, b):
    if set(a) != set(b):
        return 9.9
    return max(abs(a[i] - b[i]) for i in a)


def _paint_patch(scan, seed_vertex=9000, n_faces=300):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(scan.data)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    seed = bm.verts[seed_vertex].link_faces[0]
    patch = {seed}
    frontier = [seed]
    while len(patch) < n_faces and frontier:
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
    bmesh.update_edit_mesh(scan.data)


def _check_evaluator(ro):
    """Pure maths on the profile: shape, continuity, corner radii, identity."""
    A, f, rt, rb = 15.0, 10.0, 4.0, 3.0
    theta, r_t, r_b, ev = ro._rounded_profile(A, f, rt, rb)
    d = np.linspace(0.0, f, 20001)
    w = ev(d)
    z = w * A
    ends = abs(w[0]) < 1e-12 and abs(w[-1] - 1.0) < 1e-12
    monotone = bool(np.all(np.diff(w) >= -1e-12))
    # height identity
    L = f - (r_t + r_b) * math.sin(theta)
    ident = abs((r_t + r_b) * (1 - math.cos(theta)) + L * math.tan(theta) - A)
    # slope continuity at the junctions (numeric first derivative jump)
    h = d[1] - d[0]
    dz = np.diff(z) / h
    x_b = r_b * math.sin(theta)
    x_t = f - r_t * math.sin(theta)
    def jump_at(x):
        k = int(round(x / h))
        left = dz[max(k - 6, 0):max(k - 1, 1)].mean()
        right = dz[k + 1:k + 6].mean()
        return abs(left - right)
    slope_jump = max(jump_at(x_b), jump_at(x_t))
    # discrete curvature radius in the middle of each fillet
    def radius_at(x):
        k = int(round(x / h))
        z1 = (z[k + 1] - z[k - 1]) / (2 * h)
        z2 = (z[k + 1] - 2 * z[k] + z[k - 1]) / (h * h)
        return (1 + z1 * z1) ** 1.5 / abs(z2)
    rad_b = radius_at(0.5 * x_b)
    rad_t = radius_at(x_t + 0.5 * (f - x_t))
    # infeasible radii: scaled, no exception, still a valid monotone profile
    th2, s_t, s_b, ev2 = ro._rounded_profile(15.0, 10.0, 8.0, 8.0)
    w2 = ev2(d)
    scaled_ok = (
        s_t + s_b <= 10.0 and abs(s_t / s_b - 1.0) < 1e-9
        and bool(np.all(np.diff(w2) >= -1e-12)) and abs(w2[-1] - 1.0) < 1e-12
    )
    # zero radii degenerate to a plain ramp (linear)
    th3, _t, _b, ev3 = ro._rounded_profile(15.0, 10.0, 0.0, 0.0)
    lin = np.abs(ev3(d) - d / f).max()
    _gate(
        "evaluator_maths",
        ends and monotone and ident < 1e-6 and slope_jump < 0.05
        and abs(rad_b / r_b - 1) < 0.05 and abs(rad_t / r_t - 1) < 0.05
        and scaled_ok and lin < 1e-9,
        f"theta={math.degrees(theta):.1f} ident={ident:.1e} "
        f"slope_jump={slope_jump:.3f} rad_b={rad_b:.3f}/{r_b} "
        f"rad_t={rad_t:.3f}/{r_t} scaled=({s_t:.3f},{s_b:.3f}) "
        f"theta_scaled={math.degrees(th2):.1f} lin_err={lin:.1e}",
    )
    return theta


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        import importlib
        ro = importlib.import_module("bl_ext.user_default.rigo_brace.operators.region_ops")
        _check_evaluator(ro)

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        scan_name = scan.name
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        # #54 Task 7: the band now lies on the body around the pad; on the raw
        # sample (3.7 mm edges, drawable corner 9.2 mm) a 14 mm outward
        # commit is honestly REFUSED (3 faces would tear), so the commit
        # phase runs on the once-subdivided sample like the B-scan tests.
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.subdivide(number_cuts=1, smoothness=1.0)
        bpy.ops.object.mode_set(mode="OBJECT")

        # ---- 2. Add ROUNDED ---- #
        _paint_patch(scan)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 10.0
        settings.region_feather = 10.0
        settings.region_falloff = "ROUNDED"
        settings.region_top_radius = 4.0
        settings.region_bottom_radius = 3.0
        bpy.ops.rigo.region_add()
        region = scan.rigo_regions[scan.rigo_region_index]
        mask = region.surface_mask
        w = _weights(scan, mask)
        d = _distance(scan, mask)
        contact = _contact(scan, mask)
        # #54 Task 7: pad = 1; band evaluated at x = feather - d_out (d stored
        # as -d_out), members while d_out <= feather.
        pad = np.flatnonzero(contact)
        band = np.flatnonzero(~contact & ~np.isnan(d) & (-d <= 10.0 + 1e-9))
        members = np.concatenate([pad, band])
        f_eff = 10.0
        _t, _rt, _rb, ev = ro._rounded_profile(10.0, f_eff, 4.0, 3.0)
        expect = {i: 1.0 for i in pad.tolist()}
        expect.update(zip(
            band.tolist(), np.maximum(ev(10.0 + d[band]), 1e-6).tolist(),
        ))
        dw = _max_dw(w, expect)
        _gate("add_rounded_matches_evaluator",
              region.falloff_type == "ROUNDED" and dw < 2e-6
              and abs(region.depth_mm - float(d[members].max())) < 1e-3,
              f"members={len(members)} max_dw={dw:.2e} f_eff={f_eff:.2f} "
              f"depth={region.depth_mm:.2f} readout='{ro.profile_readout(region)}'")

        region.magnitude_mm = 14.0
        w14 = _weights(scan, mask)
        _t, _rt, _rb, ev14 = ro._rounded_profile(14.0, f_eff, 4.0, 3.0)
        expect14 = {i: 1.0 for i in pad.tolist()}
        expect14.update(zip(
            band.tolist(), np.maximum(ev14(10.0 + d[band]), 1e-6).tolist(),
        ))
        dw14 = _max_dw(w14, expect14)
        modifier = scan.modifiers.get(f"RIGO_REGION_PREVIEW_{mask}")
        _gate("amount_reevaluates_rounded",
              _max_dw(w, w14) > 0.02 and dw14 < 2e-6
              and modifier is not None and abs(modifier.strength + 0.014) < 1e-9,
              f"changed={_max_dw(w, w14):.3f} max_dw={dw14:.2e}")
        region.top_radius_mm = 1.0
        w_r1 = _weights(scan, mask)
        region.top_radius_mm = 4.0
        _gate("corner_radius_live",
              _max_dw(w14, w_r1) > 0.01 and _max_dw(_weights(scan, mask), w14) <= 1e-6,
              f"changed={_max_dw(w14, w_r1):.3f}")

        # ---- 3. commit samples the profile: reconstruction validates ---- #
        group = scan.vertex_groups.get(mask)
        field = ro._authored_rim_field(scan.data, group.index, region)
        dev = []
        if field is not None:
            for i in members.tolist():
                dev.append(abs(field(scan.data.vertices[i].co) - w14[i]))
            dev.sort()
        p95 = dev[int(len(dev) * 0.95)] if dev else 9.9
        _gate("rim_field_reconstructs_rounded", field is not None and p95 <= 0.01,
              f"field={'yes' if field else 'None'} p95={p95:.4f} "
              f"max={dev[-1] if dev else 9.9:.4f}")

        # ---- 4. commit ---- #
        before = {v.index: v.co.copy() for v in scan.data.vertices}
        nverts0 = len(scan.data.vertices)
        bpy.ops.rigo.region_apply()
        scan = bpy.data.objects[scan_name]
        region = scan.rigo_regions[scan.rigo_region_index]
        core = [i for i in members.tolist() if w14[i] >= 0.999]
        core_depth = np.median([
            (scan.data.vertices[i].co - before[i]).length * 1000.0 for i in core
        ]) if core else 0.0
        outside_moved = sum(
            1 for v in scan.data.vertices
            if v.index < nverts0 and v.index not in w14
            and (v.co - before[v.index]).length > 1e-9
        )
        committed = scan.get(f"rigo_committed_{mask}", False)
        _gate("commit_rounded",
              committed and abs(core_depth - 14.0) <= 1.4 and outside_moved == 0
              and len(scan.data.vertices) == nverts0 + region.refined_added,
              f"core_depth={core_depth:.2f}mm of 14 outside_moved={outside_moved} "
              f"refined_added={region.refined_added}")

        # ---- 5. style round trip ---- #
        bpy.ops.rigo.region_style_save(style_name=_STYLE)
        settings.region_style = [
            e["id"] for e in ro.region_library.load_library()
            if e.get("label") == _STYLE
        ][0]
        entry = ro.region_library.get_entry(settings.region_style)
        bpy.context.scene.cursor.location = (
            scan.matrix_world @ scan.data.vertices[20000].co
        )
        bpy.ops.rigo.region_style_import()
        imported = scan.rigo_regions[scan.rigo_region_index]
        _gate("style_round_trip",
              entry.get("falloff") == "ROUNDED"
              and abs(float(entry.get("top_radius_mm", 0)) - 4.0) < 1e-6
              and abs(float(entry.get("bottom_radius_mm", 0)) - 3.0) < 1e-6
              and abs(float(entry.get("feather_mm", 0)) - 10.0) < 1e-6
              and imported.falloff_type == "ROUNDED"
              and abs(imported.top_radius_mm - 4.0) < 1e-6
              and abs(imported.bottom_radius_mm - 3.0) < 1e-6,
              f"entry falloff={entry.get('falloff')} imported={imported.name}")
        bpy.ops.rigo.region_style_delete()

        failed = [k for k, ok in _GATES.items() if not ok]
        _mark(f"FAILED={failed}")
        _mark(f"PASS={not failed and len(_GATES) >= 6}")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
