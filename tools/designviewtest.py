"""Installed-copy regression for trim/body versus final-brace view states."""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators.qa_ops import evaluate_brace_qa


OUT = r"C:\Projects\Blender Add-on Braces\designviewtest_result.txt"
TRIES = {"count": 0}
LINES = []


def _write(message):
    LINES.append(str(message))
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(LINES))


def _state(scan, perimeter, brace, mode):
    base = bpy.data.objects.get("Rigo Corset Base")
    active = bpy.context.view_layer.objects.active
    selected = sorted(obj.name for obj in bpy.context.selected_objects)
    return {
        "mode": bpy.context.scene.rigo_brace.design_view_mode == mode,
        "scan_hidden": scan.hide_get(),
        "perimeter_hidden": perimeter.hide_get(),
        "brace_hidden": None if brace is None else brace.hide_get(),
        "base_hidden": None if base is None else base.hide_get(),
        "active": None if active is None else active.name,
        "selected": selected,
    }


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["count"] < 30:
        return 0.1
    try:
        scan, settings = prepare_reference_design()
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        helper = bpy.data.objects.new("LM_TEST_PREVIEW_HELPER", None)
        bpy.context.scene.collection.objects.link(helper)
        initial = _state(scan, perimeter, None, "TRIM")
        initial_ok = (
            initial["mode"]
            and not initial["scan_hidden"]
            and not initial["perimeter_hidden"]
            and initial["active"] == perimeter.name
        )
        _write(f"initial={initial} ok={initial_ok}")

        generated = bpy.ops.rigo.generate_corset()
        brace = bpy.data.objects.get("Rigo Corset")
        brace_state = _state(scan, perimeter, brace, "BRACE")
        brace_finish_polls = all(
            operator.poll()
            for operator in (
                bpy.ops.rigo.cut_slots,
                bpy.ops.rigo.emboss_text,
                bpy.ops.rigo.smooth_trim_edge,
                bpy.ops.rigo.flare_edge,
                bpy.ops.rigo.vent_grid,
            )
        )
        brace_ok = (
            generated == {"FINISHED"}
            and brace_state["mode"]
            and brace_state["scan_hidden"]
            and brace_state["perimeter_hidden"]
            and not brace_state["brace_hidden"]
            and brace_state["base_hidden"]
            and brace_state["active"] == brace.name
            and brace_state["selected"] == [brace.name]
            and helper.hide_get()
            and brace_finish_polls
        )
        _write(
            f"brace_preview={brace_state} finishing_enabled={brace_finish_polls} "
            f"ok={brace_ok}"
        )

        trim_result = bpy.ops.rigo.design_view(mode="TRIM")
        trim_state = _state(scan, perimeter, brace, "TRIM")
        trim_finish_polls = any(
            operator.poll()
            for operator in (
                bpy.ops.rigo.cut_slots,
                bpy.ops.rigo.emboss_text,
                bpy.ops.rigo.smooth_trim_edge,
                bpy.ops.rigo.flare_edge,
                bpy.ops.rigo.vent_grid,
            )
        )
        trim_ok = (
            trim_result == {"FINISHED"}
            and trim_state["mode"]
            and not trim_state["scan_hidden"]
            and not trim_state["perimeter_hidden"]
            and trim_state["brace_hidden"]
            and trim_state["base_hidden"]
            and trim_state["active"] == perimeter.name
            and trim_state["selected"] == [perimeter.name]
            and helper.hide_get()
            and not trim_finish_polls
        )
        _write(
            f"trim_edit={trim_state} finishing_enabled={trim_finish_polls} "
            f"ok={trim_ok}"
        )

        settings.corset_offset += 1.0
        dirty_ok = settings.brace_dirty and bool(brace.get("rigo_brace_dirty", False))
        settings.opening_width += 2.0
        regenerated_trim = bpy.ops.rigo.auto_trimline()
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        retrim_state = _state(scan, perimeter, brace, "TRIM")
        retrim_ok = (
            regenerated_trim == {"FINISHED"}
            and dirty_ok
            and not retrim_state["scan_hidden"]
            and not retrim_state["perimeter_hidden"]
            and retrim_state["brace_hidden"]
            and retrim_state["active"] == perimeter.name
        )
        _write(f"retrim={retrim_state} dirty={dirty_ok} ok={retrim_ok}")

        updated = bpy.ops.rigo.generate_corset()
        brace = bpy.data.objects.get("Rigo Corset")
        updated_state = _state(scan, perimeter, brace, "BRACE")
        unique = [obj.name for obj in bpy.data.objects if obj.name.startswith("Rigo Corset")]
        update_ok = (
            updated == {"FINISHED"}
            and not settings.brace_dirty
            and not bool(brace.get("rigo_brace_dirty", True))
            and updated_state["scan_hidden"]
            and updated_state["perimeter_hidden"]
            and not updated_state["brace_hidden"]
            and updated_state["active"] == brace.name
            and len(unique) == 2
            and set(unique) == {"Rigo Corset Base", "Rigo Corset"}
        )
        _write(f"updated={updated_state} objects={unique} ok={update_ok}")

        source_vertex = scan.data.vertices[0]
        source_coordinate = source_vertex.co.copy()
        source_vertex.co.x += 0.001
        scan.data.update()
        stale_source_qa = evaluate_brace_qa(bpy.context, brace)
        source_guard_ok = (
            not stale_source_qa["passed"]
            and stale_source_qa["reasons"]
            and "corrected body changed" in stale_source_qa["reasons"][0].lower()
            and settings.brace_dirty
            and bool(brace.get("rigo_brace_dirty", False))
        )
        source_vertex.co = source_coordinate
        scan.data.update()
        _write(
            f"source_guard={stale_source_qa['reasons']} dirty={settings.brace_dirty} "
            f"ok={source_guard_ok}"
        )

        # Missing either source fingerprint must stale-block a legacy or
        # corrupt brace instead of allowing it through manufacturing QA.
        restored = bpy.ops.rigo.generate_corset()
        brace = bpy.data.objects.get("Rigo Corset")
        del brace["rigo_source_trim_signature"]
        missing_record_qa = evaluate_brace_qa(bpy.context, brace)
        missing_record_ok = (
            restored == {"FINISHED"}
            and not missing_record_qa["passed"]
            and missing_record_qa["reasons"]
            and "no complete source record"
            in missing_record_qa["reasons"][0].lower()
            and settings.brace_dirty
            and bool(brace.get("rigo_brace_dirty", False))
        )
        _write(
            f"missing_source_record={missing_record_qa['reasons']} "
            f"dirty={settings.brace_dirty} ok={missing_record_ok}"
        )

        # Force an unexpected exception after the private base is created.
        # The last canonical objects and working view must remain intact.
        restored_again = bpy.ops.rigo.generate_corset()
        brace = bpy.data.objects.get("Rigo Corset")
        valid_base = bpy.data.objects.get("Rigo Corset Base")
        prior_mode = settings.design_view_mode
        prior_outline = settings.outline_editing
        valid_perimeter_data = perimeter.data
        malformed_data = bpy.data.curves.new(
            "Transaction Regression Perimeter", "CURVE"
        )
        malformed_data.dimensions = "3D"
        malformed_data.splines.new("POLY")
        perimeter.data = malformed_data
        unexpected_error = ""
        unexpected_raised = False
        try:
            unexpected_result = bpy.ops.rigo.generate_corset()
        except RuntimeError as error:
            unexpected_result = {"CANCELLED"}
            unexpected_error = str(error)
            unexpected_raised = True
        finally:
            perimeter.data = valid_perimeter_data
            bpy.data.curves.remove(malformed_data)
        candidates_clean = (
            bpy.data.objects.get("Rigo Corset Candidate") is None
            and bpy.data.objects.get("Rigo Corset Base Candidate") is None
        )
        transaction_state = _state(scan, perimeter, brace, prior_mode)
        view_restored = (
            transaction_state["mode"]
            and transaction_state["scan_hidden"]
            and transaction_state["perimeter_hidden"]
            and not transaction_state["brace_hidden"]
            and transaction_state["base_hidden"]
            and transaction_state["active"] == brace.name
            and transaction_state["selected"] == [brace.name]
        )
        transaction_ok = (
            restored_again == {"FINISHED"}
            and unexpected_raised
            and unexpected_result == {"CANCELLED"}
            and bpy.data.objects.get("Rigo Corset") is brace
            and bpy.data.objects.get("Rigo Corset Base") is valid_base
            and candidates_clean
            and view_restored
            and settings.design_view_mode == prior_mode
            and settings.outline_editing == prior_outline
        )
        _write(
            f"unexpected_transaction result={unexpected_result} "
            f"error={unexpected_error!r} candidates_clean={candidates_clean} "
            f"view={transaction_state} view_restored={view_restored} "
            f"ok={transaction_ok}"
        )

        perimeter.data.splines[0].bezier_points[5].co.x += 0.010
        fit_result = bpy.ops.rigo.snap_trimline_to_surface()
        fit_state = _state(scan, perimeter, brace, "TRIM")
        fit_ok = (
            fit_result == {"FINISHED"}
            and settings.brace_dirty
            and not fit_state["scan_hidden"]
            and not fit_state["perimeter_hidden"]
            and fit_state["brace_hidden"]
            and fit_state["active"] == perimeter.name
        )
        _write(f"fit={fit_state} dirty={settings.brace_dirty} ok={fit_ok}")
        _write(
            f"PASS={initial_ok and brace_ok and trim_ok and retrim_ok and update_ok and source_guard_ok and missing_record_ok and transaction_ok and fit_ok}"
        )
    except Exception as error:  # noqa: BLE001
        import traceback

        _write(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
