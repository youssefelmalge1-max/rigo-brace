# AGENTS.md — control tower for coding agents

Provider-neutral instructions for OpenAI Codex / GPT coding agents and any other agent
that reads `AGENTS.md`. Claude Code readers: `CLAUDE.md` carries the same policy plus
the build/test details; both point at the same canonical skills.

## Project

**Rigo Brace Designer** — a Blender 5.x add-on plus application template for orthotists
designing Rigo-Chéneau spinal braces. Pure Python against `bpy`. Two installable pieces:
`rigo_brace/` (the extension) and `rigo_brace_template/` (the application template).

The project is mature and clinical-adjacent. Preserve working behavior.
Prefer `Preserve · Understand · Harden · Extend` over `Rewrite`.

## Build / test essentials

- Build zip: `python build.py` → `rigo_brace.zip`
- Install the dev copy: `./install.ps1` (PowerShell, project root)
- Run a test (GUI Blender required; `bl_pkg` does not exist under `--background`):

  ```powershell
  & "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --app-template rigo_brace --python tools\selftest.py
  ```

  Each `tools/*test.py` writes `<name>_result.txt` to the project root — read the file;
  stdout is not the result.

**Critical gotcha:** tests exercise the *installed* add-on. After editing anything under
`rigo_brace/` or the template, run `./install.ps1` **before** testing.

Conventions: 1 Blender unit = 1 m, all UI values in mm (`* 0.001`); mutating operators
carry `bl_options = {"REGISTER", "UNDO"}`; operator idnames use the `rigo.` prefix;
`register()` order is `core → operators → ui → keymaps`.

## Mandatory workflow for substantial changes

```text
Investigate → classify → route experts → identify root cause →
minimal plan → regression test → implement → verify
```

Never `guess → rewrite → hope`. Gather repository evidence before proposing a fix, and
pass through `implementation-gate` before editing code.

## Expert Council

For any non-trivial problem involving geometry, mesh topology, Blender internals,
procedural architecture, numerical robustness, correction regions, scoliosis-brace
geometry, performance or reliability, **start at the orchestrator**:

```text
.ai/expert-council/skills/council-orchestrator/SKILL.md
```

Rules:

- **Progressive disclosure.** Load only the routed skills' `SKILL.md`. Load a skill's
  `references/` only when the task genuinely needs deep context.
- **Never** load `.ai/expert-council/source/original-v3/ALL_EXPERT_CONTEXT_COMBINED.md`
  or `EXPERT_SKILLS_01_15_COMBINED.md`. They are archival bundles and defeat routing.
- **Default council size:** 1 primary + 1–3 secondary, plus `geometry-reliability` for
  P0/P1 or geometry-kernel changes, plus `expert-manuel-rigo` when clinical semantics
  are involved.
- **Keywords are hints, not routes.** Classify the actual root problem first (see
  `.ai/expert-council/ROUTING.md`).
- **Lenses, not people.** Each expert skill is a public-work-derived engineering profile.
  Never claim the named person reviewed this repository or gave private advice.

Machine-readable index: `.ai/expert-council/REGISTRY.yaml`.
Adapters for skill-directory scanners: `.codex/skills/` (and `.claude/skills/`).

## Available Expert Skills

- **council-orchestrator** — Routes complex repository/geometry/clinical problems to the
  relevant expert council, runs cross-review, emits one verdict.
  Path: `.ai/expert-council/skills/council-orchestrator/SKILL.md`

- **expert-ryan-schmidt** — Interactive geometry systems, editable mesh representation,
  remeshing with constraints, spatial structures, SDF/implicit workflows, preview/commit
  tool architecture.
  Path: `.ai/expert-council/skills/expert-ryan-schmidt/SKILL.md`

- **expert-howard-trickey** — Boolean and solid-geometry robustness: union/difference/
  intersection, coplanar overlap, shards and non-manifold output — and whether Boolean is
  the right abstraction at all.
  Path: `.ai/expert-council/skills/expert-howard-trickey/SKILL.md`

- **expert-jacques-lucke** — Procedural and declarative architecture: correction stacks,
  dependency graphs, template vs instance, caching/invalidation, schema versioning and
  migration.
  Path: `.ai/expert-council/skills/expert-jacques-lucke/SKILL.md`

- **expert-keenan-crane** — Intrinsic surface geometry: geodesic distance, curvature,
  Laplacians, tangent frames, parallel transport, surface fields, signed distance on
  imperfect scans.
  Path: `.ai/expert-council/skills/expert-keenan-crane/SKILL.md`

- **expert-alec-jacobson** — Robust geometry processing on dirty scans: self-intersection,
  inside/outside and winding numbers, mesh validation, fold and inversion detection,
  pathological-mesh corpora.
  Path: `.ai/expert-council/skills/expert-alec-jacobson/SKILL.md`

- **expert-campbell-barton** — Blender platform integration: bpy/bmesh, operator context
  and modes, modal lifecycle, depsgraph, undo, registration and data-block ownership.
  Holds veto over unsafe Blender-state architecture.
  Path: `.ai/expert-council/skills/expert-campbell-barton/SKILL.md`

- **expert-mark-pauly** — Computational design and fabrication: design variables,
  objectives and constraints, manufacturability, optimization readiness; refuses premature
  optimization.
  Path: `.ai/expert-council/skills/expert-mark-pauly/SKILL.md`

- **expert-carl-eric-aubin** — Patient-specific brace biomechanics, FEM and simulated
  contact; audits every pressure/force/predicted-correction claim. Holds veto over
  unvalidated biomechanical claims.
  Path: `.ai/expert-council/skills/expert-carl-eric-aubin/SKILL.md`

- **expert-manuel-rigo** — Clinical Geometry Governor: Rigo-Chêneau contact and expansion
  areas, counterforces, curve-pattern applicability, sagittal protection, clinical
  template metadata. Holds clinical veto.
  Path: `.ai/expert-council/skills/expert-manuel-rigo/SKILL.md`

- **expert-jonathan-shewchuk** — Floating-point robustness: geometric predicates,
  orientation tests, epsilon and scale coupling, degeneracy, constrained triangulation,
  mesh quality. Holds veto over unexplained tolerances in topology decisions.
  Path: `.ai/expert-council/skills/expert-jonathan-shewchuk/SKILL.md`

- **expert-olga-sorkine-hornung** — Deformation quality: ARAP and variational energies,
  handle and constraint models, transition continuity, detail preservation, rings and
  spikes at region borders.
  Path: `.ai/expert-council/skills/expert-olga-sorkine-hornung/SKILL.md`

- **expert-bruno-levy** — Surface parameterization: LSCM-style local 2D charts, mapping a
  template boundary from 2D to the patient surface, distortion and foldover control.
  Path: `.ai/expert-council/skills/expert-bruno-levy/SKILL.md`

- **expert-mario-botsch** — Polygon mesh processing: half-edge and adjacency structures,
  decimation and remeshing quality, valence and aspect-ratio health, topology vs geometry.
  Path: `.ai/expert-council/skills/expert-mario-botsch/SKILL.md`

- **expert-sybren-stuvel** — Blender Python maintainability: add-on package architecture,
  module boundaries, registration/reload discipline, error paths, duplicated abstractions,
  auditability of AI-generated code.
  Path: `.ai/expert-council/skills/expert-sybren-stuvel/SKILL.md`

- **geometry-reliability** — Cross-cutting reliability gate: regression fixtures, benchmark
  corpus, geometry metrics, determinism, p50/p95 performance, save/load and undo
  verification, release gates. Auto-activates for every P0/P1, geometry-kernel change,
  migration and release.
  Path: `.ai/expert-council/skills/geometry-reliability/SKILL.md`

- **repo-audit** — Scoped forensic audit of the add-on: inventory, workflow tracing,
  source-of-truth map, topology/coordinate-space/state audits, and
  KEEP/HARDEN/REFACTOR/REPLACE-KERNEL/DEFER verdicts.
  Path: `.ai/expert-council/skills/repo-audit/SKILL.md`

- **pressure-expansion-system** — Architecture governor for the reusable Pressure/Expansion
  correction library: template vs instance, durable surface attachment, honest units, and
  the mandatory default council.
  Path: `.ai/expert-council/skills/pressure-expansion-system/SKILL.md`

- **implementation-gate** — Pre-implementation contract (evidence, architecture, root
  cause, routing, candidates, verdict, patch plan, regression test, risks) and
  post-implementation verification protocol for the Primary Implementation Agent.
  Path: `.ai/expert-council/skills/implementation-gate/SKILL.md`

## Clinical boundary

Never infer clinical truth from geometry alone. A geometric offset is not physical
pressure — label it `depth_mm` unless a validated mechanical model says otherwise. A
reusable Rigo correction must preserve clinical semantics: pairing, counterforce,
sagittal constraints, classification applicability. The orthotist makes clinical
decisions; the software assists.

## Durable identity

Object names and raw vertex indices are not durable identities. `CorrectionTemplate`
(reusable knowledge) and `CorrectionInstance` (patient placement) are distinct, and
neither may depend on patient-specific vertex IDs across topology changes.

## Never do these

- Preload all 15 expert contexts, or load the combined archival bundles.
- Impersonate the real experts or claim they reviewed this repository.
- Implement from keyword routing alone, or rewrite the add-on without evidence.
- Use object names or vertex indices as persistent identity.
- Silently modify patient-critical geometry, or alter old saved cases after an evaluator change.
- Call geometric depth "pressure" without biomechanical validation.
- Introduce clinical automation without clinical-governor review.
- Skip regression tests after severe geometry bugs.
- Mix panel/UI code with the geometry kernel for convenience.

## Existing process layer

`orthoblender-spine-skill/` is the project's operating contract and knowledge base:
read `orthoblender-spine-skill/SKILL.md` and its `knowledge/` files before working, and
update `learned_memory.md`, `decision_log.md`, `error_log.md` and `code_provenance.md`
afterwards. The expert council is review infrastructure layered above that loop, not a
replacement for it.

## Validating this infrastructure

```bash
python .ai/expert-council/tools/validate_skills.py
python .ai/expert-council/tools/test_routing.py
python .ai/expert-council/tools/sync_adapters.py --check
```
