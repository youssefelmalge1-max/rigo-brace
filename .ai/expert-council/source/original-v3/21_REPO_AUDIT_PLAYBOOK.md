# REPO AUDIT PLAYBOOK — 70% Complete Blender Add-on

## Objective

Perform a full forensic audit **before** adding the Pressure/Expansion Library. The goal is to avoid building the final 30% on hidden fragility.

## Phase 1 — Freeze the known-good baseline

Record:
- commit hash
- Blender version(s)
- OS
- Python version
- add-on version
- representative patient/test files
- known passing workflows
- known failing workflows

Create a baseline tag/branch.

## Phase 2 — Inventory

Generate:
- directory tree
- module dependency graph
- operator list
- panel/UI list
- PropertyGroup list
- handlers/timers
- geometry functions
- external libraries
- file formats
- helper objects/collections
- tests

## Phase 3 — Trace user workflows

Trace at least:
1. import scan
2. cleanup
3. create correction
4. edit correction
5. save style/library item
6. load/apply style
7. trimline
8. shell/thickness
9. export

For each click, identify code path and state mutation.

## Phase 4 — Find multiple sources of truth

Search for the same concept represented in multiple ways:
- region in Python object + vertex group + hidden mesh
- active style in Scene property + global variable
- patient identity in object name + custom property

Choose one canonical source and mark others derived/cache/view state.

## Phase 5 — Topology audit

List every operation that:
- adds/deletes vertices
- remeshes
- subdivides
- decimates
- booleans
- voxelizes
- joins/separates
- applies modifiers

For each, document which metadata becomes invalid.

## Phase 6 — Coordinate-space audit

For every geometry function mark expected space:
- object local
- world
- evaluated/deformed local
- surface-local

Look for accidental mixing, especially ray hits and stored anchors.

## Phase 7 — Blender-state audit

Search all `bpy.ops`.

For each call:
- why is operator required?
- mode?
- area?
- selection?
- active object?
- override context?
- undo?
- equivalent data API?

Do not mechanically remove operators; classify them.

## Phase 8 — Performance profiling

Profile representative small/medium/large scans.

Record:
- triangle count
- operation latency
- BVH build
- remesh
- deformation preview
- save/load
- memory

Identify repeated conversions and full-mesh loops.

## Phase 9 — Persistence audit

Close/reopen tests:
- correction regions
- library selections
- links to models
- IDs
- hidden helper objects
- parameters
- undo after load

Rename/duplicate objects and ensure relationships survive.

## Phase 10 — Geometry regression corpus

Create:
`tests/assets/geometry/`

Include synthetic and de-identified/non-patient representative meshes where permitted.

Track metrics, not screenshots only.

## Phase 11 — Expert review

Run orchestrator routing for each module:
- geometry_core → Ryan
- booleans → Howard/Alec
- fields/geodesic → Keenan
- procedural state → Jacques
- Blender adapter → Campbell
- clinical correction semantics → Rigo/Aubin

## Phase 12 — Architecture verdict

Classify code:

**KEEP**
Stable and tested.

**HARDEN**
Correct concept, needs tests/guardrails.

**REFACTOR**
Wrong coupling/representation but behavior can be preserved.

**REPLACE KERNEL**
Algorithm fundamentally unreliable.

**DEFER**
Not needed for pressure/expansion milestone.

## Required final report

1. Repository architecture map
2. user-tool inventory
3. geometry pipeline
4. state/source-of-truth map
5. top 20 risks
6. P0/P1 defects
7. pressure/expansion readiness
8. recommended refactors ranked by ROI
9. test debt
10. implementation sequence
