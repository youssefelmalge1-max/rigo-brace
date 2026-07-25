"""Persistent pressure/relief shape library (LeoSpinal-style).

Each entry is a named modification shape: a closed outline stored in a
canonical 2D frame, plus the orthotist's favourite depth, size and kind. The
library lives in ONE json file in the
user's Blender config dir, so it is global per PC: shapes recorded on one
patient are available on every patient, and survive add-on reinstalls.

    %APPDATA%/Blender Foundation/Blender/<ver>/config/rigo_brace/pad_library.json

Neutral authoring primitives are merged in on every load, so the drop-down is
never empty. Misleading schema-v1 clinical circles are preserved only as
unverified legacy entries.

Gotchas honoured here:
- No file IO at register() time: everything loads lazily on first access.
- Blender dynamic EnumProperty items must come from a long-lived Python list
  (string lifetime!) — we cache the items list at module level and only
  rebuild it when the library version bumps.
- Saves are atomic (tmp file + os.replace).
"""

import json
import math
import os
import shutil

import bpy

_FILE_NAME = "pad_library.json"
_SCHEMA_VERSION = 2

_GENERIC_DEFS = (
    ("BLANK_OVAL", "Blank Oval", "OVAL"),
    ("BLANK_ROUNDED_RECTANGLE", "Blank Rounded Rectangle", "ROUNDED_RECTANGLE"),
)

_LEGACY_CLINICAL_IDS = {
    "ILIAC_CREST_PRESSURE_L",
    "ILIAC_CREST_PRESSURE_R",
    "CURVATURE_CORR_PRESSURE_1_L",
    "CURVATURE_CORR_PRESSURE_1_R",
    "CURVATURE_CORR_PRESSURE_2_L",
    "CURVATURE_CORR_PRESSURE_2_R",
    "TROCHANTERIC_EXPANSION_L",
    "TROCHANTERIC_EXPANSION_R",
}


def _unit_circle(n=12):
    return [
        [math.cos(2.0 * math.pi * i / n), math.sin(2.0 * math.pi * i / n)]
        for i in range(n)
    ]


def _rounded_rectangle():
    return [
        [0.65, 1.0],
        [-0.65, 1.0],
        [-1.0, 0.65],
        [-1.0, -0.65],
        [-0.65, -1.0],
        [0.65, -1.0],
        [1.0, -0.65],
        [1.0, 0.65],
    ]


def _primitive_points(primitive):
    return _unit_circle() if primitive == "OVAL" else _rounded_rectangle()


def _builtin_entries():
    return [
        {
            "id": ident,
            "label": label,
            "kind": "PRESSURE",
            "depth_mm": 8.0,
            "size_mm": 90.0,
            "width_mm": 90.0,
            "height_mm": 90.0,
            "builtin": True,
            "group": "GENERIC",
            "points": _primitive_points(primitive),
            "handles": None,
            "handle_mode": "AUTO",
            "falloff": "SMOOTH",
            "orientation": "SURFACE_UP",
            "requires_orthotist_review": True,
            "schema_version": _SCHEMA_VERSION,
        }
        for ident, label, primitive in _GENERIC_DEFS
    ]


# Module-level cache. _LIB is the list of entry dicts; _LIB_VERSION bumps on
# every mutation so the enum-items cache knows when to rebuild.
_LIB = None
_LIB_VERSION = 0


def _library_path(create=False):
    base = bpy.utils.user_resource("CONFIG", path="rigo_brace", create=create)
    return os.path.join(base, _FILE_NAME)


def _backup_v1(path):
    backup = path + ".v1.backup.json"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    return backup


def _entry_dimensions(entry):
    points = entry.get("points", ())
    if not points:
        return 0.0, 0.0
    scale = float(entry.get("size_mm", 90.0)) * 0.5
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return (max(xs) - min(xs)) * scale, (max(ys) - min(ys)) * scale


def _migrate_entry(entry, source_version):
    migrated = dict(entry)
    ident = migrated["id"]
    is_legacy_clinical = ident in _LEGACY_CLINICAL_IDS
    width_mm, height_mm = _entry_dimensions(migrated)

    if is_legacy_clinical:
        label = str(migrated.get("label", ident))
        if not label.startswith("Legacy — "):
            migrated["label"] = f"Legacy — {label}"
        migrated["builtin"] = False
        migrated["group"] = "UNVERIFIED_LEGACY"
        migrated["legacy_source_id"] = ident
    else:
        migrated.setdefault("group", "USER")

    migrated.setdefault("handles", None)
    migrated.setdefault("handle_mode", "AUTO")
    migrated.setdefault("falloff", "SMOOTH")
    migrated.setdefault("orientation", "SURFACE_UP")
    migrated.setdefault("width_mm", width_mm)
    migrated.setdefault("height_mm", height_mm)
    migrated["requires_orthotist_review"] = True
    migrated["schema_version"] = _SCHEMA_VERSION
    if source_version < _SCHEMA_VERSION and migrated.get("handles") is None:
        migrated["curve_fidelity"] = "AUTO_HANDLES_FROM_V1"
        migrated["legacy_source_schema"] = source_version
    return migrated


def _write_entries(entries):
    path = _library_path(create=True)
    tmp = path + ".tmp"
    payload = {"version": _SCHEMA_VERSION, "entries": entries}
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, path)


def load_library(force=False):
    """Return the entry list, reading the json once (lazily).

    Missing or invalid JSON falls back to generic entries. Filesystem errors such as
    denied access propagate so the library is not silently overwritten later.
    """
    global _LIB, _LIB_VERSION
    if _LIB is not None and not force:
        return _LIB

    entries = []
    source_version = _SCHEMA_VERSION
    migrated_document = False
    try:
        path = _library_path()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            source_version = int(data.get("version", 1))
            migrated_document = source_version < _SCHEMA_VERSION
            if migrated_document:
                _backup_v1(path)
            for entry in data.get("entries", ()):
                if isinstance(entry, dict) and entry.get("id") and entry.get("points"):
                    entries.append(_migrate_entry(entry, source_version))
    except FileNotFoundError:
        entries = []
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"Rigo Brace: invalid pressure library {_library_path()}: {exc}")
        entries = []

    # Merge: every builtin id must exist (file copies win, keeping the
    # orthotist's edited favourites for builtins too).
    have = {e["id"] for e in entries}
    for builtin in _builtin_entries():
        if builtin["id"] not in have:
            entries.append(builtin)
    # Builtins first, in canonical order; recorded entries keep file order.
    order = {ident: i for i, (ident, _label, _primitive) in enumerate(_GENERIC_DEFS)}
    entries.sort(key=lambda e: order.get(e["id"], len(order)))

    _LIB = entries
    _LIB_VERSION += 1
    if migrated_document:
        _write_entries(entries)
    return _LIB


def save_library():
    """Atomically write the current library to disk."""
    global _LIB_VERSION
    entries = load_library()
    entries[:] = [_migrate_entry(entry, _SCHEMA_VERSION) for entry in entries]
    _write_entries(entries)
    _LIB_VERSION += 1


def get_entry(ident):
    for entry in load_library():
        if entry["id"] == ident:
            return entry
    return None


def upsert_entry(entry):
    global _LIB_VERSION
    entries = load_library()
    entry = _migrate_entry(entry, _SCHEMA_VERSION)
    for i, existing in enumerate(entries):
        if existing["id"] == entry["id"]:
            entries[i] = entry
            break
    else:
        entries.append(entry)
    _LIB_VERSION += 1


def delete_entry(ident):
    """Remove a recorded entry.  Builtins are protected; returns success."""
    global _LIB_VERSION
    entries = load_library()
    for i, entry in enumerate(entries):
        if entry["id"] == ident:
            if entry.get("builtin"):
                return False
            del entries[i]
            _LIB_VERSION += 1
            return True
    return False


def entry_id_from_label(label):
    """Stable unique identifier from a user-typed name."""
    ident = "".join(c if c.isalnum() else "_" for c in label.strip().upper())
    ident = ident.strip("_") or "SHAPE"
    existing = {e["id"] for e in load_library()}
    candidate, n = ident, 1
    while candidate in existing:
        n += 1
        candidate = f"{ident}_{n}"
    return candidate


# --------------------------------------------------------------------------- #
# Dynamic EnumProperty items — cached list (string-lifetime gotcha).
# --------------------------------------------------------------------------- #
_ENUM_CACHE = []
_ENUM_CACHE_VERSION = -1


def pad_enum_items(_self, _context):
    global _ENUM_CACHE_VERSION
    load_library()
    if _ENUM_CACHE_VERSION != _LIB_VERSION:
        _ENUM_CACHE.clear()
        for entry in _LIB:
            kind = (
                "Pressure shape"
                if entry.get("kind") == "PRESSURE"
                else "Expansion shape"
            )
            group = entry.get("group")
            if group == "UNVERIFIED_LEGACY":
                prefix = "⚠ "
                description = "Unverified legacy geometry"
            else:
                prefix = "" if entry.get("builtin") else "★ "
                description = kind
            _ENUM_CACHE.append((entry["id"], f"{prefix}{entry['label']}", description))
        _ENUM_CACHE_VERSION = _LIB_VERSION
    return _ENUM_CACHE
