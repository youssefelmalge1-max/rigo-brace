# Routing — how the council decides who is consulted

Routing is **not keyword matching**. Keywords are the first filter only. The
orchestrator classifies the *actual root problem* from repository evidence, then loads
the smallest sufficient set of skills.

```text
USER TASK
   ↓
ROOT AGENT INSTRUCTIONS            (CLAUDE.md / AGENTS.md)
   ↓
COUNCIL ORCHESTRATOR               (.ai/expert-council/skills/council-orchestrator/SKILL.md)
   ↓
REPOSITORY EVIDENCE                (files, repro, metrics, state channels)
   ↓
TASK CLASSIFICATION                (tags + severity + abstraction challenge)
   ↓
SELECT RELEVANT SKILLS             (1 primary + 1–3 secondary + governors)
   ↓
LOAD ONLY THEIR SKILL.md
   ↓
LOAD references/ ONLY IF NEEDED
   ↓
INDEPENDENT EXPERT FINDINGS
   ↓
ADVERSARIAL CROSS-REVIEW
   ↓
DISAGREEMENT RESOLUTION (by falsifying experiment, not vote)
   ↓
COUNCIL VERDICT
   ↓
IMPLEMENTATION GATE → IMPLEMENTATION
   ↓
TEST / VERIFY (geometry-reliability)
```

## 1. Evidence before routing

No expert is activated before there is: a file path, a reproduction, and the state
channels involved. A hypothesis with no evidence attached is not routable.

## 2. Classify the real problem

Tags: `REPRESENTATION` `SURFACE_MATH` `TOPOLOGY` `BOOLEAN` `ROBUSTNESS`
`BLENDER_STATE` `PROCEDURAL_ARCH` `PERFORMANCE` `PERSISTENCE` `UX_TOOL_LIFECYCLE`
`CLINICAL_GEOMETRY` `BIOMECHANICS` `MANUFACTURING` `TESTING`

Severity: `P0` data/clinical corruption · `P1` reliability · `P2` workflow · `P3` polish.
P0/P1 always add `geometry-reliability`, and are fixed before new features.

## 3. Challenge the abstraction before routing to the obvious expert

| The user says | Ask first | Often routes to |
|---|---|---|
| "the Boolean for the pressure patch fails" | Is a soft, smooth, deformable correction a set-theoretic solid operation at all? | `expert-ryan-schmidt`, `expert-olga-sorkine-hornung`, `expert-keenan-crane` **before** `expert-howard-trickey` |
| "mesh bug" | Is the mesh wrong, or is Blender state wrong? | `expert-campbell-barton` |
| "increase pressure to 25" | 25 of what unit? geometry or mechanics? | `expert-manuel-rigo` + `expert-carl-eric-aubin` |
| "just smooth the transition" | Denoise, fair, interpolate, or constrained deform? | `expert-keenan-crane`, `expert-olga-sorkine-hornung` |
| "remesh broke my saved correction" | Is durable identity stored as topology identity? | `expert-ryan-schmidt`, `expert-mario-botsch`, `expert-jacques-lucke` |
| "make the brace lighter" | What is the objective, and what are the hard constraints? | `expert-mark-pauly` + `expert-manuel-rigo` |

## 4. Council size

Default budget: **1 primary + 1–3 secondary**, plus `geometry-reliability` when the
issue is P0/P1 or touches a geometry kernel, plus `expert-manuel-rigo` when clinical
semantics are touched, plus `expert-carl-eric-aubin` when a mechanical claim is made.

Escalate beyond that only when the evidence demands it, and say why.

## 5. Multi-expert rule

Do **not** concatenate expert contexts into one generic answer. Each activated expert
writes its own findings under its own lens, then attacks the others:

```text
Ryan          representation and interactive geometry
Keenan        intrinsic surface mathematics
Olga          deformation energy and transition
Rigo          clinical semantics
Campbell      Blender implementation safety
Reliability   verification
```

Independent findings → cross-review → disagreement detection → evidence-based
resolution → verdict.

## 6. Disagreement protocol

Never resolve by majority vote. For each proposal state: invariant protected · failure
mode prevented · performance implication · complexity · Blender integration impact ·
clinical implication · backward compatibility. Then design the **smallest experiment
that falsifies each hypothesis** and decide on the measurement. Record why the rejected
alternatives lost.

## 7. Vetoes

A veto is not outvoted:

- `expert-manuel-rigo` — clinical semantics destroyed or clinically branded geometry
  without classification metadata.
- `expert-carl-eric-aubin` — pressure/force/predicted-correction claimed without a
  validated model.
- `expert-jonathan-shewchuk` — topology-changing branch on an unexplained tolerance.
- `expert-campbell-barton` — unsafe Blender state/lifecycle architecture.

## 8. Context discipline

Load `SKILL.md` for routed skills only. Load a skill's `references/` **only** when the
task genuinely needs algorithm selection, architecture review, or deep failure analysis.
Never load `source/original-v3/ALL_EXPERT_CONTEXT_COMBINED.md` or
`EXPERT_SKILLS_01_15_COMBINED.md` in normal work — they exist for offline/archival use
and defeat progressive disclosure.

## 9. Worked routing examples

These are also encoded in `REGISTRY.yaml → scenarios` and asserted by
`tools/test_routing.py`.

### Example 1 — "Pressure patch develops a ring after moving it."

```text
Primary:       expert-olga-sorkine-hornung
Secondary:     expert-keenan-crane, expert-ryan-schmidt
Clinical:      expert-manuel-rigo
Verification:  geometry-reliability
```

Likely cause: energy/continuity discontinuity at the region boundary, or a support that
does not follow the surface. More smoothing iterations hide it rather than fix it.

### Example 2 — "The saved correction moves to the wrong location after remeshing."

```text
expert-ryan-schmidt, expert-mario-botsch, expert-keenan-crane,
expert-jacques-lucke, geometry-reliability
```

Likely cause: persistent attachment stores **topology identity** (vertex indices, vertex
groups) rather than geometric/anatomical identity.

### Example 3 — "Boolean creates shards only on some patient scans."

```text
expert-howard-trickey, expert-alec-jacobson, expert-jonathan-shewchuk,
expert-ryan-schmidt, geometry-reliability
```

Classify Boolean intent, then input validity (open scan? self-intersections? scale?),
then predicates and tolerance. Preserve the failing scan as a permanent fixture.

### Example 4 — "Modal pressure tool works only if a certain object is selected."

```text
expert-campbell-barton, expert-sybren-stuvel, expert-ryan-schmidt
```

Blender context/state coupling. The kernel should receive data explicitly; the operator
is only a user-action wrapper.

### Example 5 — "I want reusable oval pressure templates that can be moved on any torso."

```text
pressure-expansion-system  (skill)
expert-jacques-lucke, expert-ryan-schmidt, expert-keenan-crane,
expert-olga-sorkine-hornung, expert-bruno-levy, expert-manuel-rigo,
geometry-reliability
```

Template vs instance, durable surface attachment, chart distortion (an "oval" must keep
its physical dimensions on a curved torso), clinical applicability metadata.

### Example 6 — "Increase pressure from 20 to 25."

```text
expert-manuel-rigo, expert-carl-eric-aubin
```

The council must first determine what "pressure" denotes. If it is geometric
displacement, correct the terminology to geometric depth in millimetres; a real pressure
figure requires a validated mechanical model.
