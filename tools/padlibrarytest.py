"""Regression test for schema-v1 to schema-v2 pressure-library migration."""

import hashlib
import importlib
import json
import os
import shutil
import tempfile

import bpy


_OUT = r"C:\Projects\Blender Add-on Braces\padlibrarytest_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(message):
    _log.append(str(message))
    with open(_OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(_log))


def _library_module():
    return importlib.import_module("bl_ext.user_default.rigo_brace.core.pad_library")


def _sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _v1_fixture():
    return {
        "version": 1,
        "entries": [
            {
                "id": "ILIAC_CREST_PRESSURE_L",
                "label": "Iliac Crest Pressure L",
                "kind": "EXPANSION",
                "depth_mm": 12.0,
                "size_mm": 70.0,
                "builtin": True,
                "points": [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]],
            },
            {
                "id": "ORTHOTIST_CUSTOM",
                "label": "Orthotist Custom",
                "kind": "PRESSURE",
                "depth_mm": 9.0,
                "size_mm": 80.0,
                "builtin": False,
                "points": [[1.0, 0.0], [0.2, 0.7], [-0.8, 0.1], [0.0, -1.0]],
            },
        ],
    }


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1

    library = _library_module()
    original_path_function = library._library_path
    temp_dir = tempfile.mkdtemp(prefix="rigo_pad_library_")
    library_path = os.path.join(temp_dir, "pad_library.json")

    try:
        with open(library_path, "w", encoding="utf-8") as handle:
            json.dump(_v1_fixture(), handle)
        original_hash = _sha256(library_path)

        library._library_path = lambda create=False: library_path
        library._LIB = None
        entries = library.load_library(force=True)
        by_id = {entry["id"]: entry for entry in entries}

        backup_path = library_path + ".v1.backup.json"
        backup_ok = os.path.exists(backup_path) and _sha256(backup_path) == original_hash
        with open(library_path, "r", encoding="utf-8") as handle:
            migrated_document = json.load(handle)
        schema_ok = migrated_document.get("version") == 2
        generic_ok = {"BLANK_OVAL", "BLANK_ROUNDED_RECTANGLE"}.issubset(by_id)
        _mark(
            f"phase=document backup_ok={backup_ok} schema_ok={schema_ok} "
            f"generic_ok={generic_ok}"
        )

        legacy = by_id["ILIAC_CREST_PRESSURE_L"]
        legacy_ok = (
            legacy["kind"] == "EXPANSION"
            and legacy["group"] == "UNVERIFIED_LEGACY"
            and legacy["builtin"] is False
            and legacy["requires_orthotist_review"] is True
            and legacy["handles"] is None
            and legacy["curve_fidelity"] == "AUTO_HANDLES_FROM_V1"
            and legacy["label"].startswith("Legacy — ")
        )
        _mark(f"phase=legacy preserved_kind={legacy['kind']} legacy_ok={legacy_ok}")

        custom = by_id["ORTHOTIST_CUSTOM"]
        custom_ok = (
            custom["group"] == "USER"
            and custom["points"] == _v1_fixture()["entries"][1]["points"]
            and custom["depth_mm"] == 9.0
            and custom["curve_fidelity"] == "AUTO_HANDLES_FROM_V1"
            and custom["width_mm"] > 0.0
            and custom["height_mm"] > 0.0
        )
        _mark(f"phase=custom custom_ok={custom_ok}")

        backup_hash = _sha256(backup_path)
        library.load_library(force=True)
        idempotent_ok = _sha256(backup_path) == backup_hash
        protected_ok = library.delete_entry("BLANK_OVAL") is False
        _mark(
            f"phase=repeat idempotent_ok={idempotent_ok} protected_ok={protected_ok}"
        )

        _mark(
            f"PASS={backup_ok and schema_ok and generic_ok and legacy_ok and custom_ok and idempotent_ok and protected_ok}"
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    finally:
        library._library_path = original_path_function
        library._LIB = None
        library.load_library(force=True)
        shutil.rmtree(temp_dir, ignore_errors=True)

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
