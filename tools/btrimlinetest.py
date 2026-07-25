"""Installed-copy technical geometry gate for the clinic B model."""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import prepare_b_design  # noqa: E402


_OUT = r"C:\Projects\Blender Add-on Braces\btrimlinetest_result.txt"
_TRIES = {"n": 0}


def _call_qa():
    try:
        return bpy.ops.rigo.verify_brace_qa()
    except RuntimeError:
        return {"CANCELLED"}


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.ops.rigo, "verify_brace_qa") and _TRIES["n"] < 25:
        return 0.1
    lines = []
    try:
        _scan, _settings = prepare_b_design()
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        points = len(perimeter.data.splines[0].bezier_points) if perimeter else 0
        generation_error = ""
        try:
            generated = bpy.ops.rigo.generate_curve_corset() == {"FINISHED"}
        except RuntimeError as error:
            generated = False
            generation_error = str(error)
        brace = bpy.data.objects.get("Rigo Corset")
        qa_result = _call_qa() if brace is not None else {"CANCELLED"}
        qa_pass = bool(
            brace is not None
            and qa_result == {"FINISHED"}
            and brace.get("rigo_qa_pass", False)
        )
        safe_blocked = (
            not generated
            and "cannot be generated" in generation_error.lower()
            and "traceback" not in generation_error.lower()
            and brace is None
            and bpy.data.objects.get("Rigo Corset Candidate") is None
            and bpy.data.objects.get("Rigo Corset Base Candidate") is None
        )
        # A controlled cancellation is an important safety regression, but it
        # must not turn an unsupported clinic model into a green readiness gate.
        # If generation becomes feasible, successful manufacturing QA is the
        # only condition that can make this model ready.
        safety_pass = generated or safe_blocked
        manufacturing_qa_ready = generated and qa_pass
        readiness_pass = points >= 36 and manufacturing_qa_ready
        lines.extend(
            (
                f"perimeter_points={points}",
                f"generated={generated}",
                f"generation_error={generation_error!r}",
                f"qa_result={qa_result}",
                f"SAFETY_PASS={safety_pass}",
                f"safe_blocked={safe_blocked}",
                f"manufacturing_qa_ready={manufacturing_qa_ready}",
                f"READINESS_PASS={readiness_pass}",
                f"PASS={readiness_pass}",
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
