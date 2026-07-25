# Test: Import / Export

Automated: `tools/selftest.py` (registration). No dedicated io test yet — add
`tools/iotest.py` when export QA lands (Patch 8).

Test name: Import STL/OBJ → Export brace
Feature: io_ops (import_scan, export_brace)
Input: Brace Sample.stl (and an .obj)
Steps:
1. File stage → Import Scan → pick the file.
2. Confirm it loads, becomes the active/scan object, units look right after Apply Units.
3. (End of flow) Export Brace → choose folder → export.
Expected result: scan imports at correct mm size; exported STL re-imports identical,
manifold, mm units.
Failure signs: wrong scale, missing object, non-manifold export, wrong units.
Clinical risk if failed: wrong-size or unprintable brace.
Files involved: rigo_brace/operators/io_ops.py
