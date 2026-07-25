"""Regression test for the pad shape LIBRARY: record / favourites / reuse.

Flow: place a builtin shape, deform it, record it under a name (json entry on
disk), set a favourite depth, verify the favourite pre-fills on re-selection,
respawn the recorded shape elsewhere, mirror, apply, and clean the entry up.
Writes padshapetest_result.txt then quits.  GUI only.
"""

import json
import os

import bpy
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\padshapetest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _library_file():
    base = bpy.utils.user_resource("CONFIG", path="rigo_brace")
    return os.path.join(base, "pad_library.json")


def _read_entry(ident):
    try:
        with open(_library_file(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for entry in data.get("entries", ()):
            if entry.get("id") == ident:
                return entry
    except Exception:
        pass
    return None


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

        mw = scan.matrix_world
        verts = [mw @ v.co for v in scan.data.vertices]
        idx_a = max(range(len(verts)), key=lambda i: verts[i].x)
        idx_b = max(range(len(verts)), key=lambda i: verts[i].y)

        # ---- place a builtin and deform two control points ---- #
        settings.pad_type = "BLANK_OVAL"
        settings.pad_size = 90.0
        bpy.ops.rigo.add_pad(location=verts[idx_a], use_location=True)
        pad = settings.active_pad
        pts = pad.data.splines[0].bezier_points
        n_src = len(pts)
        pts[0].co += Vector((0.0, 0.0, 0.02))
        pts[3].co += Vector((0.0, 0.0, -0.015))

        # ---- record it ---- #
        settings.pad_kind = "PRESSURE"
        settings.pad_depth = 9.0
        bpy.ops.rigo.record_pad_shape(name="Test Custom Shape")
        entry = _read_entry("TEST_CUSTOM_SHAPE")
        record_ok = (
            entry is not None
            and entry.get("builtin") is False
            and entry.get("kind") == "PRESSURE"
            and len(entry.get("points", ())) == n_src
            and entry.get("size_mm", 0) > 0
            and settings.pad_type == "TEST_CUSTOM_SHAPE"
        )
        _mark(f"phase=record entry_found={entry is not None} record_ok={record_ok}")

        # ---- favourite: save depth 12, verify persisted + prefilled ---- #
        settings.pad_depth = 12.0
        bpy.ops.rigo.set_pad_favourite()
        entry = _read_entry("TEST_CUSTOM_SHAPE")
        persisted_ok = entry is not None and abs(entry.get("depth_mm", 0) - 12.0) < 1e-3
        settings.pad_type = "BLANK_ROUNDED_RECTANGLE"  # switch away (prefills 8)
        away_depth = settings.pad_depth
        settings.pad_type = "TEST_CUSTOM_SHAPE"        # back: prefill favourite
        favourite_ok = (
            persisted_ok
            and abs(settings.pad_depth - 12.0) < 1e-3
            and abs(away_depth - 12.0) > 1e-3
        )
        _mark(f"phase=favourite persisted={persisted_ok} depth={settings.pad_depth} "
              f"favourite_ok={favourite_ok}")

        # ---- respawn the recorded shape elsewhere ---- #
        bpy.ops.rigo.add_pad(location=verts[idx_b], use_location=True)
        pad2 = settings.active_pad
        respawn_ok = (
            pad2 is not None
            and pad2.get("rigo_pad_id") == "TEST_CUSTOM_SHAPE"
            and len(pad2.data.splines[0].bezier_points) == n_src
            and abs(pad2.get("rigo_depth", 0) - 12.0) < 1e-3
        )
        _mark(f"phase=respawn respawn_ok={respawn_ok}")

        # ---- mirror ---- #
        bpy.ops.rigo.mirror_pads()
        twins = [o for o in bpy.data.objects if o.get("rigo_twin_of")]
        cx_src = sum(
            (pad2.matrix_world @ bp.co).x
            for bp in pad2.data.splines[0].bezier_points
        ) / n_src
        mirrored_x = []
        for twin in twins:
            if twin.get("rigo_twin_of") == pad2.name:
                mirrored_x = [
                    (twin.matrix_world @ bp.co).x
                    for bp in twin.data.splines[0].bezier_points
                ]
        cx_twin = sum(mirrored_x) / len(mirrored_x) if mirrored_x else 1e9
        mirror_ok = len(twins) >= 1 and abs(cx_twin + cx_src) < 0.03
        _mark(f"phase=mirror twins={len(twins)} cx_src={cx_src:.3f} "
              f"cx_twin={cx_twin:.3f} mirror_ok={mirror_ok}")

        # ---- apply ---- #
        b_before = verts[idx_b].copy()
        bpy.ops.rigo.apply_pads()
        b_after = mw @ scan.data.vertices[idx_b].co
        moved = (b_after - b_before).length * 1000.0
        apply_ok = moved > 0.5
        _mark(f"phase=apply moved={moved:.2f}mm apply_ok={apply_ok}")

        # ---- builtin delete refused; custom delete works ---- #
        settings.pad_type = "BLANK_OVAL"
        result = bpy.ops.rigo.delete_pad_entry()
        builtin_guard_ok = result == {"CANCELLED"}
        settings.pad_type = "TEST_CUSTOM_SHAPE"
        result = bpy.ops.rigo.delete_pad_entry()
        cleanup_ok = result == {"FINISHED"} and _read_entry("TEST_CUSTOM_SHAPE") is None
        _mark(f"phase=delete builtin_guard={builtin_guard_ok} cleanup={cleanup_ok}")

        _mark(
            "PASS="
            f"{record_ok and favourite_ok and respawn_ok and mirror_ok and apply_ok and builtin_guard_ok and cleanup_ok}"
        )

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
