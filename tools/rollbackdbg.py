"""Exactly WHAT differs after a rejected Apply rolls the trimline back?

trimacceptmatrix reports "rejection restores the trimline bit-exactly" as FAIL
at arc (17,21). Two hypotheses were wrong already (selection baseline, metadata
key), so this stops guessing and prints the first differing field.
"""

import json
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import trimverify_ops  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\rollbackdbg_result.txt"
ARC = (17, 21)
TRIES = {"n": 0}
LINES = []


def _snapshot(curve):
    spline = curve.data.splines[0]
    return {
        "points": [
            (
                tuple(p.co), tuple(p.handle_left), tuple(p.handle_right),
                p.handle_left_type, p.handle_right_type,
                bool(p.select_control_point),
                bool(p.select_left_handle), bool(p.select_right_handle),
            )
            for p in spline.bezier_points
        ],
        "meta": {k: str(curve.get(k, "<absent>"))
                 for k in trimverify_ops._TRACKED_METADATA},
        "all_keys": sorted(curve.keys()),
    }


def _diff(before, after):
    if len(before["points"]) != len(after["points"]):
        LINES.append(f"  CONTROL COUNT {len(before['points'])} -> "
                     f"{len(after['points'])}")
        return
    for index, (b, a) in enumerate(zip(before["points"], after["points"])):
        if b != a:
            names = ("co", "handle_left", "handle_right", "hl_type",
                     "hr_type", "sel_co", "sel_hl", "sel_hr")
            for name, bv, av in zip(names, b, a):
                if bv != av:
                    LINES.append(f"  point {index}.{name}: {bv} -> {av}")
    for key in before["meta"]:
        if before["meta"][key] != after["meta"][key]:
            LINES.append(f"  metadata {key}: {before['meta'][key][:60]!r} -> "
                         f"{after['meta'][key][:60]!r}")
    added = set(after["all_keys"]) - set(before["all_keys"])
    removed = set(before["all_keys"]) - set(after["all_keys"])
    if added:
        LINES.append(f"  KEYS ADDED (not tracked): {sorted(added)}")
    if removed:
        LINES.append(f"  KEYS REMOVED: {sorted(removed)}")


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    try:
        prepare_reference_design()
        bpy.ops.rigo.auto_trimline()
        curve = bpy.data.objects["Rigo Trim Perimeter"]
        for index, point in enumerate(curve.data.splines[0].bezier_points):
            point.select_control_point = ARC[0] <= index <= ARC[1]
        before = _snapshot(curve)
        LINES.append(f"tracked metadata: {list(trimverify_ops._TRACKED_METADATA)}")
        LINES.append(f"keys before edit: {before['all_keys']}")

        bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode="SMOOTH_ARC")
        after_edit = _snapshot(curve)
        LINES.append("")
        LINES.append("AFTER EDIT (expected to differ):")
        _diff(before, after_edit)

        pending = str(curve.get(trimverify_ops.PENDING_KEY, ""))
        LINES.append("")
        LINES.append(f"pending snapshot present: {bool(pending)} "
                     f"({len(pending)} chars)")
        if pending:
            stored = json.loads(pending)
            LINES.append(f"  snapshot points={len(stored['points'])} "
                         f"metadata keys={sorted(stored.get('metadata', {}))}")

        try:
            result = bpy.ops.rigo.apply_trimline_edit()
            LINES.append(f"apply -> {result}")
        except RuntimeError as exc:
            LINES.append(f"apply -> REJECTED: {str(exc).strip()[:110]}")

        curve = bpy.data.objects["Rigo Trim Perimeter"]
        after_rollback = _snapshot(curve)
        LINES.append("")
        LINES.append("AFTER ROLLBACK vs BEFORE (should be empty):")
        _diff(before, after_rollback)
        LINES.append("  (no differences)" if before == after_rollback else "")
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
