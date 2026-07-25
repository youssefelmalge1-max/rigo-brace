"""Functional test for trim-edge finishing (Patch 6).

The paired shell has no open boundary. Generate marks its explicit rim and rebuilds
the feathered ``RIGO_TRIM_BAND`` after final topology cleanup.

Gates:
- Generate: RIGO_TRIM_BAND group exists with members.
- Smooth Trim Edge: total area of band faces DECREASES (stair-steps relax);
  vertex count unchanged; the vertex farthest from the band does not move.
- Flare Edge (6 mm): verts with weight >= 0.999 move radially outward by
  6 mm (+-0.1), z unchanged; far vertex frozen.
- See-Through: viewport show_xray toggles on and off.
Writes trimtest_result.txt and self-quits. GUI only.
"""

import os
import sys

import bpy
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import prepare_a_design  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\trimtest_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _band_weights(obj):
    vg = obj.vertex_groups.get("RIGO_TRIM_BAND")
    if vg is None:
        return {}
    gi = vg.index
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi and g.weight > 0.0:
                out[v.index] = g.weight
                break
    return out


def _band_area(obj, weighted):
    """Total area of faces fully inside the band (all verts weighted)."""
    total = 0.0
    for p in obj.data.polygons:
        if all(i in weighted for i in p.vertices):
            total += p.area
    return total


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        scan, settings = prepare_a_design()
        bpy.context.view_layer.objects.active = scan

        settings.edge_band = 15.0
        bpy.ops.rigo.generate_curve_corset()
        corset = bpy.data.objects.get("Rigo Corset")
        weights = _band_weights(corset)
        band_ok = len(weights) > 100
        _mark(f"phase=band members={len(weights)} band_ok={band_ok}")

        # far probe vertex: weight-0 vert farthest from any weighted vert
        me = corset.data
        tree = kdtree.KDTree(len(weights))
        for i in weights:
            tree.insert(me.vertices[i].co, i)
        tree.balance()
        far_i, far_d = None, -1.0
        for v in me.vertices:
            if v.index in weights:
                continue
            _co, _i, d = tree.find(v.co)
            if d is not None and d > far_d:
                far_d, far_i = d, v.index
        far_before = me.vertices[far_i].co.copy()
        nverts0 = len(me.vertices)

        # ---- Smooth Trim Edge ---- #
        area0 = _band_area(corset, weights)
        settings.trim_smooth_iters = 50
        bpy.ops.rigo.smooth_trim_edge()
        me = corset.data
        area1 = _band_area(corset, weights)
        far_after = me.vertices[far_i].co.copy()
        smooth_ok = (
            area1 < area0
            and len(me.vertices) == nverts0
            and (far_after - far_before).length < 1e-9
        )
        _mark(
            f"phase=smooth band_area={area0:.6f}->{area1:.6f} "
            f"far_moved={(far_after - far_before).length:.2e} smooth_ok={smooth_ok}"
        )

        # ---- Flare Edge: 6 mm radial at weight-1 verts, XY only ---- #
        xs = [v.co.x for v in me.vertices]
        ys = [v.co.y for v in me.vertices]
        cx = (min(xs) + max(xs)) * 0.5
        cy = (min(ys) + max(ys)) * 0.5
        rim = {i: w for i, w in weights.items() if w >= 0.999}
        before = {
            i: (
                me.vertices[i].co.z,
                Vector((me.vertices[i].co.x - cx, me.vertices[i].co.y - cy)).length,
            )
            for i in rim
        }
        far_before2 = me.vertices[far_i].co.copy()

        settings.edge_flare = 6.0
        bpy.ops.rigo.flare_edge()
        me = corset.data
        max_err = 0.0
        max_dz = 0.0
        for i, (z0, r0) in before.items():
            v = me.vertices[i]
            r1 = Vector((v.co.x - cx, v.co.y - cy)).length
            max_err = max(max_err, abs((r1 - r0) * 1000.0 - 6.0))
            max_dz = max(max_dz, abs(v.co.z - z0))
        far_after2 = me.vertices[far_i].co.copy()
        flare_ok = (
            len(rim) > 10
            and max_err < 0.1
            and max_dz < 1e-9
            and (far_after2 - far_before2).length < 1e-9
            and len(me.vertices) == nverts0
        )
        _mark(
            f"phase=flare rim={len(rim)} radial_err={max_err:.3f}mm "
            f"dz={max_dz:.2e} flare_ok={flare_ok}"
        )

        # ---- See-Through toggle ---- #
        def _xray_state():
            return any(
                sp.shading.show_xray
                for a in bpy.context.screen.areas
                for sp in a.spaces
                if sp.type == "VIEW_3D"
            )

        s0 = _xray_state()
        bpy.ops.rigo.toggle_seethrough()
        s1 = _xray_state()
        bpy.ops.rigo.toggle_seethrough()
        s2 = _xray_state()
        xray_ok = s1 != s0 and s2 == s0
        _mark(f"phase=seethrough {s0}->{s1}->{s2} xray_ok={xray_ok}")

        _mark(f"PASS={band_ok and smooth_ok and flare_ok and xray_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
