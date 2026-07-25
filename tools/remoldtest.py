"""Functional test for the Remold (Sculpt) tools on Blender 5.0.

Gates (numeric, not just return codes):
- remold_toggle enters SCULPT mode and the unified brush size/strength equal the
  panel sliders exactly.
- remold_apply_sliders pushes changed slider values into the unified settings.
- remold_toggle again returns to OBJECT mode.
Writes remoldtest_result.txt and self-quits. GUI only.
"""

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\remoldtest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _ups(context):
    ts = context.scene.tool_settings
    ups = getattr(ts, "unified_paint_settings", None)
    if ups is None and ts.sculpt is not None:
        ups = ts.sculpt.unified_paint_settings
    return ups


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

        # ---- Toggle ON: sculpt mode + sliders applied ---- #
        settings.remold_brush_size = 77
        settings.remold_brush_strength = 0.66
        bpy.ops.rigo.remold_toggle()
        in_sculpt = bpy.context.mode == "SCULPT"
        ups = _ups(bpy.context)
        size_ok = ups is not None and ups.size == 77
        strength_ok = ups is not None and abs(ups.strength - 0.66) < 1e-6
        unified_ok = (
            ups is not None and ups.use_unified_size and ups.use_unified_strength
        )
        _mark(
            f"phase=toggle_on sculpt={in_sculpt} size={getattr(ups,'size',None)} "
            f"strength={getattr(ups,'strength',None):.3f} size_ok={size_ok} "
            f"strength_ok={strength_ok} unified_ok={unified_ok}"
        )

        # ---- Apply sliders with new values while in sculpt ---- #
        settings.remold_brush_size = 42
        settings.remold_brush_strength = 0.33
        result = bpy.ops.rigo.remold_apply_sliders()
        apply_ok = (
            "FINISHED" in result
            and ups.size == 42
            and abs(ups.strength - 0.33) < 1e-6
        )
        _mark(
            f"phase=apply_sliders ret={sorted(result)} size={ups.size} "
            f"strength={ups.strength:.3f} apply_ok={apply_ok}"
        )

        # ---- Toggle OFF: back to object mode ---- #
        bpy.ops.rigo.remold_toggle()
        back_ok = bpy.context.mode == "OBJECT"
        _mark(f"phase=toggle_off object={back_ok}")

        _mark(
            "PASS="
            f"{in_sculpt and size_ok and strength_ok and unified_ok and apply_ok and back_ok}"
        )

    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
