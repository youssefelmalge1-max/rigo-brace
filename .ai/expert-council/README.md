# Expert Council — portable geometry/clinical review skills

A provider-neutral **Agent Skills** layer for the Rigo Brace Designer add-on. It gives
any capable coding agent (Claude Code, Claude, OpenAI Codex/GPT agents, anything that
understands `SKILL.md`) a disciplined way to review geometry, Blender-platform,
procedural-architecture, numerical-robustness and clinical questions **before** code is
written.

## 1. What the council is

Nineteen skills: fifteen expert review lenses, plus four system skills (orchestrator,
repository audit, pressure/expansion architecture, implementation gate).

Each expert lens is a **public-work-derived engineering profile**, inferred from
published papers, open-source code, talks and documentation. It is not a digital clone
of the named person, does not reproduce private opinions, and never implies that the
named person reviewed this repository. See `source/original-v3/24_SOURCE_LEDGER.md` for
the public sources behind each lens.

## 2. Architecture

```text
.ai/expert-council/            <- canonical, provider-neutral (single source of truth)
├── README.md                  <- this file
├── REGISTRY.yaml              <- machine-readable skill + routing metadata
├── ROUTING.md                 <- how routing, cross-review and vetoes work
├── skills/<skill>/SKILL.md    <- the skill contract (loaded on activation)
├── skills/<skill>/references/ <- deep context (loaded only when needed)
├── source/original-v3/        <- the original supplied bundle, preserved verbatim
└── tools/                     <- validate_skills.py, test_routing.py

.claude/skills/<skill>/SKILL.md   <- thin adapter -> canonical
.codex/skills/<skill>/SKILL.md    <- thin adapter -> canonical
CLAUDE.md / AGENTS.md             <- root control towers that point here
```

The provider folders contain **adapters only** — a frontmatter block and a pointer.
Expert knowledge exists in exactly one place, so there is no synchronization debt.

## 3. Skill list

| Skill | One line |
|---|---|
| `council-orchestrator` | Classifies the real root problem, routes the smallest expert set, runs cross-review, emits one verdict. |
| `expert-ryan-schmidt` | Interactive geometry systems, editable representation, remeshing with constraints, preview/commit. |
| `expert-howard-trickey` | Boolean/solid robustness — and whether Boolean is the right abstraction at all. |
| `expert-jacques-lucke` | Procedural architecture, correction stacks, template vs instance, caching and versioning. |
| `expert-keenan-crane` | Intrinsic surface geometry: geodesics, curvature, frames, transport, surface fields. |
| `expert-alec-jacobson` | Robust processing of dirty scans: winding numbers, validation, fold detection. |
| `expert-campbell-barton` | Blender platform: bpy/bmesh, context, modes, depsgraph, undo, lifecycle. *(veto)* |
| `expert-mark-pauly` | Computational design, objectives and constraints, manufacturability, optimization readiness. |
| `expert-carl-eric-aubin` | Brace biomechanics and FEM; audits every pressure/force/correction claim. *(veto)* |
| `expert-manuel-rigo` | Clinical Geometry Governor: Rigo-Chêneau contact/expansion systems. *(veto)* |
| `expert-jonathan-shewchuk` | Predicates, epsilon and scale, degeneracy, constrained triangulation, mesh quality. *(veto)* |
| `expert-olga-sorkine-hornung` | Deformation energy, ARAP, handles, transition continuity, detail preservation. |
| `expert-bruno-levy` | Parameterization, local 2D charts, distortion, foldover. |
| `expert-mario-botsch` | Mesh data structures, adjacency, decimation/remeshing quality, mesh health. |
| `expert-sybren-stuvel` | Blender Python maintainability, package boundaries, reload, error paths. |
| `geometry-reliability` | Regression fixtures, benchmark corpus, metrics, p50/p95, release gates. |
| `repo-audit` | Scoped forensic audit with KEEP/HARDEN/REFACTOR/REPLACE-KERNEL/DEFER verdicts. |
| `pressure-expansion-system` | Architecture governor for the reusable Pressure/Expansion library. |
| `implementation-gate` | Pre-implementation contract and post-implementation verification. |

## 4. How routing works

Read `ROUTING.md`. In short: evidence → classification → abstraction challenge →
smallest sufficient council → independent findings → adversarial cross-review →
disagreement resolved by the smallest falsifying experiment → one verdict → implementation
gate → verification. Keywords are hints, never the decision.

## 5. How progressive disclosure works

Three tiers, loaded on demand:

1. **Descriptions** (always visible) — the frontmatter `description` of each skill is the
   semantic trigger. Nothing else is preloaded.
2. **`SKILL.md`** (loaded when the skill activates) — role, activation boundaries,
   workflow, mandatory questions, output contract, vetoes, handoffs. A few hundred lines.
3. **`references/`** (loaded only when the task needs depth) — the full expert context,
   the RFC, the audit playbook, the router and casebook.

Anti-goal: pasting fifteen expert files into every session. That is what the combined
bundles in `source/original-v3/` would do, which is why they are archival only.

## 6. How Claude uses it

- Claude Code auto-discovers `.claude/skills/*/SKILL.md` and reads the descriptions.
- Root `CLAUDE.md` instructs the agent to consult `council-orchestrator` for any
  non-trivial geometry/Blender/clinical problem.
- The adapter points at the canonical skill; the agent reads that, then loads only the
  routed experts.

## 7. How OpenAI / Codex / other agents use it

- Root `AGENTS.md` lists every skill with its one-line description and canonical path.
- `.codex/skills/*/SKILL.md` mirrors the Claude adapters for tools that scan a skills
  directory.
- Any agent that can read Markdown can start at
  `.ai/expert-council/skills/council-orchestrator/SKILL.md`.

## 8. How to add another expert

1. `mkdir -p skills/expert-<name>/references`.
2. Write `SKILL.md` with frontmatter (`name` matching the folder, a specific
   `description`) and the standard sections: role · activate when · do NOT activate ·
   task classification · workflow · mandatory questions · output contract · veto
   conditions · escalation · deep reference.
3. Put the long-form knowledge in `references/expert-context.md`.
4. Add an entry to `REGISTRY.yaml` under `skills:` (type, path, priority, summary,
   domain, references) and, if relevant, to `routing:`.
5. Generate the adapters (`.claude/skills/...`, `.codex/skills/...`) — copy an existing
   adapter and change the name, description and relative path.
6. Run `python .ai/expert-council/tools/validate_skills.py` and
   `python .ai/expert-council/tools/test_routing.py`.
7. Add the skill to the table in this README and to `AGENTS.md`.

## 9. How to update expert context

Edit `skills/<skill>/references/expert-context.md`. The archived original in
`source/original-v3/` stays untouched as provenance; the validator reports intentional
divergence as an informational note, not an error. Record *why* the context changed in
`orthoblender-spine-skill/knowledge/decision_log.md`.

## 10. How to test the skills

```bash
python .ai/expert-council/tools/validate_skills.py    # structure, frontmatter, refs, adapters
python .ai/expert-council/tools/test_routing.py       # registry integrity + routing scenarios
```

`validate_skills.py` checks: every canonical skill has `SKILL.md`; frontmatter parses;
`name` and `description` exist; `name` matches the folder; names are unique; every
referenced file exists; registry paths resolve; Claude and Codex adapters exist, are
thin, and point at a resolvable canonical path; no adapter embeds the giant context.

`test_routing.py` checks: registry integrity, domain coverage, trigger→expert mappings,
required expert combinations, and the six worked scenarios in `ROUTING.md`.

Both exit non-zero on failure and need no third-party packages (PyYAML is used when
available, with a built-in fallback parser otherwise).

## 11. Why the combined bundles must not be loaded

`source/original-v3/ALL_EXPERT_CONTEXT_COMBINED.md` (~150 KB) and
`EXPERT_SKILLS_01_15_COMBINED.md` (~110 KB) contain everything at once. Loading them
destroys the routing discipline: the agent gets every lens simultaneously, produces
generic multi-topic commentary instead of role-separated findings, and burns the context
budget that should hold *repository evidence*. They exist for offline reading, archival,
and emergencies where per-skill files are unavailable.

## 12. Clinical veto and reliability gates

**Clinical veto** — `expert-manuel-rigo` can block a change that destroys clinical
relationships (a contact area moved without its paired expansion/counterforce, expansion
treated as mirrored negative displacement, a clinically branded preset with no
classification metadata, unintended sagittal change, or automated clinical inference from
scan geometry alone). `expert-carl-eric-aubin` can block any pressure/force/correction
claim that is not backed by a validated model with version provenance. A veto is not
outvoted; it is resolved by removing the claim, adding the metadata, or escalating to the
orthotist.

**Reliability gate** — `geometry-reliability` activates automatically for every P0/P1,
every geometry-kernel change, every migration and every release. Its release gate fails
if a P0 is open, a P1 is unmitigated, geometry validity regresses, save/load loses
semantic state, undo fails to restore mesh **and** domain state, a migration silently
changes an old patient case, or an agreed performance gate is materially exceeded.

## 13. Provenance and honesty rules

Original expert context is public-work-derived and is **not** an impersonation or a claim
of private expert advice. Never state that a named expert reviewed this repository or
endorsed a decision. Attribute factual claims to the repository, Blender documentation,
or the cited public source.
