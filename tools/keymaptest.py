"""Verify the paint-select keyboard shortcuts registered into the 3D View keymap.

Writes keymaptest_result.txt and self-quits.
"""

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\keymaptest_result.txt"
_TRIES = {"n": 0}
_log = []

_EXPECT = {
    ("rigo.paint_select", "P"): (True, None),
    ("rigo.push_selection", "O"): (True, "OUT"),
    ("rigo.push_selection", "I"): (True, "IN"),
    ("rigo.thicken_selection", "T"): (True, None),
    ("rigo.delete_selection", "X"): (True, None),
    ("rigo.select_grow", "G"): (True, None),
    ("rigo.select_shrink", "H"): (True, None),
    ("rigo.select_clear", "C"): (True, None),
}


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        wm = bpy.context.window_manager
        kc = wm.keyconfigs.addon
        found = {}
        for km in kc.keymaps:
            if km.name != "3D View":
                continue
            for kmi in km.keymap_items:
                if kmi.idname.startswith("rigo."):
                    direction = None
                    try:
                        direction = kmi.properties.direction
                    except Exception:  # noqa: BLE001
                        pass
                    found[(kmi.idname, kmi.type)] = (kmi.alt, direction)
        _mark(f"found={len(found)} items")
        delete_key_removed = ("rigo.erase_delete", "D") not in found
        _mark(f"box_erase_D_removed={delete_key_removed}")
        ok = delete_key_removed
        for (idname, key), (want_alt, want_dir) in _EXPECT.items():
            hit = found.get((idname, key))
            if hit is None:
                _mark(f"MISSING {idname} {key}")
                ok = False
                continue
            alt, direction = hit
            dir_ok = (want_dir is None) or (direction == want_dir)
            _mark(f"OK {idname} {key} alt={alt} dir={direction} dir_ok={dir_ok}")
            if alt != want_alt or not dir_ok:
                ok = False
        _mark(f"PASS={ok}")
    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
