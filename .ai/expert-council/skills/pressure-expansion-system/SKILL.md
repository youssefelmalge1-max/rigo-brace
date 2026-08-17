---
name: pressure-expansion-system
description: Use for any work on the reusable Pressure/Expansion correction library — pressure regions, expansion regions, correction templates and instances, reusable or saved correction styles, movable patches, correction libraries, patient-specific surface attachment, local region frames, presets, and Rodin-like reusable rectification workflows. Enforces the CorrectionTemplate-versus-CorrectionInstance split, forbids vertex indices as durable clinical identity, and convenes a fixed default council before any implementation.
---

# Pressure / Expansion Correction Library

The milestone feature: an orthotist picks a correction type from a library, places it on
a patient model, sees an immediate preview, and can move / rotate / scale / re-depth it
while it stays coherently attached to the surface — and the same template works on a
different patient with different topology.

This skill governs the **architecture**, not the implementation schedule. Nothing here
authorizes writing production code; route through `implementation-gate` first.

## Activate when the work involves

pressure region · expansion region · relief · correction template · reusable correction ·
correction style/preset · movable patch · correction library · correction instance ·
patient-specific surface attachment · local region frame · region transfer between scans ·
Rodin-like reusable rectification workflow.

## Do NOT activate when

- The task is a generic mesh/Blender defect with no correction-region semantics.
- The task is the existing pad library's UI wording only, with no data-model change.

## Convene this council (default, mandatory)

```text
expert-jacques-lucke          procedural definition / instance / evaluation architecture
expert-ryan-schmidt           editable representation, preview/commit lifecycle
expert-keenan-crane           surface attachment, intrinsic field, local frame
expert-olga-sorkine-hornung   deformation energy and transition quality
expert-manuel-rigo            clinical semantics (governor)
geometry-reliability          regression and release evidence
```

Add conditionally, on evidence:

```text
expert-bruno-levy             if a local 2D chart/parameterization is used
expert-mario-botsch           if topology changes or local remeshing is involved
expert-jonathan-shewchuk      if precision/degeneracy affects topology decisions
expert-campbell-barton        if modal tools, undo, or persistence lifecycle change
expert-sybren-stuvel          if module boundaries or add-on packaging change
expert-carl-eric-aubin        if any biomechanical claim (pressure/force/correction) appears
expert-mark-pauly             if optimization or manufacturability objectives appear
expert-howard-trickey         if Boolean/solid topology is proposed
expert-alec-jacobson          if dirty scans, folds, or inside/outside classification arise
```

## Non-negotiable architectural rules

### 1. Template ≠ Instance

**`CorrectionTemplate`** is reusable knowledge: `id` (UUID), `name`, `semantic_type`
(pressure|expansion|relief|transition), `device_concept`, `clinical_tags`,
`shape.family`, `influence.model`, `influence.falloff_curve`, `direction.policy`,
`constraints`, `schema_version`.

**`CorrectionInstance`** is a patient placement: `id`, `template_id`, `target_model_id`,
`attachment` (anchor triangle + barycentric + world fallback, local frame, optional
landmark frame), `boundary` (local 2D control points), `transform` (translate/rotate/
scale in local coordinates), `magnitude` (`depth_mm`, profile), `stack` (enabled, order),
`version` (attachment, evaluator).

A template must **not** be stored as patient-specific vertex IDs. An instance must
**not** be confused with the library definition.

### 2. Vertex indices are not clinical identity

If topology can change, raw vertex indices are not durable anchors. Vertex groups and
attributes are **cache/output**, never the source of truth. Candidate durable
attachments (choose on evidence, after inspecting the repository): barycentric
coordinates on reference triangles · closest surface point + normal + tangent frame ·
geodesic coordinates around a seed · anatomical landmark-relative frame · hybrid.

### 3. Direction is a policy, not a constant

Do not hard-code "pressure = inward normal, expansion = outward normal" as clinical
truth. Support: normal displacement · blended normal + clinical vector · user vector
projected/transported · future biomechanical solver.

### 4. Honest units

Label UI parameters **geometric depth / relief in mm** unless a validated mechanical
model computes real pressure. Any `pressure`/`force`/`correction` wording triggers
`expert-carl-eric-aubin`.

### 5. Expansion is not negative pressure

It is space for tissue migration, movement and breathing within a corrective system,
with its own clinically meaningful shaping and boundaries (`expert-manuel-rigo`).

### 6. Versioning

Never silently reinterpret old patient corrections. Instances keep the
`evaluator_version` they were created with; migration is offered, measured
(before/after deviation), and reversible.

## Workflow for any task under this skill

1. Read the repository's current state before choosing an implementation — this project
   already has `core/pad_library.py`, a painted-region system, and a documented
   `CorrectionRegion` model in `orthoblender-spine-skill/knowledge/correction_region_model.md`
   plus `docs/pressure_expansion_feature_spec.md`. Inspect before designing.
2. Classify the task: procedural architecture · surface attachment · surface
   mathematics · deformation · clinical semantics · reliability.
3. Convene the default council; add conditional experts on evidence.
4. Produce independent findings and cross-review (see `council-orchestrator`).
5. Choose the influence model by benchmark, not fashion: geodesic radial · local 2D
   parameter domain · constrained harmonic/biharmonic. The RFC's recommended prototype
   is a local 2D boundary with geodesic/tangent-space influence, benchmarked against a
   constrained biharmonic formulation.
6. Emit the verdict to `implementation-gate`; implement in layers (domain objects and
   serialization → attachment/frame → template library → preview evaluator →
   move/rotate/scale → commit/undo → persistence → regression suite → clinical metadata
   and warnings → performance). Do not start with automatic placement.

## Acceptance criteria for v1

Place a template in ≤3 interactions · move without visible detachment · cancel restores
geometry exactly · save/reopen preserves instance parameters · works on two scans with
different topology · no triangle flips within the supported depth range on the benchmark
set · interactive preview latency on representative scans · severe geometry failures
raise explicit errors rather than committing silently.

## Explicit non-goals for v1

Automatic Rigo classification · predicted Cobb correction · pressure in kPa · tissue
mechanics · auto-placing all pads from the scan · copying proprietary vendor assets or
algorithms · requiring identical topology between patients.

## Output contract

Use the `council-orchestrator` verdict format, plus:

```text
Domain Model Delta        (template fields / instance fields added or changed)
Attachment Strategy       (with the falsifying experiment that chose it)
Evaluator Version Impact  (migration plan for existing cases)
Clinical Metadata         (pairing, applicability, sagittal, review flags)
```

## Deep Reference

For the full RFC — domain schemas, influence-model candidates A/B/C, surface-local
coordinate construction, move/rotate/scale UX, correction stack semantics, library
format, versioning, geometry metrics, performance architecture, and the complete test
suite — read:

`references/architecture-rfc.md`

Read it before any design decision on this feature; skip it for wording-only changes.
