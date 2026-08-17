---
name: geometry-reliability
description: Cross-cutting reliability gate — regression fixtures that fail before a fix, the geometry benchmark corpus, numerical geometry comparison (Hausdorff-style deviation, max and p95 displacement, area, volume, topology metrics, landmark drift), determinism and reproducibility, p50/p95 performance profiling, save/load and undo/redo verification, migration safety for old patient cases, and release gates. Activate automatically for every P0 and P1 defect, every geometry-kernel change, every migration, and every release.
---

# Geometry Reliability — Regression, Benchmark & Release Gate

**Meta-skill, not a person.** This lens exists so recommendations become *measurable*.
For a medical-adjacent CAD add-on, a visually plausible result is not evidence.

## Role

Cross-cutting Reliability, Regression & Performance Governor.

## Activate when (automatic)

- Any **P0** (data/clinical corruption) or **P1** (crash, non-manifold, repeatable
  wrong geometry, undo breakage, unpredictable preset movement).
- Any change to a geometry kernel, evaluator, or persistence schema.
- Any migration that could reinterpret existing patient cases.
- Release preparation.
- Whenever another expert's recommendation needs a falsifying experiment.

## Do NOT activate when

- A P3 cosmetic change with no geometry, state, or schema effect.
- Documentation-only work.

## Task classification

`TESTING` · `PERFORMANCE`. Sub-classify: missing failing-before test · unmeasured
geometry change · determinism gap · persistence gap · performance regression ·
migration risk.

## Core doctrine

1. **No severe bug is fixed without a failing-before regression.** Screenshots are
   supporting evidence, never the test.
2. **Compare geometry numerically**: nearest-surface/Hausdorff-style deviation, max and
   p95 displacement, surface area, volume, topology metrics, boundary drift, landmark drift.
3. **Performance is measured on representative workloads** — small / median / heavy scan,
   recorded as p50 and p95.
4. **Tests are layered**: unit · geometry kernel · Blender integration · save/load ·
   interaction · clinical-semantic rules.

## Workflow

1. Reproduce the defect as a script that **fails before** the change.
2. Capture baseline metrics on the relevant fixtures before touching anything.
3. Define the pass/fail gate numerically, in advance, with the metric and threshold named.
4. Run the golden workflow end to end: load scan → create region → move/rotate/scale →
   undo/redo → save → close/reopen → continue editing → remesh where supported → export →
   compare visible against exported result.
5. Re-measure after the change; report the delta, not an impression.
6. Record any unresolved risk in an explicit ledger.

Repository note: tests here are GUI Blender scripts under `tools/` that write
`<name>_result.txt` to the project root; they exercise the **installed** add-on, so
`./install.ps1` must run first. Headless `--background` runs are fine for pure geometry
probes but cannot load the extension/app-template.

## Benchmark corpus (BraceGeo)

**Synthetic:** plane, sphere, cylinder, saddle, thin shell, two close surfaces.
**Pathological:** holes, non-manifold edge, flipped normals, duplicate faces, degenerate
triangle, self-intersection, density variation, disconnected island.
**Representative torso-like:** mild asymmetry, strong rib prominence, concavity,
high/low density, short trunk, difficult curvature — de-identified or synthetic only,
consistent with the project's clinical-data governance (patient scans are gitignored).

## Pressure/Expansion test set

Serialization roundtrip · same template on different topology · movement over curvature ·
overlapping regions · reorder · disable/enable · evaluator-version migration · exact
cancel · undo/redo · save/reopen · transfer to a second model · clinical-warning persistence.

## Mandatory questions

1. What test fails today and passes after the fix?
2. What is the metric, the fixture, and the threshold?
3. Is the result deterministic across runs and machines?
4. Does undo restore mesh **and** domain state? Does save/reopen preserve both?
5. What is p50/p95 on the heavy scan, before and after?
6. Could this change silently alter an existing saved case?

## Output contract

```text
Test Matrix
Fixtures
Baseline Metrics
Post-Change Metrics
Pass/Fail Verdict
Performance Analysis     (p50/p95, per stage)
Unresolved Risk Ledger
```

## Release gate — fail the release if

A P0 is open · a P1 is unmitigated · geometry validity regresses · save/load loses
semantic state · undo fails to restore mesh + domain state · a migration silently
changes old patient geometry · an agreed performance gate is materially exceeded.

## Escalation / handoff

Back to whichever expert owns the failing metric; `implementation-gate` for the
verification step of a patch; `council-orchestrator` when a metric contradicts the
accepted root cause.

## Deep Reference

If the issue requires corpus design, gate definition, or deep verification planning, read:

`references/expert-context.md`

Do not read this file for trivial issues.
