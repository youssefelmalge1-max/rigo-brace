"""Regression test for the LeoSpinal-style deform planes (discs + red axis).

Covers:
- the 2500 mm clamp bug: on an UNSCALED scan (hundreds of metres) the To plane
  must still initialise at the true top of the model;
- discs are filled meshes (real click targets) with semi-transparent colours,
  locked to vertical movement; red axis rides the From disc, unselectable;
- dragging a disc drives the modifier limits (drivers), geometry below the
  From disc freezes;
- swap-safety and full cleanup on reset/apply.
Writes planestest_result.txt and self-quits.
"""

import bpy

_OUT    = r"C:\Projects\Blender Add-on Braces\planestest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES  = {"n": 0}
_log    = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _ev_limits(scan):
    deps = bpy.context.evaluated_depsgraph_get()
    mod = scan.evaluated_get(deps).modifiers["Rigo Deform"]
    return mod.limits[0], mod.limits[1]


def _ev_cos(scan):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = scan.evaluated_get(deps)
    mesh = ev.to_mesh()
    cos = [v.co.copy() for v in mesh.vertices]
    ev.to_mesh_clear()
    return cos


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

        # ---- Clamp regression: UNSCALED scan (252 m tall) ---- #
        raw_top = max(v.co.z for v in scan.data.vertices)
        bpy.ops.rigo.deform_start(method="STRETCH")
        hi = bpy.data.objects.get("Rigo Upper Ring")
        unscaled_ok = hi is not None and abs(hi.location.z - raw_top) < raw_top * 0.01
        _mark(
            f"phase=unscaled raw_top={raw_top:.1f} hi_z={hi.location.z:.1f} "
            f"unscaled_ok={unscaled_ok}"
        )
        bpy.ops.rigo.deform_reset()

        # ---- Real scale from here on ---- #
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        before = [v.co.copy() for v in scan.data.vertices]
        zmin0 = min(c.z for c in before)
        sz0 = max(c.z for c in before) - zmin0
        idx_low = min(
            range(len(before)), key=lambda i: abs(before[i].z - (zmin0 + sz0 / 6))
        )
        idx_top = min(
            range(len(before)), key=lambda i: abs(before[i].z - (zmin0 + sz0 * 0.9))
        )

        # ---- Start stretch: discs + axis, LeoSpinal styling ---- #
        bpy.ops.rigo.deform_start(method="STRETCH")
        lo = bpy.data.objects.get("Rigo Lower Ring")
        mid = bpy.data.objects.get("Rigo Middle Ring")
        hi = bpy.data.objects.get("Rigo Upper Ring")
        axis = bpy.data.objects.get("Rigo Bend Axis")
        discs_ok = (
            lo is not None and mid is not None and hi is not None
            and lo.type == "MESH" and mid.type == "MESH" and hi.type == "MESH"
            and len(lo.data.polygons) >= 1          # filled disc, not a line
            and len(lo.data.vertices) >= 32
            and lo.color[3] < 0.99 and hi.color[3] < 0.99   # semi-transparent
            and abs(lo.location.z - zmin0) < 1e-4
            and abs(mid.location.z - (zmin0 + sz0 * 0.5)) < 1e-4
            and abs(hi.location.z - (zmin0 + sz0)) < 1e-4
            and lo.lock_location[0] and lo.lock_location[1]
            and not lo.lock_location[2]
        )
        axis_ok = (
            axis is not None
            and axis.parent is mid
            and axis.hide_select
            and axis.color[0] > 0.9    # red
        )
        _mark(f"phase=discs discs_ok={discs_ok} axis_ok={axis_ok}")

        # ---- Drag the From disc up a third (what the Move tool does) ---- #
        mid.location.z = zmin0 + sz0 / 3.0
        l0, l1 = _ev_limits(scan)
        drag_ok = abs(l0 - 1 / 3) < 0.01 and abs(l1 - 1.0) < 0.01
        settings.stretch_mm = 100.0
        cos = _ev_cos(scan)
        low_moved = (cos[idx_low] - before[idx_low]).length
        top_rise = cos[idx_top].z - before[idx_top].z
        geo_ok = low_moved < 1e-5 and top_rise > 0.003
        _mark(
            f"phase=drag limits=({l0:.3f},{l1:.3f}) drag_ok={drag_ok} "
            f"low_moved={low_moved:.6f} top_rise={top_rise:.4f} geo_ok={geo_ok}"
        )

        # ---- Swap-safety: From above To — limits must stay ordered ---- #
        mid.location.z = zmin0 + sz0 * 0.9
        hi.location.z = zmin0 + sz0 * 0.5
        l0, l1 = _ev_limits(scan)
        swap_ok = abs(l0 - 0.5) < 0.01 and abs(l1 - 0.9) < 0.01
        _mark(f"phase=swap limits=({l0:.3f},{l1:.3f}) swap_ok={swap_ok}")

        # ---- Reset: discs, axis, origin, drivers all gone ---- #
        bpy.ops.rigo.deform_reset()
        anim = scan.animation_data
        n_drivers = len(anim.drivers) if anim else 0
        gone = all(
            bpy.data.objects.get(n) is None
            for n in ("Rigo Lower Ring", "Rigo Middle Ring", "Rigo Upper Ring", "Rigo Bend Axis",
                      "Rigo Deform Origin")
        )
        clean_ok = gone and n_drivers == 0
        _mark(f"phase=reset drivers={n_drivers} clean_ok={clean_ok}")

        # ---- Apply path cleans up too ---- #
        bpy.ops.rigo.deform_start(method="BEND")
        settings.bend_angle = 10.0
        bpy.ops.rigo.deform_apply()
        anim = scan.animation_data
        n_drivers = len(anim.drivers) if anim else 0
        gone = all(
            bpy.data.objects.get(n) is None
            for n in ("Rigo Lower Ring", "Rigo Middle Ring", "Rigo Upper Ring", "Rigo Bend Axis",
                      "Rigo Deform Origin")
        )
        apply_ok = gone and n_drivers == 0 and scan.modifiers.get("Rigo Deform") is None
        _mark(f"phase=apply drivers={n_drivers} apply_ok={apply_ok}")

        _mark(
            "PASS="
            f"{unscaled_ok and discs_ok and axis_ok and drag_ok and geo_ok and swap_ok and clean_ok and apply_ok}"
        )

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
