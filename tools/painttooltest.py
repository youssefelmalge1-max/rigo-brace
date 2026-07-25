"""Regression test: Paint Area must arm the circle-select tool in ADD mode.

Blender's circle select defaults to "Set" mode which replaces the selection on
every new drag — wiping the region painted so far.  After rigo.paint_select the
active EDIT_MESH tool must be builtin.select_circle with mode == 'ADD'.
Writes painttooltest_result.txt and self-quits.
"""

import bpy

_OUT    = r"C:\Projects\Blender Add-on Braces\painttooltest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES  = {"n": 0}
_log    = []


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
        bpy.context.scene.rigo_brace.scan_object = scan
        bpy.context.view_layer.objects.active = scan

        bpy.ops.rigo.paint_select()
        _mark(f"phase=paint mode={bpy.context.mode}")

        tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "EDIT_MESH", create=False
        )
        tool_id = tool.idname if tool is not None else None
        tool_ok = tool_id == "builtin.select_circle"
        mode = None
        if tool_ok:
            mode = tool.operator_properties("view3d.select_circle").mode
        mode_ok = mode == "ADD"
        _mark(f"phase=tool idname={tool_id} mode={mode}")

        _mark(f"PASS={tool_ok and mode_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
