---
name: implementation-gate
description: Use before and after any substantial code change in this repository — the mandatory pre-implementation contract (evidence, current architecture, root cause, council routing, candidate solutions, council verdict, minimal patch plan, regression test, risk analysis) and the post-implementation verification protocol (install, run tests, compare geometry metrics, report changed files and residual risk). Activate whenever an edit touches geometry, Blender state, persistence, clinical semantics, or public operator IDs.
---

# Implementation Gate — Primary Implementation Agent Protocol

The **Primary Implementation Agent** is whichever agent is about to edit code (this
concept was called "Fable" in the v3 bundle; the two names are interchangeable). This
skill is the gate it must pass through.

Your job is not to impress with a rewrite. It is to understand the existing repository,
preserve working behavior, find the real root cause, and implement the smallest robust
change — guided by the council verdict.

## Activate when

- A change touches geometry, mesh topology, Blender state, persistence, saved-case
  schema, clinical semantics, or a public operator `bl_idname`.
- A council verdict exists and must become a patch.
- Any P0/P1 fix.

## Do NOT activate when

- Documentation, comments, or a label string with no behavioral effect.
- A single-line guard in a well-understood path with an existing test.

## First rule

**Do not edit code until the pre-implementation contract below is complete.** If the
evidence is missing, gather it. If the root cause is not falsifiable, keep investigating.

## Pre-implementation contract (all nine sections, in order)

```text
1. Evidence              exact files / classes / functions producing the behavior
2. Current Architecture  how data actually flows today
3. Root Cause            one falsifiable sentence
4. Council Routing       which expert skills were activated and why
5. Candidate Solutions   at least two when the change is architectural
6. Council Verdict       why the chosen candidate wins; why the others were rejected
7. Minimal Patch Plan    ordered steps, files, and the boundary of the change
8. Regression Test       must fail before the patch and pass after
9. Risk Analysis         undo · save/load · topology · performance · clinical semantics
```

Then implement. Then verify.

## Coding constraints (non-negotiable)

- Preserve public operator IDs unless the migration is intentional and stated.
- Preserve existing patient files, or provide and test a migration.
- Never use object names as durable IDs.
- Never use raw vertex indices as durable region identity across remeshing.
- No silent destructive changes; preview/cancel must be transactional.
- Geometry code must be testable outside panel logic.
- Use explicit units and document the coordinate space (repo: 1 BU = 1 m, UI in mm).
- Validate geometry after any topology-changing operation.
- Avoid per-frame or full-mesh Python loops where a local/cached approach exists.
- Do not use clinical terms to imply unvalidated physical predictions.
- Mutating operators carry `bl_options = {"REGISTER", "UNDO"}`.

## Repository-specific verification (this add-on)

1. `./install.ps1` — **required** after editing anything under `rigo_brace/` or the
   template. Tests exercise the *installed* copy; skipping this tests stale code.
2. Run the relevant GUI test:
   `& "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --app-template rigo_brace --python tools\<name>test.py`
3. Read `<name>_result.txt` in the project root — stdout is not the result.
4. Add or extend a `tools/*test.py` for the specific defect.
5. Update `orthoblender-spine-skill/knowledge/` (learned_memory, decision_log,
   error_log on bugs, code_provenance on any reuse).

## Post-implementation report

```text
Changed Files
Tests Run + Results       (paste the pass/fail lines from *_result.txt)
Geometry Metrics          (baseline vs post-change)
Behavior Comparison       (against the pre-change baseline)
Residual Risks
Expert Disagreements      (any unresolved council dissent)
Follow-up Work            (labelled DEFER, with why)
```

Report failures honestly: if a test fails, show the output; if a step was skipped, say so.

## Escalation

Stop and return to `council-orchestrator` if implementation reveals that the root cause
was wrong, the minimal patch cannot hold the invariant, or a second canonical source of
truth is discovered mid-patch.

Stop and ask the orthotist if the change would encode a clinical decision, alter
clinical semantics, or require choosing between clinically meaningful alternatives.

## Deep Reference

For the full original implementation-agent protocol — audit output requirements, the
per-issue template, the layered Pressure/Expansion implementation order, and the final
verification checklist — read:

`references/implementation-protocol.md`
