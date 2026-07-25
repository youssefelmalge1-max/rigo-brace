"""Functional test for Apply Units (rigo.apply_units).

Covers the "model disappears" bug: scaling mm -> m must re-frame the viewport
onto the now-small model, a second apply must be refused (double-shrink guard),
and "m" must be a no-op.  Writes applyunitstest_result.txt and self-quits.
"""

import bpy

_OUT    = r"C:\Projects\Blender Add-on Braces\applyunitstest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES  = {"n": 0}
_log    = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _view_distance():
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            return area.spaces.active.region_3d.view_distance
    return None


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        bpy.context.scene.rigo_brace.scan_object = scan
        h_before = scan.dimensions.z
        _mark(f"phase=imported height={h_before:.1f}")

        # ---- mm -> m: must scale 0.001x and zoom the view onto the model ---- #
        bpy.context.scene.rigo_brace.scan_units = "mm"
        result = bpy.ops.rigo.apply_units()
        h_after = scan.dimensions.z
        dist = _view_distance()
        scaled_ok = abs(h_after - h_before * 0.001) < 1e-4
        # After view_selected the camera distance must be near the ~0.6 m model,
        # not the hundreds of units it was framed at before.
        framed_ok = dist is not None and dist < 10.0
        _mark(
            f"phase=applied result={result} height={h_after:.4f} "
            f"view_distance={dist:.2f} scaled_ok={scaled_ok} framed_ok={framed_ok}"
        )

        # ---- second apply: guard must refuse the double shrink ---- #
        result2 = bpy.ops.rigo.apply_units()
        h_guard = scan.dimensions.z
        guard_ok = result2 == {"CANCELLED"} and abs(h_guard - h_after) < 1e-6
        _mark(f"phase=guard result={result2} height={h_guard:.4f} guard_ok={guard_ok}")

        # ---- metres: explicit no-op, must still FINISH ---- #
        bpy.context.scene.rigo_brace.scan_units = "m"
        result3 = bpy.ops.rigo.apply_units()
        noop_ok = result3 == {"FINISHED"} and abs(scan.dimensions.z - h_after) < 1e-6
        _mark(f"phase=metres result={result3} noop_ok={noop_ok}")

        _mark(f"PASS={scaled_ok and framed_ok and guard_ok and noop_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
