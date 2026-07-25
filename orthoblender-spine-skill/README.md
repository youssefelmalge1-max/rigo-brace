# OrthoBlender Spine Skill

A knowledge system + operating contract for building **rigo_brace** — a Blender-based
orthotics design platform, spinal/Rigo-Chêneau first, expandable to other devices.

This folder is **documentation and process**, not add-on code. The add-on itself lives in
`../rigo_brace/` (the installable extension) and `../rigo_brace_template/`.

## What's here
- `SKILL.md` — the operating contract (identity, rules, memory formats, module map,
  session loop). Read it first.
- `CLAUDE.md` — how an AI agent should operate this project (points to SKILL.md + the
  add-on's own `../CLAUDE.md` for code conventions).
- `knowledge/` — the persistent memory: audits, provenance, decisions, lessons, errors,
  requirements, roadmap, clinical rules, capability maps, QA & safety protocols, and the
  pressure/expansion + brace/insole template libraries.
- `templates/` — fill-in templates for audits, provenance, QA/bug reports, plans, and the
  clinical YAML libraries.
- `scripts/` — helper utilities (inspect add-on structure, list operators, mesh metrics,
  run tests, generate the feature matrix).
- `tests/` — manual test checklists per feature area (the automated tests are the real
  `../tools/*test.py` GUI scripts).
- `docs/` — user workflow, developer architecture, module design notes.

## Operating loop (every session)
Read `knowledge/` → inspect architecture → smallest safe change → explain plan →
implement one module → test (`./install.ps1` then a `tools/*test.py`) → update memory →
summarize. Never finish a task without writing what was learned.

## Licensing
rigo_brace is GPL-3.0-or-later (user-owned). Reference apps uFit (GPL-3.0) and WASP-Med
(GPL-2-or-later) are GPL-compatible; any reused/ported unit keeps its GPL header and gets
a `knowledge/code_provenance.md` entry. Proprietary references (LeoSpinal, Rodin4D) are
learn-from-only.

## Clinical disclaimer
This platform **guides** design; the final clinical decision belongs to the orthotist.
Nothing here is an automatic prescription. Every correction template carries a
`requires_orthotist_review` flag — see `knowledge/clinical_safety_protocol.md`.
