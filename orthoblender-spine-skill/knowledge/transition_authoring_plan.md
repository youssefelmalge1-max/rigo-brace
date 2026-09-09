# Transition authoring plan (#54) — task specs

Approved 2026-09-08 by the orthotist ("hand over, one thing at a time, plan →
spec → implement → test → continue"). Source verdict: DEC-0064 / LM-0049 /
`tools/targetsurfdbg.py`. Product goal: the orthotist AUTHORS the pressure /
expansion transition visually (amount, width, shape), live and non-destructive
until Commit, and the committed surface draws that shape cleanly.

Order is by dependency, not by visibility. Each task ships alone, installed,
tested, recorded, before the next starts.

| # | Task | Status |
|---|------|--------|
| 1 | Editable transition foundation: stored outline distance, per-region feather + falloff, live re-evaluation | done 2026-09-08 — DEC-0065, tools/feathertest.py 11/11, battery green (pre-existing shading_tail red only) |
| 2 | Profile model: width + top-corner radius + bottom-corner radius (mm), same evaluator, refinement samples it | done 2026-09-08 — DEC-0066, tools/profiletest.py 7/7, battery green (pre-existing shading_tail red only) |
| 3 | Corner-aware sampling (Rounded only) + honest corner readout / commit note + degenerate-quad split fix | done 2026-09-08 — DEC-0067, ERR-0038, tools/cornertest.py 8/8, nine-test battery green (pre-existing shading_tail red only) |
| 4 | Rim mollifier in mm (mesh-independent) | dropped 2026-09-08 — DEC-0068: the mollifier removes edge-scale paint quantization, edge-relative is correct; no mm-scale defect measured |
| 5 | Optional base fairing under the footprint (measure first; drop if < 3° shade gain) | dropped 2026-09-08 — DEC-0068: 4.6° gain measured, but it silently moves the patient's scan under the pad; the explicit Subdivide Scan / Smooth Area tools do it visibly |
| 6 | Hinge guard (fold-back between 100° and 162° that the fold test missed); faired-normal repair and re-flip stay on the backlog (no measured defect) | done 2026-09-08 — DEC-0069, tools/hingetest.py 2/2, ten-test battery green (pre-existing shading_tail red only) |

---

## Task 1 — Editable transition foundation

### Goal
Clinical: feather width and falloff of a live region can be changed by the
orthotist without repainting, and the preview follows immediately.
Technical: stop baking the profile into the vertex group at Add time; store the
CONTINUOUS definition (surface distance from the painted outline) and evaluate
`amount × falloff(min(d, f) / f)` from it on demand.

### Evidence
- `_region_weights_from_selection` computes `depth` (m, via `_boundary_distance`)
  and immediately collapses it to weights; the depth is discarded.
- `RIGO_OT_region_update` in Object mode only re-syncs the modifier strength;
  feather/falloff changes require Edit Selection → Update Preview.
- `RigoCorrectionRegion` has no feather; `_authored_rim_field` re-derives it from
  the weights at commit (median ratio + 0.01 validation).

### Smallest safe change
1. `RigoCorrectionRegion.feather_mm` (0 = unknown/legacy) with `update=`;
   `falloff_type` and `magnitude_mm` get `update=` callbacks (late-import
   `region_ops` from `core`; callbacks no-op on committed regions).
2. Add / circle / Edit-mode Update store the inward distance in mm as a FLOAT
   POINT attribute `f"{mask}.dist"` (non-members = -1). Circle: `d = radius − g`,
   `feather_mm = radius` (reproduces the current weights exactly).
3. `_reevaluate_region(obj, region)`: numpy read of the attribute → weights
   → vertex-group REPLACE → light snapshot refresh (weight column only) →
   `_sync_preview`. Returns False when no attribute (style / mirror / legacy).
4. Edit-mode Update uses the REGION's feather/falloff, not the scene defaults.
5. Panel: feather + falloff rows on the active region, disabled with a reason
   for committed regions and regions without a stored distance.
6. Remove drops the attribute.

Out of scope (kept as-is, noted for later): mirrored and imported-style regions
have no distance (their weights come from the chart field); Amount stays live
for them, feather/falloff need a repaint. Profile shape (Task 2) plugs into the
same evaluator.

### Invariants
- Weights from re-evaluation == weights from a fresh Edit-mode Update with the
  same feather/falloff (|Δw| ≤ 1e-6): same distance, same formula.
- Outside contract untouched: membership is fixed by the attribute; weight of
  rim vertices stays `_MASK_EDGE_WEIGHT`.
- Committed regions never change on property edits.
- `_authored_rim_field` still validates (weights remain closed-form in d).

### Test — `tools/feathertest.py` → `feathertest_result.txt` (PASS=True/False)
1. paint patch, Add f=10 SMOOTH → W10; attribute exists, member count == group.
2. `region.feather_mm = 20` → W20a; Edit Selection → Update Preview → W20b;
   max |W20a − W20b| ≤ 1e-6.
3. `feather_mm = 10` → back to W10 within 1e-6; `falloff_type = LINEAR` equals
   fresh LINEAR Update within 1e-6.
4. preview: evaluated displacement == −n · A · w for the live weights
   (< 0.05 mm); `magnitude_mm = 12` moves the modifier strength without Update.
5. circle r=30: stored feather == 30, weights unchanged by re-evaluation;
   feather 15 → w == falloff(min(d,15)/15).
6. commit, then `feather_mm = 5` → weights and mesh unchanged.
7. undo after a feather change restores W10 (best effort, logged).
Regression: selftest, regiontest, regionqualtest, goldenroutetest,
regionstyletest, regionuitest all PASS on the installed copy.

### Risks / rollback
- `update=` callbacks run on every slider step: cost is one numpy pass + N
  `vg.add` calls (~10–100 ms for 7k–40k members). Acceptable; GN Float Curve
  is the upgrade path if it ever drags.
- Attribute interpolation at refinement splits can leave small positive d on
  outside vertices post-commit; harmless because committed regions never
  re-evaluate. Rollback: revert the commit; saved .blends with the attribute
  keep working (it is ignored by older code).

---

## Task 2 — Profile model (Rounded corners)

### Goal
Clinical: the orthotist shapes the transition itself — how softly the pad
rounds over at the top and how softly it meets the body at the outline — in
millimetres, live, and two pads with the same amount and width can differ.
Technical: a new falloff kind `ROUNDED` whose weight is a physical profile in
the (distance, height) plane: flat plateau → top fillet `r_top` → straight
wall at angle θ → bottom fillet `r_bottom` → untouched body. `w(d) = z(d) / A`.

### Why this parametrisation (DEC-0064)
Every polynomial falloff has a fixed corner sharpness tied to feather and
amount (smoothstep: r = f²/6A). The measured defect was the top corner at
1 mm radius. Fillet radii are the quantity the orthotist can see and say.

### Construction (mm, per region, A = amount, f = min(feather, max d))
- bottom arc: centre (0, r_b), from (0, 0) to (r_b sinθ, r_b(1 − cosθ))
- wall: slope tanθ over the remaining width L = f − (r_t + r_b) sinθ ≥ 0
- top arc: centre (f, A − r_t), ends tangent to the plateau at (f, A)
- height identity: A = (r_t + r_b)(1 − cosθ) + L·tanθ, monotone in θ, solved
  by bisection on (0, 90°]. Feasible iff r_t + r_b < f (any A) or
  r_t + r_b = f with A ≤ f. Radii that do not fit are scaled down together to
  fit and the panel says so (readout shows the effective values and θ).
- classic kinds SMOOTH / LINEAR / SHARP are untouched (regression parity).

### Smallest safe change
1. core: `falloff_type` gains `ROUNDED`; region gets `top_radius_mm`,
   `bottom_radius_mm` (update → reevaluate); scene defaults gain the same two;
   Amount edits now route through `reevaluate_region` (a ROUNDED weight
   depends on A) — classic kinds recompute identical weights.
2. region_ops: `_rounded_profile(A, f, r_t, r_b)` → (θ, r_t_eff, r_b_eff,
   evaluator over numpy mm); `_weights_from_distance` takes the profile
   parameters; Add / circle / Update / reevaluate pass them;
   `_authored_rim_field` takes the region and, for ROUNDED, evaluates the same
   profile with the stored feather (still self-validated against the weights,
   tolerance unchanged). Mirror and style save/import carry the fields.
3. panel: `Falloff` row shows the two radius sliders when ROUNDED, plus a
   readout `wall 62° · corners 4.0 / 3.0 mm`.
Default stays SMOOTH until Task 3 (corner-aware sampling) exists — a Rounded
profile with radii at the edge-length scale is the same crease.

### Test — `tools/profiletest.py`
1. evaluator: w(0)=0, w(f)=1, monotone, slope continuous at both junctions
   (numeric), discrete curvature radius at the corners ≈ r_t / r_b (5 %),
   height identity holds; infeasible radii are scaled, never raise.
2. Add ROUNDED (A 10, f 10, r_t 4, r_b 3): mask weights == evaluator(d) ≤ 2e-6;
   `magnitude_mm = 14` re-evaluates (weights differ, equal evaluator at 14).
3. `_authored_rim_field` on the live region is not None and matches the mask
   weights (p95 ≤ 0.01) — commit samples the profile, not an interpolant.
4. commit: core depth within 10 % of A, nothing outside moved, count/manifold
   as declared.
5. style save/import round-trips the three profile fields.
Regression battery as Task 1.

---

## Task 3 — Corner-aware sampling and an honest corner readout

### Goal
Clinical: a corner the orthotist authored is drawn as a fillet, not a crease,
whenever the mesh can afford it; when it cannot, the tool says which corner
is too fine for this mesh and names the two fixes (bigger corners / wider
feather, or Subdivide Scan).
Technical: the refinement criterion is slope-only (`g = A|Δw|/L`) and blind
to turning (DEC-0064: it never fired on the B scan at 1 mm edges). Add a
curvature criterion from the analytic profile.

### Measured baseline (B scan x4, 15 mm, tools/targetsurfdbg.py)
| arm | feather | shoulder spikes | shoulder dihedral p50 / max |
|---|---|---|---|
| Smooth | 10 | 56 | 38.6 / 53.6 |
| Rounded 2/2 | 10 | 74 | 42.3 / 59.0 |
| Rounded 4/3 | 10 | 13 | 21.2 / 43.1 |
| Rounded 6/4 | 15 | 0 | 11.8 / 27.2 |

### Smallest safe change
1. `_authored_rim_field` attaches to the returned field: `.distance(co)`,
   `.corner_radius(d)` (local curvature radius of the target profile, m,
   None on flat/straight parts and on kinks) and `.min_corner_radius`
   (Smooth: f²/6A; Rounded: min(r_t, r_b); Linear/Sharp: 0 = kink).
2. `_refine_footprint`: per candidate edge, `r = min corner radius at the
   endpoints`; requirement `h_c = max(0.25·r, h_floor)` with
   `h_floor = max(0.5 mm, mean_edge / 2)`; split when the predicted length
   exceeds 1.4·h_c (same margin as the slope rule). The floor is deliberate:
   resolving a 1 mm fillet needs 0.3 mm edges, which on a coarse scan is a
   remesh, not a refinement (contract growth gate 2.5×). One halving per
   commit round in the corner bands is what a coarse scan affords; the rest
   is said, not hidden.
3. Commit note (`region.commit_note`, shown in the panel after Commit) and a
   WARNING report when `min_corner_radius < r_draw = h_floor / 0.25`.
4. `region.edge_mm` stored at Add / circle / Update; `transition_readout()`
   for every kind (Smooth shows its implicit corner `f²/6A`), with a warning
   icon below `r_draw`.

### Test — `tools/cornertest.py` (B scan x4, two regions)
1. Rounded 4/3 f10 A15: shoulder dihedral p50 ≤ 12°, max ≤ 32° (was 21 / 43);
   footprint face growth ≤ 2.5×; no commit note; commit ≤ 90 s.
2. Smooth f10 A15: commit note names the corner (1.1 mm) and "Rounded";
   shoulder p50 ≤ 25° (was 38.6), max < 53.6°.
3. readouts: Smooth 15/10 warns (1.1 mm < 2 mm); Rounded 6/4 does not.
Regression battery as before; golden MEASURE lines are EXPECTED to change
(the A-model waist Smooth 20/15 corner is 1.9 mm < r_draw) — gates decide.

---

## Task 6 — Hinge guard (done, DEC-0069)

Fold-back past 100° on a pair smoother than 60° before the commit = repair
target + ship blocker; needles (altitude < 0.1 mm) exempt. Contract keys
`fold.hinge_deg` / `fold.hinge_pre_deg`. Test `tools/hingetest.py`.

## Backlog after #54 (not started)
- Scan needle triangles (12 in one 45 mm footprint of the B scan; Subdivide
  Scan turns each into four) — a plausible source of the orthotist's "dark
  specks"; belongs in the scan Clean stage, not in Commit.
- Repair sliding on faired instead of raw normals; frozen-coordinate re-flip
  (Codex round 1) — no measured defect yet.
- Mirrored / imported-style regions carry no outline distance: Amount is
  live, Feather / corners need a repaint.
- Default falloff stays SMOOTH; switching new regions to ROUNDED is a product
  decision for the orthotist now that corners are drawn and reported.
- A mm-denominated outline smoothing control (DEC-0068) if wanted.

## Task 7 — Outward feather for newly painted regions (DEC-0070, awaiting approval)

### Goal
Paint = the full-depth contact footprint (w = 1 on every painted vertex).
Feather = a band of width f OUTSIDE the outline on the surrounding body,
using the SAME profiles (Smooth / Linear / Sharp / Rounded; Rounded's top
fillet starts at the painted outline). No clamp: the band is not limited by
the pad's size. Legacy (inward) regions keep their semantics unchanged,
including through Edit Selection -> Update.

### Design (each item answers a Codex round-3 blind spot)
- Contact identity stored explicitly: a BOOLEAN point attribute
  `<mask>.contact` (painted vertices), never reconstructed from the field.
- Distance: `_boundary_distance` unchanged, run over painted + candidate
  set; candidate set = edge-walk from the painted rim through non-painted
  vertices to `_BAND_CAP_MM` (the panel's feather maximum), stored once in
  `<mask>.dist` as -d_out (inside stays >= 0; non-member NaN). A feather
  edit then never needs new distances (growth) and removes members with
  d_out > f (shrink): `reevaluate_region` gains removal.
- Versioning: region property `feather_outside` (False for stored regions,
  True for new painted ones); `_weights_from_distance` keeps the clamp on
  the legacy path only.
- `region_edit` (Edit Selection) selects `.contact` only, never the band.
- `_authored_rim_field` at commit: rim = contact boundary from `.contact`;
  outward samples for refined vertices use the stored evaluate with sign.
- Snapshot / styles / mirror: membership = contact + band; `max_geodesic_mm`
  and anchor computed from the contact set; band recomputed on import
  (styles already carry feather + profile).
- Explicit outer influence boundary: Edit-mode weight overlay while a live
  region is active, or an outline of the band's outer edge; decide with the
  orthotist (round-1 requirement, restated in round 3).
- Overlap: two live regions whose bands overlap stack two DISPLACE
  modifiers; measured, not blended or normalised.
- Connectivity readout in the Scan stage (component count, non-manifold
  edges) so "the model isn't connected" is measured, not inferred.

### Test — `tools/featherlifecycletest.py` (Codex's named regression)
Elongated painted footprint on the B x4 fixture, A20 / Smooth. Feather
5 -> 50 -> 5, Edit Selection -> Update, save/reopen (.blend round trip),
Commit. Gates: contact set identical throughout; every contact vertex at
w >= 0.999 in preview and displaced A +- 0.05 mm at commit; band recruited
at 50 and released at 5; <= 0.001 mm movement beyond the band; a legacy
inward region on the same mesh bit-identical before/after; preview and
commit crease/topology quality (no rim edge > 30 deg, no core edge > 15 deg,
no non-manifold, no hinge); golden route MEASURE lines identical.

### Status
DONE 2026-09-09 (DEC-0071): featherlifecycletest 32/32, hingetest 2/2,
cornertest re-baselined for the outward corner, feathertest/profiletest
definition gates on the outward contract; UI screenshots in
tools/task7_uishot.py. Open: ERR-0040 (interpolation-path fold escape),
rim-adjacent refined-vertex side rule, Design-stage hide of the outline,
circle regions still inward, Codex round C review.
