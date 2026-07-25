"""Keyboard shortcuts for the paint-select region tools.

These register into the 3D View keymap, so they show up under
    Edit > Preferences > Keymap > 3D View
where the orthotist can freely rebind or disable any of them.

Defaults (all use Alt so they don't clash with Blender's built-ins):
    Alt+P  Paint Area
    Alt+O  Push Out
    Alt+I  Push In
    Alt+T  Thicken Area
    Alt+X  Delete Area
    Alt+G  Grow selection
    Alt+H  Shrink selection
    Alt+C  Clear selection

"""

import bpy

# (operator_idname, key, {modifiers}, {properties})
_SHORTCUTS = (
    ("rigo.paint_select", "P", {"alt": True}, {}),
    ("rigo.push_selection", "O", {"alt": True}, {"direction": "OUT"}),
    ("rigo.push_selection", "I", {"alt": True}, {"direction": "IN"}),
    ("rigo.thicken_selection", "T", {"alt": True}, {}),
    ("rigo.delete_selection", "X", {"alt": True}, {}),
    ("rigo.select_grow", "G", {"alt": True}, {}),
    ("rigo.select_shrink", "H", {"alt": True}, {}),
    ("rigo.select_clear", "C", {"alt": True}, {}),
)

_addon_keymaps = []


def register():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:  # headless / --background: no addon keyconfig
        return
    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    for idname, key, mods, props in _SHORTCUTS:
        kmi = km.keymap_items.new(idname, key, "PRESS", **mods)
        for prop, value in props.items():
            setattr(kmi.properties, prop, value)
        _addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:  # noqa: BLE001
            pass
    _addon_keymaps.clear()
