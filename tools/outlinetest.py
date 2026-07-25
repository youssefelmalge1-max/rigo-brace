"""Regression for retiring the duplicate legacy outline workflow."""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import prepare_a_design  # noqa: E402


_OUT = r"C:\Projects\Blender Add-on Braces\outlinetest_result.txt"
_TRIES = {"n": 0}


def _call_generate():
    try:
        return bpy.ops.rigo.generate_corset()
    except RuntimeError:
        return {"CANCELLED"}


def _generation_names():
    return sorted(
        obj.name
        for obj in bpy.data.objects
        if obj.name.startswith("Rigo Corset")
    )


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    lines = []
    try:
        _scan, settings = prepare_a_design()
        bpy.ops.rigo.clear_trimlines()
        blocked = _call_generate() == {"CANCELLED"}
        settings.trim_type = "A"
        bpy.ops.rigo.auto_trimline()
        generated = _call_generate() == {"FINISHED"}
        perimeter_count = sum(obj.name == "Rigo Trim Perimeter" for obj in bpy.data.objects)
        legacy_compatible = all(
            hasattr(bpy.ops.rigo, operator)
            for operator in ("edit_outline", "apply_outline", "reset_outline")
        )
        canonical_names = ["Rigo Corset", "Rigo Corset Base"]
        base_identity = bpy.data.objects.get("Rigo Corset Base")
        edit_result = bpy.ops.rigo.edit_outline()
        outline = bpy.data.objects.get("Rigo Outline")
        edit_state_ok = (
            edit_result == {"FINISHED"}
            and settings.outline_editing
            and bpy.context.mode == "EDIT_CURVE"
            and outline is not None
            and bpy.context.view_layer.objects.active is outline
            and not outline.hide_get()
        )
        apply_result = bpy.ops.rigo.apply_outline()
        applied_brace = bpy.data.objects.get("Rigo Corset")
        apply_clean = (
            apply_result == {"FINISHED"}
            and not settings.outline_editing
            and _generation_names() == canonical_names
            and bpy.data.objects.get("Rigo Corset Base") is base_identity
            and applied_brace is not None
            and bpy.context.view_layer.objects.active is applied_brace
            and not applied_brace.hide_get()
            and bpy.data.objects.get("Rigo Outline") is outline
            and outline.hide_get()
        )
        reset_result = bpy.ops.rigo.reset_outline()
        reset_brace = bpy.data.objects.get("Rigo Corset")
        reset_clean = (
            reset_result == {"FINISHED"}
            and not settings.outline_editing
            and bpy.data.objects.get("Rigo Outline") is None
            and _generation_names() == canonical_names
            and bpy.data.objects.get("Rigo Corset Base") is base_identity
            and reset_brace is not None
            and bpy.context.view_layer.objects.active is reset_brace
            and not reset_brace.hide_get()
        )
        passed = all(
            (
                blocked,
                generated,
                perimeter_count == 1,
                legacy_compatible,
                _generation_names() == canonical_names,
                edit_state_ok,
                apply_clean,
                reset_clean,
            )
        )
        lines.extend(
            (
                f"generate_without_perimeter_blocked={blocked}",
                f"generate_with_perimeter={generated}",
                f"perimeter_count={perimeter_count}",
                f"legacy_file_operators_registered={legacy_compatible}",
                f"legacy_edit={edit_result} state_ok={edit_state_ok}",
                f"legacy_apply={apply_result} names={_generation_names()} "
                f"base_preserved={bpy.data.objects.get('Rigo Corset Base') is base_identity} "
                f"clean={apply_clean}",
                f"legacy_reset={reset_result} names={_generation_names()} "
                f"clean={reset_clean}",
                f"PASS={passed}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={exc!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    with open(_OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
