# CLAUDE.md — OrthoBlender Spine Skill

Guidance for an AI agent operating the rigo_brace orthotics project under the
OrthoBlender Spine Skill discipline.

## Two CLAUDE.md files — don't confuse them
- **`../CLAUDE.md`** (repo root) — the **add-on code** conventions (build/install/test
  commands, architecture of `rigo_brace/`). The Claude Code harness auto-loads it. Keep
  it at the root; do not move it.
- **This file** — the **skill/process** layer: how to behave, what to read/update.

## Before doing anything
Read, in order: `SKILL.md`, then `knowledge/learned_memory.md`,
`knowledge/decision_log.md`, `knowledge/error_log.md`, `knowledge/code_provenance.md`,
`knowledge/feature_backlog.md`, `knowledge/roadmap.md`, and the active
`knowledge/requirements_*.md`.

## How to work
1. Smallest safe change; explain the patch plan; implement ONE module.
2. After editing `../rigo_brace/` or the template, run `../install.ps1` BEFORE tests —
   tests exercise the INSTALLED copy.
3. Add/extend a `../tools/*test.py` GUI test; read its `*_result.txt`.
4. Update `knowledge/` (learned_memory + decision_log; error_log on bugs; provenance on
   any reuse). Never finish without writing what was learned.
5. Separate, when explaining: clinical concept · Blender implementation · code task ·
   test task. The user is an orthotics professional, not a software engineer.

## Hard rules
- License/provenance discipline (see SKILL.md §rules + `knowledge/code_provenance.md`).
- Clinical safety: guide, never prescribe; `requires_orthotist_review` on every template.
- Keep working tools; remove noise only after a replacement passes tests.

## Current state
The brace UI is being rebuilt into a uFit-style guided workflow (see the plan file +
`knowledge/requirements_v1.md` + roadmap). Shipped: View panel (Patch 1), Workflow shell
+ design history (Patch 2), Clean stage (Patch 3), Blender MCP live loop (DEC-0014),
issue-fix wave (DEC-0015: remold 5.0 fix, patient-keyed history; `../issues.md` is the
living status board). Next: Patch 4 — combined Guided(mm)+Free sculpt on the
CorrectionRegion model (`knowledge/correction_region_model.md`).
