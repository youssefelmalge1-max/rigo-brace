"""Functional test for the X-ray overlay transforms + lock-to-model (Patch 4b).

Gates:
- import_xray (with a generated PNG): creates the "Rigo X-ray" IMAGE empty,
  coronal orientation, opacity applied.
- xray_transform execute path selects the overlay (modal drag is GUI-only).
- xray_lock: parents the overlay to the scan WITHOUT visual jump (world matrix
  preserved, < 1e-6 m); moving the scan then carries the overlay by exactly the
  same delta; unlock keeps the world transform and clears the parent.
Writes xraytest_result.txt and self-quits. GUI only.
"""

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\xraytest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_PNG = r"C:\Projects\Blender Add-on Braces\xraytest_image.png"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


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

        # ---- generate a small radiograph stand-in PNG ---- #
        img = bpy.data.images.new("xray_stub", width=64, height=64)
        img.filepath_raw = _PNG
        img.file_format = "PNG"
        img.save()

        # ---- import ---- #
        settings.xray_opacity = 0.42
        bpy.ops.rigo.import_xray(filepath=_PNG)
        xray = bpy.data.objects.get("Rigo X-ray")
        import_ok = (
            xray is not None
            and xray.empty_display_type == "IMAGE"
            and abs(xray.color[3] - 0.42) < 1e-6
            and abs(xray.rotation_euler.x - 1.5708) < 1e-4
        )
        _mark(f"phase=import ok={import_ok}")

        # ---- transform execute path selects the overlay ---- #
        result = bpy.ops.rigo.xray_transform(mode="MOVE")
        select_ok = (
            "FINISHED" in result
            and bpy.context.view_layer.objects.active is xray
            and xray.select_set is not None
        )
        _mark(f"phase=transform select_ok={select_ok}")

        # ---- lock: no jump, then follows the model exactly ---- #
        before = xray.matrix_world.copy()
        bpy.ops.rigo.xray_lock()
        jump = max(
            abs(before[i][j] - xray.matrix_world[i][j])
            for i in range(4)
            for j in range(4)
        )
        locked_ok = xray.parent is scan and jump < 1e-6

        pos0 = xray.matrix_world.translation.copy()
        scan.location.x += 0.123
        bpy.context.view_layer.update()
        moved = xray.matrix_world.translation - pos0
        follow_ok = (
            abs(moved.x - 0.123) < 1e-6
            and abs(moved.y) < 1e-6
            and abs(moved.z) < 1e-6
        )
        _mark(
            f"phase=lock jump={jump:.2e} locked_ok={locked_ok} "
            f"follow_dx={moved.x:.4f} follow_ok={follow_ok}"
        )

        # ---- unlock: parent cleared, world transform kept ---- #
        before = xray.matrix_world.copy()
        bpy.ops.rigo.xray_lock()
        jump2 = max(
            abs(before[i][j] - xray.matrix_world[i][j])
            for i in range(4)
            for j in range(4)
        )
        unlock_ok = xray.parent is None and jump2 < 1e-6
        _mark(f"phase=unlock jump={jump2:.2e} unlock_ok={unlock_ok}")

        _mark(
            f"PASS={import_ok and select_ok and locked_ok and follow_ok and unlock_ok}"
        )

    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
