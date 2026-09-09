"""#54 Task 1 — editable transition foundation (feather / falloff live).

A live region keeps its CONTINUOUS definition (surface distance from the
painted outline, `<mask>.dist` point attribute) and the vertex-group weights
are re-evaluated from it whenever the orthotist edits the region's own
Feather or Falloff — no repaint, no Update button.  Gates:

1. Add stores the distance; members == mask members.
2. feather 10 -> 20 via the property equals a fresh Edit Selection -> Update
   Preview at 20 (|dw| <= 1e-6); back to 10 restores the original weights.
3. falloff LINEAR via the property equals a fresh LINEAR Update.
4. The live preview follows the re-evaluated weights (-n * A * w, < 0.05 mm)
   and Amount edits move the modifier strength without any operator.
5. Circle: stored feather == radius, re-evaluation reproduces its weights;
   feather 15 gives falloff(min(d, 15) / 15).
6. Committed region: editing feather changes neither weights nor mesh.
7. Undo after a feather edit restores the previous weights (logged; gated).
Writes feathertest_result.txt (last line PASS=True/False).  GUI only:
  & blender.exe --app-template rigo_brace --python tools\\feathertest.py
"""

import traceback

import bpy
import bmesh
import numpy as np
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\feathertest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []
_GATES = {}


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
    return values


def _max_dw(a, b):
    if set(a) != set(b):
        return 9.9
    return max(abs(a[i] - b[i]) for i in a)


def _evaluated_coords(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    return {v.index: v.co.copy() for v in evaluated.data.vertices}


def _falloff(t, kind):
    if kind == "LINEAR":
        return t
    if kind == "SHARP":
        return t * t
    return t * t * (3.0 - 2.0 * t)


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


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()

        # ---- 1. Add with feather 10 SMOOTH ---- #
        _paint_patch(scan)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 10.0
        settings.region_feather = 10.0
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
        region = scan.rigo_regions[scan.rigo_region_index]
        mask = region.surface_mask
        w10 = _weights(scan, mask)
        d = _distance(scan, mask)
        contact = _contact(scan, mask)
        # #54 Task 7: paint = the pad (w = 1); the band is stored as -d_out
        # and is a member while d_out <= feather.
        pad = set(np.flatnonzero(contact).tolist()) if contact is not None else set()
        band = (
            set(np.flatnonzero(
                ~contact & ~np.isnan(d) & (-d <= 10.0 + 1e-9)
            ).tolist())
            if d is not None and contact is not None else set()
        )
        members = pad | band
        _gate(
            "add_stores_distance",
            d is not None and contact is not None and members == set(w10)
            and abs(region.feather_mm - 10.0) < 1e-6
            and region.falloff_type == "SMOOTH" and region.feather_outside,
            f"pad={len(pad)} band={len(band)} mask={len(w10)} feather={region.feather_mm}",
        )
        # The stored distance IS the definition: pad 1, band falloff((f - d_out)/f)
        f_eff = 10.0
        expect = {i: 1.0 for i in pad}
        expect.update({
            i: max(_falloff(min(max((10.0 + float(d[i])) / 10.0, 0.0), 1.0), "SMOOTH"), 1e-6)
            for i in band
        })
        _gate("weights_match_definition", _max_dw(w10, expect) < 2e-6,
              f"max_dw={_max_dw(w10, expect):.2e} f_eff={f_eff:.3f}")

        # ---- 2. feather 20 live == fresh Update at 20 ---- #
        region.feather_mm = 20.0
        w20_live = _weights(scan, mask)
        changed = _max_dw(w10, w20_live)
        bpy.ops.rigo.region_edit()
        bpy.ops.rigo.region_update()
        w20_fresh = _weights(scan, mask)
        dw = _max_dw(w20_live, w20_fresh)
        _gate("feather_live_equals_update", dw <= 1e-6 and changed > 0.05,
              f"max_dw={dw:.2e} moved_from_f10={changed:.3f} "
              f"feather_after_update={region.feather_mm}")
        region.feather_mm = 10.0
        back = _max_dw(_weights(scan, mask), w10)
        _gate("feather_back_restores", back <= 1e-6, f"max_dw={back:.2e}")

        # ---- 3. falloff live == fresh Update ---- #
        region.falloff_type = "LINEAR"
        lin_live = _weights(scan, mask)
        bpy.ops.rigo.region_edit()
        bpy.ops.rigo.region_update()
        lin_fresh = _weights(scan, mask)
        dw = _max_dw(lin_live, lin_fresh)
        _gate("falloff_live_equals_update",
              dw <= 1e-6 and _max_dw(lin_live, w10) > 0.05,
              f"max_dw={dw:.2e} type_after_update={region.falloff_type}")
        region.falloff_type = "SMOOTH"

        # ---- 4. preview follows the live weights; Amount is live ---- #
        region.feather_mm = 20.0
        w_now = _weights(scan, mask)
        base = {v.index: v.co.copy() for v in scan.data.vertices}
        normals = {v.index: v.normal.copy() for v in scan.data.vertices}
        preview = _evaluated_coords(scan)
        max_err = 0.0
        for i, co in preview.items():
            expected = -normals[i] * 0.010 * w_now.get(i, 0.0)
            max_err = max(max_err, ((co - base[i]) - expected).length * 1000.0)
        _gate("preview_follows_live_weights", max_err < 0.05,
              f"max_err={max_err:.4f}mm")
        region.magnitude_mm = 12.0
        modifier = scan.modifiers.get(f"RIGO_REGION_PREVIEW_{mask}")
        _gate("amount_live", modifier is not None
              and abs(modifier.strength + 0.012) < 1e-9,
              f"strength={modifier.strength if modifier else None}")
        region.magnitude_mm = 10.0

        # ---- 7. undo restores the previous weights ---- #
        region.feather_mm = 10.0
        w_before_undo = _weights(scan, mask)
        scan_name = scan.name
        bpy.ops.ed.undo_push(message="feathertest checkpoint")
        region.feather_mm = 25.0
        w_after_edit = _weights(scan, mask)
        # A script-side property edit pushes no step of its own (the UI does
        # that after every slider release) — push one so undo lands on the
        # checkpoint, exactly as it would for the orthotist.
        bpy.ops.ed.undo_push(message="feathertest edit")
        bpy.ops.ed.undo()
        # Undo rebuilds the ID structs: every RNA reference is stale now.
        scan = bpy.data.objects[scan_name]
        settings = bpy.context.scene.rigo_brace
        region = scan.rigo_regions[scan.rigo_region_index]
        w_after_undo = _weights(scan, mask)
        _gate("undo_restores_weights",
              _max_dw(w_after_edit, w_before_undo) > 0.05
              and _max_dw(w_after_undo, w_before_undo) <= 1e-6,
              f"edited_dw={_max_dw(w_after_edit, w_before_undo):.3f} "
              f"undo_dw={_max_dw(w_after_undo, w_before_undo):.2e} "
              f"feather_after_undo={region.feather_mm}")

        # ---- 6. committed region ignores feather edits ---- #
        bpy.ops.rigo.region_apply()
        scan = bpy.data.objects[scan_name]
        region = scan.rigo_regions[scan.rigo_region_index]
        wc = _weights(scan, mask)
        coords_c = {v.index: v.co.copy() for v in scan.data.vertices}
        region.feather_mm = 5.0
        region.falloff_type = "SHARP"
        moved = max(
            (v.co - coords_c[v.index]).length for v in scan.data.vertices
        )
        _gate("committed_frozen",
              _max_dw(_weights(scan, mask), wc) == 0.0 and moved == 0.0
              and _distance(scan, mask) is None
              and scan.modifiers.get(f"RIGO_REGION_PREVIEW_{mask}") is None,
              f"moved={moved:.2e} dist_dropped={_distance(scan, mask) is None}")

        # ---- 5. circle: feather == radius, re-evaluation is exact ---- #
        seed_idx = 20000
        bpy.context.scene.cursor.location = (
            scan.matrix_world @ scan.data.vertices[seed_idx].co
        )
        settings.region_radius = 30.0
        settings.region_kind = "EXPANSION"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        circ = scan.rigo_regions[scan.rigo_region_index]
        cw = _weights(scan, circ.surface_mask)
        cd = _distance(scan, circ.surface_mask)
        circ.feather_mm = 30.0  # same value: must reproduce exactly
        cw_same = _weights(scan, circ.surface_mask)
        circ.feather_mm = 15.0
        cw15 = _weights(scan, circ.surface_mask)
        expect15 = {
            i: max(_falloff(min(float(cd[i]), 15.0) / 15.0, "SMOOTH"), 1e-6)
            for i in cw
        }
        _gate("circle_reevaluates",
              cd is not None and abs(circ.feather_mm - 15.0) < 1e-6
              and _max_dw(cw, cw_same) <= 1e-6
              and _max_dw(cw15, expect15) <= 2e-6
              and abs(cw.get(seed_idx, 0.0) - 1.0) < 1e-6
              and _max_dw(cw, cw15) > 0.05,
              f"members={len(cw)} same_dw={_max_dw(cw, cw_same):.2e} "
              f"dw15={_max_dw(cw15, expect15):.2e} seed_w={cw.get(seed_idx)}")

        # ---- remove drops the attribute ---- #
        bpy.ops.rigo.region_remove()
        _gate("remove_drops_distance",
              _distance(scan, circ.surface_mask) is None
              and scan.vertex_groups.get(circ.surface_mask) is None)

        failed = [k for k, ok in _GATES.items() if not ok]
        _mark(f"FAILED={failed}")
        _mark(f"PASS={not failed and len(_GATES) >= 10}")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
