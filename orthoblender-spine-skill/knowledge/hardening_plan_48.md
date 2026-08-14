# #48 Hardening Plan — reusable Pressure/Expansion library → production subsystem

Written 2026-08-14, after independent reproduction of the expert-council backlog
(issues.md #48 review entry). Evidence: `tools/hardendbg.py` → `hardendbg_result.txt`
(result files are gitignored by project convention; every load-bearing number is
recorded in ERR-0031), pure-Python float32 proof, and line-level code audit of
`rigo_brace/operators/region_ops.py` @ bdbad85. Nothing in this plan is council wording
taken on trust — every item below was re-derived from the repository or a probe run.

Goal: not "make tests green" — mature the kernel (verdict KEEP) into a subsystem whose
geometry, saved semantics, validation and evidence are independently trustworthy.

---

## Phase 1 — Reconciliation: finding → code location → reproduction → classification

| # | Council finding | Involved code | Reproduction | Classification |
|---|---|---|---|---|
| 1 | Contract/test threshold drift | `region_quality_contract.md` vs `regionqualtest.py` (`_gate_parity`, `_measure` rev_tol, missing gates) | Audit table below; maxdd 2.70 mm measured vs 2.5 mm written; "undo gates" cited in contract do not exist (grep regiontest.py: 0 hits) | CONFIRMED CONTRACT/EVIDENCE DEFECT |
| 2 | Mirror bypasses snapshot; metadata loss | `RIGO_OT_region_mirror` (region_ops.py:1322–1391, no `_store_snapshot`); `region_style_save` entry dict (:1091) | Probe `[mirror]`: SNAPSHOT_MISSING=True; save fell back to displaced-surface sampling with misleading "Older region" warning; label→NONE; no pairing keys in entry; **241 source verts collapse to 57 unique mirrored verts** (nearest-vertex Voronoi transfer) | CONFIRMED DEFECT (P1) + one CLINICAL POLICY QUESTION (pair model) |
| 3 | Edit→Update destroys imported authored field | `RIGO_OT_region_update` (:964–1007) rebuilds weights via `_region_weights_from_selection` from **panel** feather/falloff; overwrites vertex group, snapshot, `falloff_type` | Probe `[editupdate]`: weight RMS diff **0.453** (field is 0–1), 253/346 verts changed >0.05, SMOOTH→SHARP, snapshot replaced — zero warning | CONFIRMED DEFECT (P1) |
| 4 | Deep press pierces opposite wall undetected | `_footprint_self_intersections` (:467) builds BVH from **footprint faces only**; `_repair_folds` `defective()` sees only footprint | Probe `[oppwall]`: 24 mm body, 30 mm press → commit **FINISHED**, production selfx=0, independent whole-mesh oracle: **46 crossings**, tip 6 mm past the far wall | CONFIRMED DEFECT (**P0**) |
| 5 | Adjacent-face fold-over evades predicates | flip test `p.normal.dot(pre) <= 1e-9` (>90° only); selfx `set(polys[a]) & set(polys[b])` exclusion (:485) | Probe `[adjfold.foldover_creased]`: pre-creased wall folded flat by an **80° rotation** — flip=False, selfx=False, degen=False, production sees NOTHING. Detector candidate proven: adjacent-normal dot −0.09→−1.00; projected-winding oracle also flags. (Flat-start folds ≥~99° ARE caught — the blind window is creased geometry, which is exactly what dirty scans have.) | CONFIRMED DEFECT (**P0**), boundary precisely mapped |
| 6 | Chart non-injective at large radius | `_style_snapshot` tangent-plane projection; `region_radius` max 150 mm (core/__init__.py:495) | Probe `[chartfold]`: R=60 mm cylinder, 140 mm circle → **877 collision pairs** (≤1.5 mm apart in chart, >30 mm apart on surface); example weights 0.00 vs 0.14 in one cell | CONFIRMED ARCHITECTURAL LIMITATION (P2-high) — needs detection + refusal, not a new chart |
| 7 | Horseshoe loses far lobe to geodesic trim | `_geodesic_trim` limit = chart radius × 1.35 (:608); **plus a second root cause the council missed**: painted snapshot frame origin = weighted centroid (:163) which sits in the C's gap, so the import cursor (necessarily on the pad) shifts the whole pattern ~40 mm | Probe `[horseshoe]`: import IoU **0.123**, **78 % of the authored pad lost** | CONFIRMED DEFECT (P1 — silent design-topology corruption), root cause refined |
| 8 | float32 defeats 1e-6 mask floor | `_MASK_EDGE_WEIGHT=1e-6`; stores via `vg.add(max(w,1e-6))` (float32); member tests `w >= 1e-6` (:431, :1260, :505) vs `region_edit` `> 0.0` (:954) | Pure Python: `float32(1e-6)=9.9999999747e-07 < 1e-6` → floor-valued verts fail every `>= 1e-6` member test while `> 0.0` includes them. Currently benign (those verts displace ~0 anyway) | CONFIRMED DEFECT (P3 trap) |
| 9 | Tests share predicates with production | test `_self_intersections` = same footprint-only BVH + same shared-vertex exclusion; `inverted` = same <90° class; `degen` = same `1e-12` | Both probe P0 cases pass the TEST's oracle too — the shared blind spot is proven, not theoretical | CONFIRMED EVIDENCE DEFECT (P1) |

Council claims **falsified or narrowed**: (a) item 5's "evades the flip test" is false for
flat-start geometry — the evasion window is pre-creased surfaces (<90° rotation to fold);
(b) item 7 is only half trim — the anchor-in-the-gap placement error dominates (~40 mm
shift), and fixing the trim alone would NOT fix horseshoes.

---

## Item 1 — full numeric gate audit

Origin legend: AUTH = authored pre-fix in the contract without derivation; TUNE = adjusted
during gate-tuning with in-session rationale never written back.

| Metric | Contract | Test | Best measured | Worst measured | Origin | Meaningful? | Verdict |
|---|---|---|---|---|---|---|---|
| selfx / inverted / degen / holes / nonman Δ | 0 | 0 | 0 | 0 | AUTH | clinical validity | ALIGNED — but predicate itself is blind (items 4/5); fix predicate, not threshold |
| vertex/face count unchanged | required | **no gate** | — | — | AUTH | state safety | ADD test gate (trivial) |
| osc bound `max(1, 2A·6/F²·h²)` | same | same | direct5 0.58/1.0 | paint15 4.46/**40.5** (vacuous) | AUTH | numeric proxy for C1 | METRIC PARTLY WRONG at small feather → clamp `min(bound, A)` + absolute spike budget (measure first; paint15 has 14 new >60° edges today) |
| import parity osc ≤1.5×direct+0.3; spikes ≤ direct+2 | same | same | 0.88 vs 1.20 | 1.55 vs 1.74 | AUTH | yes | ALIGNED |
| amount core_med 90–110 % | same | same | 15.00 | 13.74 (91.6 %) | AUTH | clinical | ALIGNED |
| outside mask ≤0.001 mm | same | same | 0.0000 | 0.0000 | AUTH | clinical | ALIGNED |
| monotonicity rev tol | 0.2 mm | `max(0.2, 0.05·A)` = 0.75 @15 | rev=0 | rev=0 | TUNE | numeric | EXPERIMENT: rerun at 0.2; if reversals appear at the repair rim, derive tol from tangential-slide bound and write it into the contract; else tighten test to 0.2 |
| radial-bin monotone profile | required | **no gate** | — | — | AUTH | feather quality | ADD test gate |
| parity IoU | ≥0.80 | ≥0.75 | 0.891 | 0.856 | TUNE | footprint fidelity | Implementation already meets the contract → **tighten test to 0.80** (outcome 1) |
| parity RMS | ≤0.5 mm | ≤0.5 | 0.025 | 0.062 | AUTH | yes | ALIGNED |
| parity maxdd | ≤2.5 mm | ≤0.25·A (3.75) | 0.99 | **2.70 — violates contract** | AUTH/TUNE | partly wrong metric: dominated by ~1.5-edge lateral rim shift on a steep wall (slope 1.5·A/F) while the core matches to 0.06 RMS | REPLACE with derived two-part gate: **core (w>0.5) maxdd ≤ measured-then-fixed tight bound (~1.0 mm)** + **rim maxdd ≤ 1.5·h·1.5·A/F** (patient: 3.54 mm ≥ 2.70 ✓; scan: 4.33 ≥ 1.25 ✓). Derivation goes in the contract; global maxdd stays recorded as diagnostic |
| resolution core_med ≥90 % | same | same | 14.74 | 13.74 | AUTH | yes | ALIGNED |
| topology-modifier import refusal | required | **no fixture** | — | — | AUTH | state safety | ADD red fixture (live subsurf → expect refusal message) |
| determinism bit-equal | same | same | pass | pass | AUTH | yes | ALIGNED |
| undo/preview/idempotence "gates keep passing" | cites undo gates | **undo gates do not exist** | — | — | AUTH | state safety | ADD scripted undo test (make the clause true rather than deleting it) + .blend save/reopen |
| failed import mutates nothing | required | only commit-refusal gated | — | — | AUTH | state safety | ADD gate on import-refusal paths |
| perf ≤2 s | same | same (op-scoped) | 0.65 s | 0.65 s | AUTH | workflow | ALIGNED |

**Structural fix (ends divergence by construction):** all numeric thresholds move into a
fenced ```json block inside `region_quality_contract.md`; a tiny bpy-free parser
(`tools/quality_contract.py`) is the ONLY place tests get thresholds from;
`python tools/contractcheck.py` (headless, no Blender) fails if the block is missing,
unparsable, or lacks a key any gate uses. The markdown prose explains each number's
derivation next to the block. Divergence then requires editing one file inconsistently
with itself, which the checker catches.

---

## Item 9 — evidence-independence audit

| Assertion | Production predicate | Test oracle | Status |
|---|---|---|---|
| self-intersection | footprint-only BVH + shared-vertex exclusion | **same algorithm, same exclusion** | SHARED — replace test side with whole-mesh BVH + pair-level classification (proven in hardendbg `_global_selfx`) |
| triangle inversion | `dot(pre) ≤ 1e-9` | `dot < 0` | same class — both blind <90°; add winding/dihedral oracle to tests (proven in probe) |
| adjacent fold-over | none | none | ADD both sides, different algorithms: production = dihedral-collapse (baselined `n_a·n_b < −0.95` new); test = projected-winding sign per one-ring |
| opposite-wall | none | none | ADD both sides: production = moved-faces-vs-static-mesh BVH; test = independent global overlap + ray thickness |
| degenerate | `area < 1e-12` (absolute, unit-implicit) | same | make production edge-relative (`area < (0.01·mean_edge)²`-class); test keeps absolute as second opinion |
| amount fidelity | (none — analytic by construction) | signed displacement along pre-normal | INDEPENDENT ✓ |
| outside-mask invariance, osc, spikes, holes, monotonicity | none (test-only) | own measurement | INDEPENDENT ✓ |
| refuse/restore bit-exact | positions restored by op | test compares stored positions | INDEPENDENT ✓ |

---

## Cross-cutting architecture review (evidence-based KEEP/MODIFY/REPLACE)

| Pillar | Verdict | Evidence |
|---|---|---|
| Continuous normalized field (grid + IDW fallback) | **KEEP** | every parity/smoothness gate green; no reproduced defect implicates it |
| Undisplaced bake-time snapshot | **KEEP + extend to mirror** | RC3 only resurfaces where the snapshot is skipped (probe `[mirror]`) |
| Evaluated-surface-consistent frames | **KEEP + extend to painted add/update** | painted `_store_snapshot(obj, mask, _style_snapshot(obj, weights))` passes raw coords (region_ops.py:779, :998) — the one remaining mixed-state path |
| Geodesic-mm feather | **KEEP** | no terracing in any measured case |
| Exact `Amount × weight` displacement | **KEEP** | core_med 91.6–100 % everywhere |
| Valid-or-refuse transactional commit | **KEEP + widen the validator** | refuse/restore proven bit-exact; the flaw is what "valid" checks, not the transaction |
| Schema-v2 grid representation | **KEEP + additive v2.1 keys** | chart-agnostic storage confirmed; folding needs detection/refusal, not a new representation. Geodesic-polar exp-map chart stays DEFERRED |
| Tangent chart | **MODIFY (guard), not replace** | folds are real (877 pairs) but only beyond ~90° of arc; detection at bake + refusal/cap keeps the envelope honest |

## Clinical quality model (measurable, three zones)

- **Core (w > 0.9):** median |d| ∈ [90, 110] % of Amount; per-vertex |d| within ±15 % of
  Amount (no central pole/crater — new gate); no new >60° dihedral edge.
- **Transition (0 < w < 0.9):** C0 by construction (continuous field); C1 proxy = one-ring
  oscillation ≤ min(analytic smoothstep bound, Amount); zero terracing (radial-bin
  monotone); zero weight-vs-|d| reversals beyond tolerance; no secondary ring (bin profile
  has exactly one sign of slope). We do NOT claim C2 — the representation (bilinear grid ×
  smoothstep) does not guarantee it; the contract must say so.
- **Outside (w = 0):** |d| ≤ 0.001 mm, count/topology unchanged, no new defects anywhere
  on the mesh (whole-mesh validator, not footprint-only).

---

## The plan, per item

Severity: P0 silent invalid geometry · P1 corrupts saved semantics/data ·
P2 robustness/fidelity · P3 maintainability trap.

### Wave 0 — Contract integrity (Item 1) — P1, SAFE, first
**Fix:** JSON threshold block + parser + checker as above; tighten IoU to 0.80; derived
two-part maxdd gate (measure core-maxdd first, then fix the number); rev_tol experiment;
add missing gates (count-unchanged, radial-bin monotone, live-modifier import refusal,
failed-import no-mutation, scripted undo, .blend save/reopen); provenance stamp (git hash
+ date) in every result file; remove/true-up the undo sentence.
**Alternatives considered:** a divergence-*detector* comparing two documents (rejected:
two sources of truth remain); moving thresholds into Python only (rejected: the contract
doc is the clinical-facing artifact and must stay readable).
**Acceptance:** contractcheck passes headless; regionqualtest gates read only parsed
values; all gates green with the reconciled numbers OR a measured, documented derivation
for each changed number. **Regression risk:** none to geometry (test/doc only).
**Rollback:** revert commit; no data format touched.

### Wave 1 — Validator v2 (Items 4+5+9) — P0, red fixtures FIRST
**Root cause (shared):** "valid" is footprint-local and <90°-flip-only.
**Fix (production):** after displacement+repair, run (a) moved-faces-vs-whole-static-mesh
BVH crossing check (pre-existing crossings baselined out, exactly like today's baseline
set) and (b) dihedral-collapse fold predicate: interior edge whose adjacent-normal dot
falls below −0.95 post-commit and was above −0.5 pre-commit. Both feed the existing
refuse-and-restore transaction — message: "would press through the opposite surface /
fold the surface here".
**Fix (tests):** independent oracles (global BVH classification + projected-winding +
ray-thickness spot check) + two red fixtures promoted from hardendbg: `oppwall`
(24 mm body / 30 mm press → must REFUSE) and `foldover_creased` unit fixture for the
predicate. **Safety margin:** the oppwall fixture also gates a measurable
remaining-material margin: refuse when the displaced surface comes within **3 mm** of the
opposite sheet — an explicitly *geometric* safety floor (collision prevention), NOT a
clinical thickness rule; the clinical minimum clearance is a policy value the orthotist
can raise in settings, never lower below the geometric floor. (Documented per the
"do not invent clinical millimetres" rule.)
**Alternatives:** winding-number inside/outside test (rejected: scans are open/dirty,
winding unreliable); full remesh-based collision (rejected: destructive, forbidden);
shrinkwrap clamp to opposite wall (rejected: silently changes the correction instead of
refusing — violates valid-or-refuse).
**Perf:** whole-mesh BVH ≈ 44 k faces ~0.1 s, inside the 2 s budget (gated).
**Regression risk:** MEDIUM — new refusals on previously-"passing" hostile geometry;
that is the intended behavior change; baselining keeps dirty-scan pre-existing defects
out. **Rollback:** predicate additions are two pure functions + two call sites.

### Wave 2 — Snapshot/anchor semantics (Items 2 + 7 + painted mixed-state) — P1
**Mirror fix:** derive the mirrored snapshot FROM the source snapshot (mirror sample u →
−u; re-anchor via `_target_surface` at the mirrored anchor), never from displaced
geometry; replace nearest-vertex weight transfer with the same field-evaluation path the
importer uses (kills the 241→57 Voronoi collapse); report the true unique-vertex count.
Keep `anatomical_label` through save/import as metadata; on mirror, auto-map sided labels
(AXILLA_L↔AXILLA_R etc. — the enum already encodes sides) with the existing
`requires_orthotist_review`/"review the kind" flag.
**Horseshoe fix:** snapshot anchor must lie ON the pad — for painted regions snap the
weighted centroid to the nearest member vertex and store `anchor_uv` (≡0,0) + per-bake
`max_geodesic_mm`; `_geodesic_trim` limit = stored `max_geodesic_mm × 1.15` instead of
chart-radius × 1.35. Import doc line: "the cursor marks the style's anchor point".
**Painted mixed-state:** pass evaluated coords/normals into the painted-path snapshot
(region_ops.py:779, :998), same as the circle path already does.
**Schema:** additive v2.1 keys (`anchor_uv`, `max_geodesic_mm`, `clinical{label}`) —
v1/v2 entries keep loading unchanged (absent keys = today's behavior); no migration
needed; saved styles remain forward-readable.
**Tests:** direct→save→mirror→import parity battery; horseshoe/C/crescent/two-lobe/
narrow-bridge fixtures with IoU ≥ 0.80 vs authored; painted-with-live-modifier snapshot
consistency.
**OPEN CLINICAL POLICY (needs your decision, not blocking Waves 0–1):** what a saved
style stores for a paired correction — options in the final report (single region +
pairing metadata [recommended]; full pair-group style; reference link).
**Regression risk:** MEDIUM (anchor change shifts painted-style placement semantics —
convex pads: centroid≈nearest member vertex, so drift is sub-edge; a parity gate pins it).

### Wave 3 — Imported-field preservation on edit (Item 3) — P1
**Ownership model:** footprint geometry (editable selection) vs correction profile
(Amount, falloff, authored field in the snapshot) get explicit owners. `region_update` on
a region whose snapshot carries an authored field re-evaluates THAT field over the edited
footprint (grown verts get field-extrapolated/hull-tapered weights; shrunk verts drop);
`falloff_type` and the snapshot survive. Converting to a plain painted feather becomes an
explicit operator option ("Rebuild falloff from selection") with a visible report, never
the silent default.
**Measured acceptance:** edit-without-change round-trip weight RMS ≤ 0.02 (today 0.453);
peak |d|, feather width, radial profile, orientation each within 2 % of pre-edit;
explicit-convert path reports and changes falloff only then.
**Alternatives:** freezing imported regions read-only (rejected: orthotists legitimately
adapt footprints per patient); storing a second "original field" copy for undo-style
revert (deferred: snapshot already serves this once Update stops overwriting it).
**Regression risk:** MEDIUM (touches the painted-edit workflow; regiontest/regionstyletest
edit phases pin the old behavior for non-imported regions, which keeps panel-feather
semantics).

### Wave 4 — Chart guard + gate vacuum (Item 6 + backlog 6) — P2
Bake-time chart-collision detection (the probe's metric: 2D-near/3D-far pairs) → refuse
save with "this region wraps too far around the body to store as a flat style — reduce
the radius or split it"; effective cap documented (~90° of local arc). Import side:
same check against the target. Gate clamp `min(bound, Amount)` + absolute new-spike
budget on gated commits (measure paint15's 14 spikes first; if the budget must exceed
~max(2, 2 % of footprint faces), the painted commit needs smoothing work, not a wider
gate — that experiment decides). Frame-up 0.1 cliff: blend the two tangent-up candidates
over a band instead of switching (P3 rider).

### Wave 5 — Precision + evidence residue (Items 8 + 9 remainder) — P3/safe
`>= 1e-6` member tests → `> 0.0` (region_ops.py:431, :505/:516-area, :1260) matching
`region_edit`; serialization round-trip test for weights {0, 5e-7, 1e-6, 2e-6, 0.005,
0.0051, 0.99, 1.0} × 3 save/load cycles (library JSON + vertex-group float32);
edge-relative degeneracy epsilon; try/except-restore wrapper around the commit
mutate-repair window; baked-scale invariant documented in core/__init__ near
`apply_units`; genuine v1-migration deviation measurement (v1 entry → v2 field rebuild →
measured RMS disclosed); downstream full-pipeline run (committed correction → trimline →
brace → QA → export) added to the release battery.

---

## Dependencies and order

```
Wave 0 (contract single-source)          — no dependencies; everything else cites it
Wave 1 (validator v2)                    — red fixtures exist (hardendbg); do FIRST after 0 (P0)
Wave 2 (snapshot/anchor)                 — independent of 1; pairing METADATA safe now,
                                           pair MODEL waits for orthotist decision
Wave 3 (field-preserving edit)           — after 2 (uses anchor/max_geodesic keys)
Wave 4 (chart guard, spike budget)       — after 0 (thresholds live in contract block)
Wave 5 (precision/evidence residue)      — float32 + provenance can ride Wave 0; rest last
```

Grouped root causes honored: 4+5+9 are ONE validator correction; 2+7+painted-snapshot are
ONE anchor/snapshot correction; nothing ships as nine unrelated patches.

## Regression matrix (final battery, before release)

direct P/E 5/15 · painted P/E · same-position import · moved import · rotated-frame
import · mirrored import · same-name update · edited imported footprint (kept + grown +
shrunk) · densities 2/3/6 mm + decim 0.65/0.30 · live deform modifier · live
topology-changing modifier (refusal) · dirty/creased scan · convex/concave · large pad ·
horseshoe/C/crescent/two-lobe/narrow-bridge · repeated imports (5+5 gated, 15+15 refusal)
· stacked previews · infeasible refusal · **oppwall attack (refusal)** · **creased-fold
attack** · scripted undo/redo · .blend save/reopen · v1 fallback + measured migration ·
v2 determinism round-trip · perf ≤2 s — then downstream: corrected patient → trimline →
complete brace → manifold/selfx/wall-thickness QA → export.

## Risk classes

- SAFE: Wave 0, Wave 5 float32/provenance/docs.
- MEDIUM: Wave 1 (new refusals — intended), Wave 2 (placement semantics, schema-additive),
  Wave 3 (edit workflow), Wave 4 (new save refusals).
- RISKY/representation-breaking: none planned — schema stays v2-additive; exp-map chart
  remains DEFERRED. Stop-and-report triggers: any need to break v2 readability, the pair
  model decision, sided-label auto-mapping, chord-vs-geodesic mm ruling.
