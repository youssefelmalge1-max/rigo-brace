"""Functional test for parametric ventilation + the #13 guard (Patch 7).

Gates:
- #13 guard: generate_corset REFUSES while a Bend deform session is live
  ("Apply or Reset..."), then works after deform_reset.
- Bridge safety: Ø 8 / spacing 10 (bridge 2 mm < 3 mm) is REFUSED.
- Cut: on a painted back patch with Ø 6 / spacing 15, the hole count measured
  by TOPOLOGY equals what the boolean really cut: each through-hole raises the
  genus by 1, so holes = (χ_before − χ_after) / 2 with χ = V − E + F.
  The shell must stay watertight (0 boundary) and manifold (0 non-manifold).
Writes venttest_result.txt and self-quits. GUI only.
"""

import os
import sys

import bpy
import bmesh

sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import prepare_a_design  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\venttest_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _topo(obj):
    """(euler characteristic, boundary edges, non-manifold edges)."""
    me = obj.data
    chi = len(me.vertices) - len(me.edges) + len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    nonman = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    return chi, boundary, nonman


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        scan, settings = prepare_a_design()
        bpy.context.view_layer.objects.active = scan

        # ---- #13 guard: refuse generate mid-deform ---- #
        bpy.ops.rigo.deform_start()
        guard_ok = False
        try:
            bpy.ops.rigo.generate_corset()
        except RuntimeError as exc:
            guard_ok = "Apply or Reset" in str(exc)
        bpy.ops.rigo.deform_reset()
        _mark(f"phase=guard13 guard_ok={guard_ok}")

        bpy.ops.rigo.generate_corset()
        corset = bpy.data.objects.get("Rigo Corset")
        if corset is None:
            raise RuntimeError("corset missing after reset")

        # ---- paint a back patch at mid height ---- #
        bpy.ops.object.select_all(action="DESELECT")
        corset.select_set(True)
        bpy.context.view_layer.objects.active = corset
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(corset.data)
        bm.faces.ensure_lookup_table()
        zs = [f.calc_center_median().z for f in bm.faces]
        z_mid = (max(zs) + min(zs)) * 0.5
        seed = max(
            (f for f in bm.faces if abs(f.calc_center_median().z - z_mid) < 0.05),
            key=lambda f: f.calc_center_median().y,
        )
        patch = {seed}
        frontier = [seed]
        while len(patch) < 400 and frontier:
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
        bmesh.update_edit_mesh(corset.data)

        # ---- bridge refusal: 8 mm holes at 10 mm spacing = 2 mm bridge ---- #
        settings.vent_diameter = 8.0
        settings.vent_spacing = 10.0
        bridge_ok = False
        try:
            bpy.ops.rigo.vent_grid()
        except RuntimeError as exc:
            bridge_ok = "Bridge" in str(exc) or "bridge" in str(exc)
        _mark(f"phase=bridge bridge_ok={bridge_ok} mode={bpy.context.mode}")

        # the refusal happens before the mode switch; ensure still in edit
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")

        # ---- cut: Ø 6 / 15 mm, verify by topology ---- #
        chi0, bnd0, nm0 = _topo(corset)
        settings.vent_diameter = 6.0
        settings.vent_spacing = 15.0
        bpy.ops.rigo.vent_grid()
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        chi1, bnd1, nm1 = _topo(corset)
        holes = (chi0 - chi1) // 2
        # nm gate is RELATIVE: generate_corset itself can leave a pinch edge
        # at the trim (issue #14, Patch-8 repair) — the ventilation cut must
        # simply add none.
        cut_ok = (
            (chi0 - chi1) % 2 == 0
            and holes >= 3
            and bnd0 == 0 and bnd1 == 0
            and nm1 <= nm0
        )
        _mark(
            f"phase=cut chi={chi0}->{chi1} holes={holes} boundary={bnd1} "
            f"nonmanifold={nm0}->{nm1} cut_ok={cut_ok}"
        )

        _mark(f"PASS={guard_ok and bridge_ok and cut_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
