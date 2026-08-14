"""Persistent library of orthotist-authored pressure/expansion masks."""

import json
import os

import bpy


_FILE_NAME = "region_library.json"
_SCHEMA_VERSION = 1
_LIBRARY = None
_LIBRARY_VERSION = 0
_ENUM_CACHE = []
_ENUM_CACHE_VERSION = -1


def _library_path(create=False):
    folder = bpy.utils.user_resource("CONFIG", path="rigo_brace", create=create)
    return os.path.join(folder, _FILE_NAME)


def load_library(force=False):
    global _LIBRARY, _LIBRARY_VERSION
    if _LIBRARY is not None and not force:
        return _LIBRARY
    try:
        with open(_library_path(), "r", encoding="utf-8") as stream:
            document = json.load(stream)
        if not isinstance(document, dict):
            raise ValueError("Region library document must be an object")
        entries = document.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError("Region library entries must be a list")
        _LIBRARY = [entry for entry in entries if _valid_entry(entry)]
    except FileNotFoundError:
        _LIBRARY = []
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"Rigo Brace: invalid region library {_library_path()}: {error}")
        _LIBRARY = []
    _LIBRARY_VERSION += 1
    return _LIBRARY


def _valid_entry(entry):
    return (
        isinstance(entry, dict)
        and bool(entry.get("id"))
        and bool(entry.get("label"))
        and isinstance(entry.get("samples"), list)
        and len(entry["samples"]) >= 3
    )


def save_library():
    library_path = _library_path(create=True)
    temporary_path = library_path + ".tmp"
    document = {"version": _SCHEMA_VERSION, "entries": load_library()}
    with open(temporary_path, "w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=1)
    os.replace(temporary_path, library_path)


def get_entry(identifier):
    return next(
        (entry for entry in load_library() if entry["id"] == identifier), None
    )


def upsert_entry(entry):
    global _LIBRARY_VERSION
    entries = load_library()
    for index, existing in enumerate(entries):
        if existing["id"] == entry["id"]:
            entries[index] = entry
            break
    else:
        entries.append(entry)
    _LIBRARY_VERSION += 1
    save_library()


def delete_entry(identifier):
    global _LIBRARY_VERSION
    entries = load_library()
    original_count = len(entries)
    entries[:] = [entry for entry in entries if entry["id"] != identifier]
    if len(entries) == original_count:
        return False
    _LIBRARY_VERSION += 1
    save_library()
    return True


def identifier_from_label(label):
    base = "".join(character if character.isalnum() else "_" for character in label.upper())
    base = base.strip("_") or "REGION_STYLE"
    identifiers = {entry["id"] for entry in load_library()}
    candidate = base
    suffix = 1
    while candidate in identifiers:
        suffix += 1
        candidate = f"{base}_{suffix}"
    return candidate


def enum_items(_settings, _context):
    global _ENUM_CACHE_VERSION
    load_library()
    if _ENUM_CACHE_VERSION != _LIBRARY_VERSION:
        _ENUM_CACHE.clear()
        for entry in _LIBRARY:
            kind = entry.get("kind", "PRESSURE").title()
            pair = (
                "; part of a corrective pair"
                if (entry.get("clinical") or {}).get("paired") else ""
            )
            _ENUM_CACHE.append(
                (entry["id"], f"★ {entry['label']}",
                 f"{kind}{pair}; orthotist review required")
            )
        if not _ENUM_CACHE:
            _ENUM_CACHE.append(("NONE", "No saved styles", "Save a region first"))
        _ENUM_CACHE_VERSION = _LIBRARY_VERSION
    return _ENUM_CACHE
