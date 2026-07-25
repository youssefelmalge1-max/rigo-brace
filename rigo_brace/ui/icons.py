"""Custom step-icon loading for the Rigo Brace UI.

Loads the badge PNGs shipped in ``rigo_brace/icons`` through Blender's preview
system so each workflow stage shows a distinctive coloured badge. If the PNGs
are missing for any reason the UI falls back to the built-in icons declared in
``WORKFLOW_TABS``.
"""

import os

import bpy.utils.previews

# Map each workflow tab id to its badge PNG filename.
_ICON_FILES = {
    "FILE": "01_file.png",
    "SCAN": "02_scan.png",
    "LANDMARKS": "03_landmarks.png",
    "MESH": "04_mesh.png",
    "DESIGN": "05_design.png",
}

_collection = None


def _icons_dir():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons")


def register():
    global _collection
    _collection = bpy.utils.previews.new()
    base = _icons_dir()
    for tab_id, filename in _ICON_FILES.items():
        path = os.path.join(base, filename)
        if os.path.exists(path):
            try:
                _collection.load(tab_id, path, "IMAGE")
            except RuntimeError as exc:
                print(f"Rigo Brace: could not load workflow icon {path}: {exc}")


def unregister():
    global _collection
    if _collection is not None:
        bpy.utils.previews.remove(_collection)
        _collection = None


def icon_id(tab_id):
    """Return the custom preview icon_value for a tab, or 0 if unavailable."""
    if _collection is not None and tab_id in _collection:
        return _collection[tab_id].icon_id
    return 0
