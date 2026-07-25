# QA & Test Protocol

Two layers: **automated** (the real harness) and **manufacturing/clinical QA** (gates
before export).

## Automated tests (the real harness)
GUI Blender only — the extension system is absent under `--background`. Pattern: each
`../tools/<name>test.py` registers a `bpy.app.timers` callback that retries until the UI
is registered, runs checks, writes `<name>_result.txt` to the repo root, and quits
Blender itself. **Tests run the INSTALLED copy** → run `../install.ps1` first.

Run one:
```
& "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --app-template rigo_brace --python tools\<name>test.py
```
Then read `<name>_result.txt` (look for `PASS=True` / `ALL_PASS=True`).

Current tests: selftest (registration), selecttest, paintkeeptest, painttooltest,
applyunitstest, bendtest, stretchtest, planestest, padtest, padshapetest, viewtest,
historytest. Headless geometry probes: bendexp, stretchexp.

Rule: after editing `rigo_brace/`, re-install, run selftest + the affected feature test;
keep them green. Add a new `*test.py` for every new operator/module.

## Mandatory user verification handoff

Every reported test result must include a short user guide containing:

1. **Readiness:** `READY FOR USER CHECK`, `PARTIAL / INFRASTRUCTURE ONLY`, or
   `NOT READY`.
2. **Restart requirement:** whether Blender/add-on reload is required.
3. **Exact path:** workflow stage, panel section, and buttons to press.
4. **Fixture:** which scan/file to use and any unit/orientation prerequisites.
5. **Expected result:** what must visibly appear or change.
6. **Pass checks:** simple observations or measurements the orthotist can verify.
7. **Known limits:** anything the test did not prove.

Automated registration, JSON migration, or one-time geometry tests must not be reported
as proof that a complete user workflow works. A feature is `READY FOR USER CHECK` only
after its exact UI sequence has been run in a fresh installed Blender session and visually
inspected. Clinical correctness always remains the orthotist's decision.

## Manufacturing / export QA gates (per design, before export)
- [ ] Units = mm, scene METRIC.
- [ ] Orientation correct (upright, facing front, on floor).
- [ ] Manifold + watertight (no non-manifold edges, no unintended holes).
- [ ] Minimum wall thickness met everywhere (manufacturing_constraints.md).
- [ ] No sharp/degenerate edges; trim edges flared.
- [ ] Mesh density reasonable for the printer; no self-intersections.
- [ ] Ventilation/slot cuts clean (manifold after boolean).
- [ ] Pressure zones preserved, expansion rooms preserved.
- [ ] Strap/ring/component positions valid (not floating).
- [ ] Deviation vs original scan within the intended correction envelope.
- [ ] File named per convention; version saved in design history.

## Clinical gate
See clinical_safety_protocol.md — orthotist review is mandatory before fabrication.
Software reports and measures; it does not approve.
