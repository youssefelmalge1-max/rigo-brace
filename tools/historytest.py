"""Regression test for the hidden legacy single-mesh snapshot operators.

Verifies: importing then pressing Next snapshots the scan as 00_/01_... version
objects in a per-patient collection, advances the stage, freezes the prior
version (hidden); Back reveals the previous version; Rollback jumps to a saved
stage; re-doing Next after rollback rebuilds forward history.
This does not certify complete brace-project restoration. Writes
historytest_result.txt and self-quits. GUI only.
"""

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\historytest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _versions(patient):
    out = {}
    for o in bpy.data.objects:
        if o.type == "MESH" and o.get("rigo_patient") == patient:
            out[int(o.get("rigo_stage", 0))] = o
    return out


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

        # The orthotist types the patient name BEFORE starting the workflow;
        # history must be keyed to it (issue #4), not to the mesh name.
        settings.brace_patient = "QA Patient"

        # ---- Next: init history + advance to SCAN ---- #
        bpy.ops.rigo.stage_next()
        patient = settings.brace_patient
        vers = _versions(patient)
        cur = settings.scan_object
        coll = bpy.data.collections.get(patient)
        next_ok = (
            patient == "QA Patient"
            and 0 in vers and 1 in vers
            and settings.brace_stage == "SCAN"
            and int(cur.get("rigo_stage", -1)) == 1
            and vers[0].name == "00_QA Patient_FILE"
            and vers[1].name == "01_QA Patient_SCAN"
            and not vers[1].hide_get()       # current visible
            and vers[0].hide_get()           # prior frozen/hidden
            and coll is not None
        )
        _mark(f"phase=next patient={patient} names={[vers[i].name for i in sorted(vers)]} "
              f"stage={settings.brace_stage} next_ok={next_ok}")

        # ---- advance again to LANDMARKS ---- #
        bpy.ops.rigo.stage_next()
        vers = _versions(patient)
        adv_ok = (
            settings.brace_stage == "LANDMARKS"
            and set(vers) == {0, 1, 2}
            and not vers[2].hide_get()
        )
        _mark(f"phase=next2 stages={sorted(vers)} stage={settings.brace_stage} "
              f"adv_ok={adv_ok}")

        # ---- Back: reveal SCAN ---- #
        bpy.ops.rigo.stage_back()
        vers = _versions(patient)
        back_ok = (
            settings.brace_stage == "SCAN"
            and not vers[1].hide_get()
            and vers[2].hide_get()
            and settings.scan_object is vers[1]
        )
        _mark(f"phase=back stage={settings.brace_stage} back_ok={back_ok}")

        # ---- Rollback to FILE ---- #
        bpy.ops.rigo.rollback(stage="FILE")
        vers = _versions(patient)
        roll_ok = (
            settings.brace_stage == "FILE"
            and not vers[0].hide_get()
            and vers[1].hide_get()
            and settings.scan_object is vers[0]
        )
        _mark(f"phase=rollback stage={settings.brace_stage} roll_ok={roll_ok}")

        # ---- Next from FILE rebuilds forward (drops old 1,2; makes fresh 1) ---- #
        bpy.ops.rigo.stage_next()
        vers = _versions(patient)
        rebuild_ok = (
            settings.brace_stage == "SCAN"
            and set(vers) == {0, 1}      # forward versions were rebuilt, not stacked
        )
        _mark(f"phase=rebuild stages={sorted(vers)} rebuild_ok={rebuild_ok}")

        # ---- Fallback: empty patient name -> object name is used ---- #
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan2 = bpy.context.active_object
        settings.scan_object = scan2
        bpy.context.view_layer.objects.active = scan2
        settings.brace_patient = ""
        obj_name = scan2.name
        bpy.ops.rigo.stage_next()
        fb_vers = _versions(obj_name)
        fallback_ok = (
            settings.brace_patient == obj_name
            and 0 in fb_vers and 1 in fb_vers
            and fb_vers[0].name == f"00_{obj_name}_FILE"
        )
        _mark(f"phase=fallback patient={settings.brace_patient} "
              f"fallback_ok={fallback_ok}")

        final = (next_ok and adv_ok and back_ok and roll_ok and rebuild_ok
                 and fallback_ok)
        _mark(f"PASS={final}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
