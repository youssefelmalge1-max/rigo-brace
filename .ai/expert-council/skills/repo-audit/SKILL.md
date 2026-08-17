---
name: repo-audit
description: Use for structured forensic audits of this add-on before large work — mapping an unfamiliar subsystem, inventorying operators/panels/PropertyGroups/handlers, tracing a user workflow click-to-code, finding multiple sources of truth for one concept, auditing topology-changing operations and coordinate spaces, auditing every bpy.ops call and persistence path, profiling representative scans, and producing a KEEP/HARDEN/REFACTOR/REPLACE-KERNEL/DEFER verdict. Use scoped audits for one subsystem; run the full playbook only before a milestone or a systemic investigation.
---

# Repository Audit

Forensic audit discipline for a mature add-on. The purpose is to avoid building the
remaining work on hidden fragility — **and to avoid a giant audit for a five-line bug**.

## Activate when

- Working in an unfamiliar subsystem for the first time.
- A major architectural change or a feature touching several layers is proposed.
- A new agent or contributor needs a reliable map.
- Bugs are systemic rather than local (the same class of failure keeps reappearing).
- Before a milestone such as the Pressure/Expansion library.
- Periodic repository-health checks.

## Do NOT activate when

- The task is a localized bug with a known reproduction and a known file.
- The task is cosmetic, documentation, or a single-parameter change.
- A previous audit of the same scope is still current — read it instead
  (`ADDON_FEATURE_AUDIT_*.md`, `PROJECT_AUDIT_DECISION_MAP.md`,
  `TRIMLINE_TEMPLATE_AUDIT_*.md`, `orthoblender-spine-skill/knowledge/current_addon_audit.md`).

## Choose the scope first (mandatory)

| Scope | When | Phases |
|---|---|---|
| **Micro** | one operator or one bug | 3, 6, 7 for the touched path only |
| **Subsystem** | one pipeline area (e.g. trimline, pads, remold) | 2, 3, 4, 5, 6, 7, 12 |
| **Milestone** | before a large feature or release | all 12 |

State the chosen scope in the output. A micro audit that grows into a full audit
without saying so wastes the user's context and time.

## Phase list (full playbook)

1. **Freeze the baseline** — commit hash, Blender version, OS, Python, add-on version,
   representative test files, known-passing and known-failing workflows.
2. **Inventory** — directory tree, module dependency graph, operators, panels,
   PropertyGroups, handlers/timers, geometry functions, external libraries, file
   formats, helper objects/collections, tests.
3. **Trace user workflows** — import scan → cleanup → create correction → edit
   correction → save style → apply style → trimline → shell/thickness → export.
   For each click record the code path and the state mutation.
4. **Find multiple sources of truth** — the same concept as a Python object *and* a
   vertex group *and* a hidden mesh; active style in a Scene property *and* a global.
   Choose one canonical source; mark the rest derived/cache/view.
5. **Topology audit** — every operation that adds/deletes vertices, remeshes,
   subdivides, decimates, booleans, voxelizes, joins/separates, or applies modifiers,
   and what metadata each invalidates.
6. **Coordinate-space audit** — object local / world / evaluated / surface-local per
   geometry function; look for mixing, especially in ray hits and stored anchors.
   (Repo convention: 1 BU = 1 m, UI in mm, converted with `* 0.001`.)
7. **Blender-state audit** — every `bpy.ops` call: why an operator, what mode/area/
   selection/active object it needs, whether context is overridden, undo behavior, and
   the data-API equivalent. Classify; do not mechanically remove.
8. **Performance profiling** — small/medium/large scans: triangle count, operation
   latency, BVH build, remesh, deformation preview, save/load, memory. Find repeated
   conversions and full-mesh Python loops.
9. **Persistence audit** — close/reopen with corrections, library selections, links,
   IDs, hidden helpers, parameters, undo after load; rename and duplicate objects and
   confirm relationships survive.
10. **Geometry regression corpus** — synthetic and de-identified fixtures; track
    metrics, not screenshots. (Patient scans are gitignored here.)
11. **Expert review** — route each module through `council-orchestrator`:
    geometry core → Ryan; booleans → Howard/Alec; fields → Keenan; procedural state →
    Jacques; Blender adapter → Campbell; clinical semantics → Rigo/Aubin.
12. **Architecture verdict** — label every finding:
    `KEEP` (stable and tested) · `HARDEN` (right concept, needs tests/guardrails) ·
    `REFACTOR` (wrong coupling, behavior preservable) · `REPLACE KERNEL` (algorithm
    fundamentally unreliable) · `DEFER` (not needed for the current milestone).

## Output contract

```text
Scope Declared            (micro / subsystem / milestone)
1. Repository architecture map
2. User-tool inventory
3. Geometry pipeline
4. State / source-of-truth map
5. Top risks (ranked)
6. P0/P1 defects
7. Milestone readiness (e.g. pressure/expansion)
8. Recommended changes ranked by ROI, each labelled KEEP/HARDEN/REFACTOR/REPLACE KERNEL/DEFER
9. Test debt
10. Implementation sequence
```

## Rules

- Audit findings are evidence, not permission to refactor. Feed them to
  `council-orchestrator`, then to `implementation-gate`.
- Do not modify production code during an audit.
- Record what you learned in the project's knowledge base
  (`orthoblender-spine-skill/knowledge/`) rather than only in the chat.

## Deep Reference

For the full phase-by-phase playbook with the original checklists, read:

`references/audit-playbook.md`

Do not read it for a micro-scope audit.
