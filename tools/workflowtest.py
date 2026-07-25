"""Functional test for the single canonical workflow navigation state."""

import bpy


_OUT = r"C:\Projects\Blender Add-on Braces\workflowtest_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(message):
    _log.append(str(message))
    with open(_OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(_log))


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1

    try:
        settings = bpy.context.scene.rigo_brace
        _mark("phase=start")

        initial_ok = (
            settings.brace_stage == "FILE"
            and not hasattr(settings, "active_tab")
            and not hasattr(bpy.types, "RIGO_PT_workflow")
        )
        _mark(f"phase=initial stage={settings.brace_stage} initial_ok={initial_ok}")

        direct_result = bpy.ops.rigo.set_tab(tab="MESH")
        direct_ok = direct_result == {"FINISHED"} and settings.brace_stage == "MESH"
        _mark(f"phase=direct stage={settings.brace_stage} direct_ok={direct_ok}")

        bpy.ops.rigo.step_tab(direction="NEXT")
        next_ok = settings.brace_stage == "DESIGN"
        bpy.ops.rigo.step_tab(direction="NEXT")
        end_clamp_ok = settings.brace_stage == "DESIGN"
        _mark(
            f"phase=next stage={settings.brace_stage} next_ok={next_ok} "
            f"end_clamp_ok={end_clamp_ok}"
        )

        bpy.ops.rigo.step_tab(direction="PREV")
        back_ok = settings.brace_stage == "MESH"
        back_stage = settings.brace_stage
        bpy.ops.rigo.set_tab(tab="FILE")
        bpy.ops.rigo.step_tab(direction="PREV")
        start_clamp_ok = settings.brace_stage == "FILE"
        _mark(
            f"phase=back stage={back_stage} back_ok={back_ok} "
            f"start_clamp_ok={start_clamp_ok}"
        )

        try:
            bpy.ops.rigo.set_tab(tab="NOT_A_STAGE")
            invalid_rejected = False
        except RuntimeError as exc:
            invalid_rejected = "Unknown workflow stage" in str(exc)
        invalid_ok = invalid_rejected and settings.brace_stage == "FILE"
        _mark(f"phase=invalid rejected={invalid_rejected} invalid_ok={invalid_ok}")

        passed = all(
            (
                initial_ok,
                direct_ok,
                next_ok,
                end_clamp_ok,
                back_ok,
                start_clamp_ok,
                invalid_ok,
            )
        )
        _mark(f"PASS={passed}")
    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
