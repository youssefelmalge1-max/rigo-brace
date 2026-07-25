"""Functional test for the View module (Req 2 + Req 6).

Asserts the new view operators register and actually run against the GUI 3D
viewport: fixed view angles, quad-view toggle on/off, full-screen toggle on/off,
and align-in-quad. Writes viewtest_result.txt and self-quits. GUI only.
"""

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\viewtest_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _quad_on():
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            return bool(area.spaces.active.region_quadviews)
    return False


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")
        ops = bpy.ops.rigo

        reg_ok = all(
            hasattr(ops, n)
            for n in ("view_axis", "toggle_quadview", "toggle_fullscreen", "align_quad")
        ) and hasattr(bpy.types, "RIGO_PT_view")
        _mark(f"phase=register reg_ok={reg_ok}")

        # ---- fixed view angles all run ---- #
        axis_ok = True
        for axis in ("TOP", "FRONT", "LEFT", "RIGHT", "BACK", "BOTTOM"):
            r = bpy.ops.rigo.view_axis(axis=axis)
            if r != {"FINISHED"}:
                axis_ok = False
        _mark(f"phase=view_axis axis_ok={axis_ok}")

        # ---- quad view: off -> on -> off ---- #
        start_quad = _quad_on()
        bpy.ops.rigo.toggle_quadview()
        mid_quad = _quad_on()
        bpy.ops.rigo.toggle_quadview()
        end_quad = _quad_on()
        quad_ok = (mid_quad != start_quad) and (end_quad == start_quad)
        _mark(f"phase=quad start={start_quad} mid={mid_quad} end={end_quad} quad_ok={quad_ok}")

        # ---- align_quad: ensures quad on + rotate tool ---- #
        r = bpy.ops.rigo.align_quad()
        align_ok = r == {"FINISHED"} and _quad_on()
        _mark(f"phase=align align_ok={align_ok}")
        # turn quad back off to leave a clean state for fullscreen test
        if _quad_on():
            bpy.ops.rigo.toggle_quadview()

        # ---- focused view: Rigo sidebar/stage bar remain visible while native
        # viewport chrome hides, and every prior state restores on exit ---- #
        area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
        space = area.spaces.active
        start_state = (
            space.show_region_header,
            space.show_region_tool_header,
            space.show_region_toolbar,
            space.show_region_ui,
        )
        r1 = bpy.ops.rigo.toggle_fullscreen()
        focus_state = (
            space.show_region_header,
            space.show_region_tool_header,
            space.show_region_toolbar,
            space.show_region_ui,
        )
        r2 = bpy.ops.rigo.toggle_fullscreen()
        end_state = (
            space.show_region_header,
            space.show_region_tool_header,
            space.show_region_toolbar,
            space.show_region_ui,
        )
        full_ok = (
            r1 == {"FINISHED"}
            and r2 == {"FINISHED"}
            and focus_state == (False, True, False, True)
            and end_state == start_state
        )
        _mark(
            f"phase=fullscreen start={start_state} focus={focus_state} "
            f"end={end_state} full_ok={full_ok}"
        )

        _mark(f"PASS={reg_ok and axis_ok and quad_ok and align_ok and full_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
