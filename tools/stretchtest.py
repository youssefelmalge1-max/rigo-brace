"""Regression test for Stretch + the three draggable deform rings.

Bugs covered:
- Stretch must lengthen along Z ONLY (it used to taper the body in X/Y).
- Localized modes keep geometry outside both active rings fixed.
- From/To planes (mm) must map to modifier limits, park the origin on the
  From plane, and freeze everything below it — for Stretch AND Bend.
Writes stretchtest_result.txt and self-quits.
"""

import bpy

_OUT    = r"C:\Projects\Blender Add-on Braces\stretchtest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES  = {"n": 0}
_log    = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _evaluated(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mesh = ev.to_mesh()
    cos = [v.co.copy() for v in mesh.vertices]
    ev.to_mesh_clear()
    return cos


def _spans(cos):
    xs = [c.x for c in cos]
    ys = [c.y for c in cos]
    zs = [c.z for c in cos]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), min(zs))


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

        before = [v.co.copy() for v in scan.data.vertices]
        sx0, sy0, sz0, zmin0 = _spans(before)
        # A probe vertex in the bottom sixth (below the From plane later).
        idx_low = min(
            range(len(before)), key=lambda i: abs(before[i].z - (zmin0 + sz0 / 6))
        )
        _mark(f"phase=imported spans=({sx0:.3f},{sy0:.3f},{sz0:.3f})")

        # ---- Stretch, full body: Z-only growth, base planted ---- #
        bpy.ops.rigo.deform_start(method="STRETCH")
        bpy.ops.rigo.deform_segment(segment="FULL")
        mod = scan.modifiers.get("Rigo Deform")
        locks_ok = (
            mod is not None
            and mod.deform_axis == "Z"
            and mod.lock_x
            and mod.lock_y
        )
        settings.stretch_mm = 100.0
        sx, sy, sz, zmin = _spans(_evaluated(scan))
        zonly_ok = (
            sz > sz0 + 0.003
            and abs(sx - sx0) < 0.001
            and abs(sy - sy0) < 0.001
        )
        _mark(
            f"phase=stretch locks_ok={locks_ok} spans=({sx:.3f},{sy:.3f},{sz:.3f}) "
            f"zmin_drift={abs(zmin - zmin0):.5f} zonly_ok={zonly_ok}"
        )

        # ---- Middle/Upper ring pair: limits + origin + frozen bottom ---- #
        bpy.data.objects["Rigo Middle Ring"].location.z = zmin0 + sz0 / 3.0
        bpy.data.objects["Rigo Upper Ring"].location.z = zmin0 + sz0 * 2.0 / 3.0
        bpy.ops.rigo.deform_segment(segment="UPPER")
        deps = bpy.context.evaluated_depsgraph_get()
        mod_ev = scan.evaluated_get(deps).modifiers["Rigo Deform"]
        lim_ok = (
            abs(mod_ev.limits[0] - 1 / 3) < 0.01
            and abs(mod_ev.limits[1] - 2 / 3) < 0.01
        )
        origin = bpy.data.objects.get("Rigo Deform Origin")
        org_ok = origin is not None and abs(
            origin.evaluated_get(deps).location.z - (zmin0 + sz0 / 3.0)
        ) < 1e-4
        cos = _evaluated(scan)
        low_moved = (cos[idx_low] - before[idx_low]).length
        frozen_ok = low_moved < 1e-5
        _mark(
            f"phase=range limits=({mod.limits[0]:.3f},{mod.limits[1]:.3f}) "
            f"lim_ok={lim_ok} org_ok={org_ok} low_moved={low_moved:.6f} "
            f"frozen_ok={frozen_ok}"
        )
        bpy.ops.rigo.deform_reset()

        # ---- Bend between the planes: top tips, bottom frozen ---- #
        bpy.ops.rigo.deform_start(method="BEND")
        bpy.data.objects["Rigo Middle Ring"].location.z = zmin0 + sz0 / 3.0
        bpy.data.objects["Rigo Upper Ring"].location.z = zmin0 + sz0 * 2.0 / 3.0
        bpy.ops.rigo.deform_segment(segment="UPPER")
        settings.bend_angle = 25.0
        cos = _evaluated(scan)
        idx_top = max(range(len(before)), key=lambda i: before[i].z)
        tip = abs(cos[idx_top].x - before[idx_top].x)
        low_moved = (cos[idx_low] - before[idx_low]).length
        bendrange_ok = tip > sz0 * 0.03 and low_moved < 1e-3
        _mark(
            f"phase=bendrange tip={tip:.4f} low_moved={low_moved:.6f} "
            f"bendrange_ok={bendrange_ok}"
        )
        bpy.ops.rigo.deform_reset()
        reset_ok = scan.modifiers.get("Rigo Deform") is None

        _mark(
            f"PASS={locks_ok and zonly_ok and lim_ok and org_ok and frozen_ok and bendrange_ok and reset_ok}"
        )

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
