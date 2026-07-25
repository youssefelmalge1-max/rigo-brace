# Test: Scan Cleanup

Automated: `tools/scancleantest.py`, `tools/applyunitstest.py`,
`tools/paintkeeptest.py`, `tools/painttooltest.py`.

Test name: Clean a raw scan
Feature: scan_ops (apply_units, recenter, fill_holes, erase) + select_ops (paint)
Input: Brace Sample.stl
Steps:
1. Apply Units (mm) → model resizes and the view re-frames (does NOT disappear — LM-0001).
2. Recenter & Drop to Floor → upright, on z=0.
3. Box Erase / paint-select stray islands → delete; Fill Holes.
4. Paint a region across several strokes (Shift adds, Ctrl removes) → region accumulates
   (LM-0002), does not reset.
Expected result: clean, centred, hole-free mesh; selection accumulates.
Failure signs: model vanishes after units; selection resets each stroke; holes remain.
Clinical risk if failed: bad base geometry propagates to the whole brace.
Files involved: scan_ops.py, mesh_ops.py, select_ops.py
