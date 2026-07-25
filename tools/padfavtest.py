"""Functional test: the full Pressure-library favourite workflow (user report).

Replays the orthotist's scenario with numeric gates:
1. Selecting a builtin prefills its favourite depth/size/kind.
2. Place at cursor + Apply -> the dent depth EQUALS the set depth (+-0.05 mm).
3. Record the fitted shape as a new library entry ("favourite area").
4. Set Favourite (12 mm / 70 mm / EXPANSION) -> written to the JSON on disk.
5. Simulated restart (force-reload from disk) -> reselect -> favourites prefill.
6. Place the recorded favourite elsewhere + Apply -> raise EQUALS 12 mm.
7. Freeze guard: with a live modifier, add_pad REFUSES fast (< 1 s) naming it,
   and apply_pads refuses the same way.
Writes padfavtest_result.txt and self-quits. GUI only.
"""

import importlib
import json
import os
import time
from math import radians

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\padfavtest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _pad_library():
    return importlib.import_module(
        "bl_ext.user_default.rigo_brace.core.pad_library"
    )


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")
        PL = _pad_library()

        # clean slate: drop any previous QA entry from earlier runs
        while PL.delete_entry("QA_FAV_AREA"):
            pass
        for n in range(2, 6):
            PL.delete_entry(f"QA_FAV_AREA_{n}")
        PL.save_library()

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        scan.rotation_euler = (0.0, radians(90.0), 0.0)
        bpy.ops.object.transform_apply(rotation=True)

        # ---- 1) builtin prefill ---- #
        settings.pad_type = "BLANK_OVAL"
        entry = PL.get_entry("BLANK_OVAL")
        prefill_ok = (
            abs(settings.pad_depth - entry["depth_mm"]) < 1e-4
            and abs(settings.pad_size - entry["size_mm"]) < 1e-4
            and settings.pad_kind == entry["kind"]
        )
        _mark(
            f"phase=prefill depth={settings.pad_depth} size={settings.pad_size} "
            f"kind={settings.pad_kind} prefill_ok={prefill_ok}"
        )

        # ---- 2) place + apply: dent == depth ---- #
        bpy.context.scene.cursor.location = (
            scan.matrix_world @ scan.data.vertices[9000].co
        )
        bpy.ops.rigo.add_pad()
        before = {v.index: v.co.copy() for v in scan.data.vertices}
        bpy.ops.rigo.apply_pads()
        disps = [
            (v.co - before[v.index]).length * 1000.0 for v in scan.data.vertices
        ]
        moved = sum(1 for d in disps if d > 0.001)
        apply_ok = abs(max(disps) - settings.pad_depth) < 0.05 and moved > 100
        _mark(
            f"phase=apply max={max(disps):.2f}mm expected={settings.pad_depth} "
            f"moved={moved} apply_ok={apply_ok}"
        )

        # ---- 3) record the shape as a favourite area ---- #
        pads = [o for o in bpy.data.objects if o.get("rigo_pad_id")]
        # apply hid the pad; recording needs it as the active shape
        settings.active_pad = pads[0]
        bpy.ops.rigo.record_pad_shape(name="QA Fav Area")
        rec_id = settings.pad_type
        record_ok = rec_id.startswith("QA_FAV_AREA") and PL.get_entry(rec_id) is not None
        _mark(f"phase=record id={rec_id} record_ok={record_ok}")

        # ---- 4) set favourite -> verify the JSON on disk ---- #
        settings.pad_depth = 12.0
        settings.pad_size = 70.0
        settings.pad_kind = "EXPANSION"
        bpy.ops.rigo.set_pad_favourite()
        with open(PL._library_path(), "r", encoding="utf-8") as fh:
            disk = json.load(fh)
        disk_entry = next(
            (e for e in disk.get("entries", []) if e["id"] == rec_id), None
        )
        disk_ok = (
            disk_entry is not None
            and abs(disk_entry["depth_mm"] - 12.0) < 1e-4
            and abs(disk_entry["size_mm"] - 70.0) < 1e-4
            and disk_entry["kind"] == "EXPANSION"
        )
        _mark(f"phase=disk entry_on_disk={disk_entry is not None} disk_ok={disk_ok}")

        # ---- 5) simulated restart: force reload from disk, reselect ---- #
        settings.pad_depth = 1.0  # scramble, then prefill must restore
        PL.load_library(force=True)
        settings.pad_type = "BLANK_OVAL"
        settings.pad_type = rec_id
        reload_ok = (
            abs(settings.pad_depth - 12.0) < 1e-4
            and abs(settings.pad_size - 70.0) < 1e-4
            and settings.pad_kind == "EXPANSION"
        )
        _mark(
            f"phase=reload depth={settings.pad_depth} size={settings.pad_size} "
            f"kind={settings.pad_kind} reload_ok={reload_ok}"
        )

        # ---- 6) place the favourite elsewhere + apply: raise == 12 mm ---- #
        bpy.ops.rigo.clear_pads()
        bpy.context.scene.cursor.location = (
            scan.matrix_world @ scan.data.vertices[30000].co
        )
        bpy.ops.rigo.add_pad()
        before = {v.index: v.co.copy() for v in scan.data.vertices}
        bpy.ops.rigo.apply_pads()
        disps = [
            (v.co - before[v.index]).length * 1000.0 for v in scan.data.vertices
        ]
        fav_apply_ok = abs(max(disps) - 12.0) < 0.05
        _mark(f"phase=fav_apply max={max(disps):.2f}mm fav_apply_ok={fav_apply_ok}")

        # ---- 7) freeze guard: modifier present -> fast, named refusal ---- #
        mod = scan.modifiers.new(name="probe_subsurf", type="SUBSURF")
        t0 = time.perf_counter()
        guard_msg = ""
        try:
            bpy.ops.rigo.add_pad()
        except RuntimeError as exc:
            guard_msg = str(exc)
        dt_place = time.perf_counter() - t0
        apply_msg = ""
        try:
            bpy.ops.rigo.apply_pads()
        except RuntimeError as exc:
            apply_msg = str(exc)
        scan.modifiers.remove(mod)
        guard_ok = (
            "probe_subsurf" in guard_msg
            and dt_place < 1.0
            and "probe_subsurf" in apply_msg
        )
        _mark(
            f"phase=guard place_refused_in={dt_place:.2f}s "
            f"named={'probe_subsurf' in guard_msg} guard_ok={guard_ok}"
        )

        final = (
            prefill_ok and apply_ok and record_ok and disk_ok
            and reload_ok and fav_apply_ok and guard_ok
        )
        _mark(f"PASS={final}")

    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
