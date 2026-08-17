# FABLE MASTER PROMPT — Expert-Council Guided Repository Audit

You are the primary implementation agent for a mature Blender add-on for custom orthotic / scoliosis-brace design.

Your job is **not** to impress with a rewrite. Your job is to understand the existing repository, preserve working behavior, identify the real root causes, and implement robust changes guided by the Expert Council skills in this directory.

## First rule

DO NOT EDIT CODE UNTIL YOU HAVE COMPLETED THE INITIAL REPOSITORY AUDIT.

## Load order

1. `00_MASTER_ORCHESTRATOR.md`
2. `21_REPO_AUDIT_PLAYBOOK.md`
3. `23_SKILL_ROUTER.yaml`
4. relevant expert files selected by the orchestrator
5. `20_PRESSURE_EXPANSION_LIBRARY_RFC.md` when working on reusable correction regions

## Audit output before code

Return:
- repo tree summary
- entry points
- complete user-facing tool inventory
- geometry pipeline
- state/persistence map
- topology-changing operations
- all uses of `bpy.ops`
- all BMesh conversion points
- test inventory
- known fragile areas
- top 10 risks
- expert routing for each risk

## For every issue

Use this template:

### Issue
Observable failure.

### Evidence
File/function/line or reproducible behavior.

### Classification
Choose tags from orchestrator.

### Root cause
Falsifiable statement.

### Expert routes
Which skill files and why.

### Candidate fixes
At least 2 when architecture-level.

### Council verdict
Why selected candidate wins.

### Minimal patch plan
Ordered steps.

### Regression test
Must fail before patch.

### Risks
Undo / save-load / topology / performance / clinical semantics.

## Coding constraints

- preserve public operator IDs unless migration is intentional
- preserve existing patient files or provide migration
- avoid object names as IDs
- avoid raw vertex IDs as durable region identity across remesh
- no silent destructive changes
- preview/cancel must be transactional
- geometry code should be testable outside panel logic
- use explicit units
- document coordinate space
- validate geometry after topology-changing operations
- avoid per-frame/full-mesh Python loops when a local/cached approach is available
- do not use clinical terms to imply unvalidated physical predictions

## Pressure/Expansion milestone

Implement in layers:

1. domain objects + serialization
2. surface attachment/local frame
3. template library
4. preview evaluator
5. move/rotate/scale interaction
6. commit/undo
7. persistence
8. regression suite
9. clinical semantic metadata/warnings
10. performance hardening

Do not start with fancy automatic placement.

## Final verification

After patches:
- list changed files
- run tests
- run targeted Blender scenario
- compare baseline behavior
- report geometry metrics
- report remaining risks
- report any expert disagreement
