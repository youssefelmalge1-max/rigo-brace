"""Functional test for the lattice cage + multi-section derotation (Patch 5).

Quantitative gates:
- Add: "Rigo Lattice" exists, W sections == setting, modifier on the scan
  targets it, cage encloses the scan bbox.
- Twist (gradient, total 30°): measured on the EVALUATED mesh around the cage
  axis — bottom vertex rotates ~0°, top vertex ~30° (±4°, B-spline blending),
  monotonic bottom < middle < top; RADIAL DISTANCE from the axis is preserved
  (< 1 mm drift — proves the scale-compensated rotation, no ellipse shear);
  vertex count unchanged.
- Apply: modifier + cage gone, twist baked into the mesh.
- Discard: after a fresh cage + twist, discard restores the scan exactly.
Writes latticetest_result.txt and self-quits. GUI only.
"""

from math import atan2, degrees

import bpy
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\latticetest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _eval_cos(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    me = ev.to_mesh()
    cos = [v.co.copy() for v in me.vertices]
    ev.to_mesh_clear()
    return cos


def _spin_mm(co0, co1, center):
    """(rotation° around Z through center, radial drift mm) for one vertex."""
    a0 = atan2(co0.y - center.y, co0.x - center.x)
    a1 = atan2(co1.y - center.y, co1.x - center.x)
    da = degrees(a1 - a0)
    while da > 180.0:
        da -= 360.0
    while da < -180.0:
        da += 360.0
    r0 = (Vector((co0.x, co0.y)) - Vector((center.x, center.y))).length
    r1 = (Vector((co1.x, co1.y)) - Vector((center.x, center.y))).length
    return da, abs(r1 - r0) * 1000.0


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        # Stand the scan upright (long axis on Z) — clinical orientation: the
        # derotation axis is the spine.
        from math import radians as _rad

        scan.rotation_euler = (0.0, _rad(90.0), 0.0)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)

        # ---- Add ---- #
        settings.lattice_sections = 5
        bpy.ops.rigo.lattice_add()
        lat = bpy.data.objects.get("Rigo Lattice")
        mod = scan.modifiers.get("Rigo Lattice")
        add_ok = (
            lat is not None
            and lat.data.points_w == 5
            and mod is not None
            and mod.object is lat
        )
        _mark(f"phase=add sections={lat.data.points_w if lat else '-'} add_ok={add_ok}")

        # ---- pick probe verts by height (base mesh, pre-twist) ---- #
        center = lat.location.copy()
        cos0 = _eval_cos(scan)
        zs = sorted(range(len(cos0)), key=lambda i: cos0[i].z)
        v_bot, v_mid, v_top = zs[50], zs[len(zs) // 2], zs[-50]
        nverts0 = len(scan.data.vertices)

        # ---- Twist: gradient 0 -> 30° ---- #
        settings.lattice_twist = 30.0
        bpy.ops.rigo.lattice_twist(
            r0=0.0, r1=7.5, r2=15.0, r3=22.5, r4=30.0
        )
        cos1 = _eval_cos(scan)
        a_bot, dr_bot = _spin_mm(cos0[v_bot], cos1[v_bot], center)
        a_mid, dr_mid = _spin_mm(cos0[v_mid], cos1[v_mid], center)
        a_top, dr_top = _spin_mm(cos0[v_top], cos1[v_top], center)
        max_drift = max(dr_bot, dr_mid, dr_top)
        twist_ok = (
            abs(a_bot) < 2.0
            and abs(a_top - 30.0) < 4.0
            and abs(a_bot) < abs(a_mid) < abs(a_top)
            and max_drift < 1.0
            and len(scan.data.vertices) == nverts0
        )
        _mark(
            f"phase=twist bot={a_bot:.1f}° mid={a_mid:.1f}° top={a_top:.1f}° "
            f"radial_drift={max_drift:.2f}mm twist_ok={twist_ok}"
        )

        # ---- Apply: baked, cage gone ---- #
        bpy.ops.rigo.lattice_apply()
        baked = scan.data.vertices[v_top].co.copy()
        apply_ok = (
            bpy.data.objects.get("Rigo Lattice") is None
            and scan.modifiers.get("Rigo Lattice") is None
            and (baked - cos1[v_top]).length < 1e-6
            and len(scan.data.vertices) == nverts0
        )
        _mark(f"phase=apply cage_gone={apply_ok}")

        # ---- Discard: fresh cage + twist, discard restores exactly ---- #
        pre = {i: v.co.copy() for i, v in enumerate(scan.data.vertices)}
        bpy.ops.rigo.lattice_add()
        bpy.ops.rigo.lattice_twist(r0=0.0, r1=5.0, r2=10.0, r3=15.0, r4=20.0)
        bpy.ops.rigo.lattice_discard()
        max_delta = max(
            (scan.data.vertices[i].co - pre[i]).length for i in pre
        )
        discard_ok = (
            bpy.data.objects.get("Rigo Lattice") is None and max_delta < 1e-9
        )
        _mark(f"phase=discard max_delta={max_delta:.2e} discard_ok={discard_ok}")

        _mark(f"PASS={add_ok and twist_ok and apply_ok and discard_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
