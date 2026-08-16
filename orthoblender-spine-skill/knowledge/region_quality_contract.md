# Reusable Pressure/Expansion correction — geometry acceptance contract (#48)

Written BEFORE the fix from measured controls (2026-07-29, `tools/regionqualdbg.py`);
reconciled 2026-08-14 after the expert-council review (hardening Wave 0 — see
`hardening_plan_48.md`). A committed correction (direct paint, direct circle, or imported
style) passes only if every gate below holds. Gates are evaluated on the raw mesh after
commit, scoped to the correction footprint (mask members + one ring) unless a gate says
whole-mesh.

## Machine-readable thresholds (single source of truth)

`tools/quality_contract.py` parses this block; `tools/regionqualtest.py` takes every
numeric gate value from it and nowhere else; `python tools/contractcheck.py` fails the
build when this block is missing, unparsable, or incomplete. Editing a threshold here IS
editing the test.

```json
{
  "validity": {
    "selfx": 0, "inverted": 0, "degenerate": 0, "holes": 0,
    "nonmanifold_delta": 0, "count_change": 0
  },
  "smooth": {"osc_floor_mm": 1.0, "osc_profile_coeff": 6.0, "osc_cap": "amount"},
  "amount": {"core_lo": 0.90, "core_hi": 1.10},
  "feather": {"outside_max_mm": 0.001, "rev_tol_mm": 0.2,
              "decile_rev_tol_mm": 0.2},
  "parity": {"osc_factor": 1.5, "osc_slack_mm": 0.3, "spike_slack": 2,
             "iou_min": 0.80, "rms_max_mm": 0.5,
             "core_maxdd_mm": 1.0, "rim_shift_edges": 1.5},
  "resolution": {"core_med_min_frac": 0.90},
  "perf": {"import_commit_max_s": 7.0},
  "wall": {"clearance_mm": 3.0, "cross_sheet_new": 0},
  "fold": {"dot": -0.95, "pre_dot": -0.5, "flip_confirm_dot": 0.0,
           "new_folds": 0,
           "oracle_post_deg": 160.0, "oracle_pre_deg": 120.0},
  "size": {"surface_tolerance_frac": 0.12},
  "quality": {"enforced": true, "wall_sampling_margin": 1.3,
              "wall_sampling_violations": 4,
              "aspect_p95_factor": 2.5, "min_rows_across_feather": 4,
              "growth_max_faces_factor": 2.5, "smooth_new_spikes": 2}
}
```

**The falloff field is defined by the authored BOUNDARY CURVE (#49e).** For a
painted region the weight is `falloff(d / f_eff)` where `d` is the surface
distance to the **mollified rim curve**, not the graph distance to the rim
vertices. Distance from a set of vertices is only C0 — its gradient jumps
along the bisector between neighbouring seeds, one crease per reflex corner of
a rim the paint tool quantized onto triangles — and an edge-walk Dijkstra adds
an anisotropic overestimate on top (measured on the A-model waist patch:
+8.5 % mean, +36.7 % p95, +43.9 % max). Refinement reproduces those creases
more faithfully; it cannot remove them, which is why two rounds of density
work (#49b, #49c) did not close the ridge crown. The construction is: rim
polyline Laplacian-mollified along itself (6 passes, λ=0.5 — kills wavelengths
under ~6 rim edges; the authored outline, mode 1 of a ~100-vertex loop, keeps
0.996 of its radius); a multi-source walk recording each vertex's ROOT rim
vertex; exact point-to-SEGMENT distance restricted to rim segments within 3
rim-steps of that root — Euclidean measurement is admissible **only** because
of that gate (across the ≲12 mm it can reach, the chord/arc gap on R ≈ 120 mm
is d³/24R² ≈ 0.005 mm, and no far-side sheet is reachable because the root
came from a walk on the surface, the same discipline as `_geodesic_trim`);
level set re-zeroed by the LARGEST rim residual, so every rim vertex is
exactly 0 with no per-vertex pinning and the region edge still lands on the
untouched scan. Because the field is a closed form, commit-time refinement
SAMPLES it for new vertices instead of interpolating the authored anchors: no
interpolant can be smoother than the function it interpolates, and IDW +
harmonic is pinned at the ORIGINAL vertices, so a coarse scan's anchor lattice
printed its own kink ring into the wall (measured, same mesh and field: wall
dihedral p95 23.0° interpolated vs 16.9° sampled, edges over 30° 35 vs 10).
The reconstruction is self-validating — compared against the stored weights
and rejected unless it agrees to 0.01 — so library/style and legacy regions
keep the interpolation path and no saved correction is silently re-authored.

**Inversion is a question about the SURFACE, not about one triangle (#49e).**
`normal · pre_normal ≤ 0` conflates two different events: the surface folding
back on itself (a defect) and the surface legitimately TILTING under a steep
authored wall (the correction itself — 15 mm through a 10 mm feather is a
2.19 mm/mm slope, a 65° tilt). On a coarse scan a thin triangle riding that
tilt crosses 90° while nothing around it is folded, degenerate or
self-intersecting (measured, paint15 face 53270: self-flip −0.049, every
neighbour dihedral 0.77, 2.14 mm² area, neighbours themselves rotated
0.64–0.72). The two questions are therefore answered separately: fold repair
still AIMS at every rotated face — dropping it from the target set measurably
let real inversions through on five circle fixtures — but what may not SHIP is
the surface-CONFIRMED subset, where at least one shared edge actually creases
past 90° (`flip_confirm_dot`, still far stricter than the `dot` fold-over test
it backs up). Self-intersection, degeneracy and fold-over keep their own
independent tests unchanged.

**A polish tool may not step at its own border (#49f).** Smoothing is a
separate operator from the commit and has its own contract: it may not leave a
discontinuity where its influence stops, it may not move anatomy the orthotist
did not paint, and it may not eat the authored correction.
`bpy.ops.mesh.vertices_smooth` fails all three by construction — it smooths
the selected vertices at uniform strength and simply stops at the selection
border. Measured on a committed A-model 20 mm region: a **1.66 mm step** and a
6.3° mean crease running along the painted outline (which, being brush-painted,
is jagged at the face scale, so the crease reads as a scalloped ring), convex
speed bumps in the wall raised from 87 to 123, and the worst core point pulled
from 95 % to **85 %** of the authored depth — a silent 2 mm of lost correction.
`Smooth Area` therefore ramps its strength to exactly zero over
`_SMOOTH_FEATHER_ROWS` rows at the painted border (wider than the border's own
one-row jaggedness, so the ramp cannot print it) and uses Vollmer's
HC-Laplacian, which pushes each vertex back by the displacement its whole
neighbourhood shared — high-frequency bumps go, the low-frequency form stays.
Measured on the same mesh: border step **0.00 mm**, crease 6.3° → 1.6°, speed
bumps 87 → 86 (67 → 49 on the wrinkled fixture), core depth 100 % of authored,
nothing outside the paint moved. Gated by `w49f.smooth_area_no_border_step` and
`w49f.smooth_area_no_new_bumps`. The same reasoning applies to Blender's
sculpt-mode Smooth brush, whose cut-off is the brush edge rather than a
selection border — a stroke run along a region's rim writes that edge into the
surface, and no add-on code can prevent it.

**Two-mode commit semantics (#49).** Every commit first attempts the REFINED
transaction. Its fold repair runs tangential-only (the clinical amount of
every vertex is preserved by construction); when the defect set stalls
unchanged for 3 iterations, the still-defective faces' OWN new vertices —
never the ring, never originals — are allowed full one-ring relaxation,
normal component included (escalation). A new vertex carries no authored
amount (its normal position is derived from the field sampling), so the
clinical promise — original scan vertices keep their exact authored
displacement — is untouched. Refined commits additionally treat any
refinement-born triangle compressed below 0.12× the sampling target as
defective (measured: displacement squeezed a new seam triangle to 0.24 mm
height against a 2.38 mm target — a numerically meaningless normal that
must not ship). If repair still leaves ONLY refinement-born seam slivers
(every still-defective face touches a new vertex; ≤4 faces), the commit
retries with those slivers DISSOLVED — plans ACCUMULATE across up to THREE
retries, because larger amounts collapse several wrinkle seams and the
clusters surface one retry at a time (#49d, measured on the A-model waist:
1 cluster at 10 mm, 2 at 15, 3 at 20; a single retry meant every amount
above 10 mm fell back to the staircase, and sculpt-smoothing the fallback
tore a spike crown). Each retry:
the bit-deterministic refinement is re-run on a fresh working copy and the
identified new vertices plus their one-ring new neighbourhood are welded
onto surviving neighbours (nearest original preferred) BEFORE displacement —
original scan vertices never move, no new topology is created, every
surviving vertex keeps its authored/field weight, and the full
displace→repair→validate stack re-runs on the dissolved topology (measured
on paint15: the wrinkle-seam slivers dissolve, the retry converges with
+168 verts, zero inverted-face oracle flags, no warning). Only if
that also fails — or the defect is NOT refinement-born — does it fall back
to a FULLY unrefined commit — bit-for-bit the pre-#49 behaviour — with a
visible WARNING telling the orthotist the wall stayed at the scan's own
sampling and that smoothing the scan first enables the finer wall. No
partial refinement, no density seams, all modes atomic and deterministic. Each mode is measured by its proven oracle set: refined
commits by the topology-independent BVH oracles, unrefined commits by the
behaviour-neutral index oracles (a refined-commit oracle applied to legacy
output flags the staircase that legacy behaviour was always accepted with).
Mesh-quality gates (#49) are ENFORCED on every commit that actually refined
(`refined_added > 0`); fallback commits are legacy-gated and warned.
Thresholds derive from measured fixtures, not taste. The enforced sampling
gate is `wall_sampling`: over surviving PRE-EXISTING footprint edges with
local slope g = amount·|Δw|/L ≥ 0.35 (sharp >60° pre-creases exempt, exactly
as refinement deliberately leaves them — pressing walls collide there), the
post-commit length must not exceed `wall_sampling_margin` (1.3, a measured
divergence allowance: actual post length exceeds the parallel-direction
prediction hypot(L, amount·Δw) where faired directions diverge; healthy
population measured ≤1.14×) × the sampling requirement 1.4·h_req(g);
violations gated to ≤4. The requirement is ABSOLUTE — #49b removed the
1.1·mean_edge floor from BOTH the refinement criterion and this oracle: a
floor proportional to the scan's own mean edge made the input triangulation
the ceiling of output quality, so coarse patient scans kept the pre-#49
staircase (measured: decim030 shipped a 21.5 mm wall edge with zero flagged
violations) while the equally-floored oracle was blind to it. Refinement now
engages on coarse scans down to the same absolute requirement (density
robustness: the same body triangulated differently must commit to the same
wall quality). The count bound
is the dissolve plan's own ≤4-face bound: a seam dissolution legitimately
returns a bounded spot to the scan's sampling (measured on paint15: 3
violations at ≤2.07× — one triangle row at one wrinkle seam), while the
systemic staircase defect measures 82 violations at 3.12× on the identical
wall committed unrefined — a 20× count separation. A correctly refined
wall away from dissolved seams has zero violations, because refinement
split every edge above the same requirement (all 21 other fixtures: 0). The stretch RATIO (recorded, NOT gated) is set by the authored
steepness alone — splitting an edge halves L and Δw alike, so the ratio is
scale-invariant at √(1+g²), up to 2.46 for a legitimate 15/10 Rigo profile —
a ratio threshold would gate the orthotist's authored profile, not the mesh
(measured: refined paint15 2.15–2.27 max ratio on FLAT sub-floor edges with
ZERO sampling violations and 0–1 smoothing spikes; the earlier 1.8/≤30 ratio
gates were calibrated before any steep-feather fixture ever refined, on
fixtures whose feathers were 2–3× wider). Aspect_p95 ratio gate 2.5
backstops gross degradation (measured: heavy wrinkle-zone refinement of
paint15 reaches 2.03–2.09× pre — splitting wrinkled triangles is
intrinsically anisotropic — while circles and light refinement stay ~1.0);
smooth-after-commit worsened-pre-existing spikes measured 0–1, gated ≤2.
`min_rows_across_feather` is enforced BY CONSTRUCTION through the per-edge
refinement criterion (split when predicted length exceeds 1.4× the local
slope's row requirement) and verified directly by the wall_sampling gate;
the same criterion makes already-dense meshes a no-op (gated).
Feather-monotonicity reversals (`rev`) are counted on the INDEX-EXACT
displacements of surviving originals in every mode: the BVH signed distance
misreads wrinkled zones by up to 2.1 mm (measured: a w 0.975/1.000 edge
with exact displacements −14.61/−15.00 mm read as −13.32/−12.93), so it
must not vote on 0.2 mm-tolerance reversals; new-vertex profile position
stays covered by the osc/decile/core gates on the BVH oracle. The inverted
oracle is dual-confirmation everywhere (#49b): faces with original vertices
need vertex-reference AND surface-reference agreement; ALL-NEW faces (no
vertex reference; the surface reference alone misreads wrinkle flanks) need
surface-reference agreement AND a real fold against an edge-neighbour
(< −0.5) — a genuinely inverted patch cannot exist without one, because its
rim faces carry original vertices and its boundary must fold. Dihedral
honesty: only PRE-EXISTING edges can prove commit damage; edges born from
refinement have no pre state (a wrinkled scan sampled finer shows sharp
dihedrals that were always there) — new-edge geometry is covered by the quality
gates and the fold/validity predicates. Displacement is measured
topology-independently (signed distance to the pre-commit surface via BVH);
parity samples the surviving original vertices as probe points. The smoothness
bound's `h` is the post-commit mean footprint edge. Perf was re-derived for the
transactional commit: full-mesh working copy + refinement + atomic write adds
~0.7 s on the 44.5k patient scan (gate was 3.0 s); #49b/#49c added real work
(floorless refinement, curved placement, harmonic field — measured 3.23 s);
#49d ladder depth scales with the AMOUNT (the orthotist's own principle):
≤10 mm commits take the direct refined-or-fallback path (one full refined
attempt on a wrinkled 53k paint measures ~4.5 s before the fallback
decides — total 6.06 s measured on the gate fixture); deep presses
(>10 mm) may run up to 4 accumulated dissolve retries on COPIES of the
once-computed refined snapshot (measured: A-model 20/15 refines +325 in
9 s where it used to staircase). The gate is 7.0 s on the ≤10 mm battery
fixture (user-paced commit; the orthotist accepted compute for maximum
wall quality — DEC-0050/0051).

## Measured clean controls (baseline)

Direct circle, 15 mm PRESSURE, 30 mm radius, patient scan (44.5k verts, 3.85 mm edges):
`osc_max=1.23 mm, osc_mean=0.32 mm, dihedral max=46.4°, edges>60°=0, inverted=0,
selfx=0, holes=0, core_med=14.43–14.55 mm (96–97 %), outside=0.0000 mm, monotone_rev=0`.

Broken pre-fix references: imported styles `osc_max` 1.9–4.0 mm, spikes>60° up to 111
(flat!), IoU vs direct 0.648, decim-0.30 `core_med=0.00`; repeat-import `osc_max=6.6`,
162 spikes, 40 inverted, 136 self-intersections; painted path 115 self-intersections.

## Gates

1. **Validity** — new self-intersections = 0; inverted faces = 0; degenerate faces = 0;
   non-manifold edge delta = 0; weight-field holes (w<0.1 vert with ≥3 one-ring
   neighbours w>0.5) = 0; vertex/face counts unchanged OUTSIDE the footprint, and
   inside only by DECLARED refinement — the commit records the exact vertex count it
   added (`region.refined_added`), and the `refined_declared` gate pins the measured
   delta to that declaration (#49; shrinkage is never legitimate).
   **Whole-body validity (Wave 1, P0):**
   - *Opposite-wall clearance* — before mutating anything, the commit casts rays from
     every core (w>0.5) vertex along its displacement direction against the body's
     static (non-footprint) faces; any hit within `displacement + clearance_mm`
     REFUSES untouched. `clearance_mm` is a geometric collision floor (never press
     through or within 3 mm of another sheet), NOT a clinical thickness rule; a
     clinical minimum may later raise it, never lower it.
   - *Cross-sheet net* — after commit+repair, new footprint-vs-static face
     intersections (shared-vertex pairs excluded, pre-existing contacts baselined)
     must equal cross_sheet_new, else refuse-and-restore.
   - *Fold collapse* — adjacent footprint faces whose shared edge folds closed
     (normal dot < fold.dot) without being pre-creased (pre dot > fold.pre_dot) are
     defects the repair must clear, else refuse-and-restore. This closes the flip
     test's <90°-rotation blind window on creased scans.
   The TEST oracle for these is independent of the production predicates: footprint
   faces vs a whole-mesh BVH (different pairing/bookkeeping), and a dihedral-degree
   measurement (`> oracle_post_deg` new, was `< oracle_pre_deg`) instead of a
   normal-dot; a unit fixture cross-checks predicate against oracle; the
   `contract_constants` gate pins the production constants to this block.
2. **Smoothness** — one-ring displacement oscillation bounded by twice the analytic
   smoothstep curvature of the requested profile, clamped so it can never go vacuous:
   `osc_max ≤ max(osc_floor_mm, min(2 × amount_mm × 6/feather_mm² × h², amount_mm))`
   where `h` = mean footprint edge (mm) and feather = the effective falloff width
   (circle: its radius). The unclamped bound reached 40.5 mm at feather 10 — steeper
   walls are legitimate, but oscillation beyond the amount itself never is.
   **Import parity**: importing a style must not be rougher than applying it directly —
   `osc_max(import) ≤ osc_factor × osc_max(direct) + osc_slack_mm` and new dihedral >60°
   edges `import ≤ direct + spike_slack` on the same fixture/parameters.
3. **Amount fidelity** — median |displacement| over the w>0.9 core within
   **[core_lo, core_hi]** of the requested amount. The saved style's stored amount and
   the region's `magnitude_mm` are one value; the panel's global "Amount (mm)" only
   seeds NEW regions and is never multiplied in.
4. **Feather fidelity** — |displacement| outside the mask ≤ outside_max_mm; zero
   weight-vs-|d| monotonicity reversals (> rev_tol_mm) across edges; the weight-decile
   profile of mean |d| is monotone non-decreasing with weight within decile_rev_tol_mm
   (shape-agnostic replacement for the old radial-bin wording — radial bins are
   undefined for painted, non-convex footprints).
5. **Library fidelity** — importing a saved style at its authoring location on the
   authoring mesh vs the direct region: footprint IoU (w>0.05) ≥ iou_min; |d| field
   RMS diff ≤ rms_max_mm; **two-part max deviation** replacing the old single 2.5 mm
   number (which was authored without derivation and measured violated at 2.70 mm while
   the shipped test allowed 3.75 mm — see decision DEC-0042):
   - core (both weights > 0.9, the controlled plateau — same zone as gate 3):
     max |d| diff ≤ core_maxdd_mm;
   - rim (everything else): max |d| diff ≤ rim_shift_edges × h × slope_max where
     slope_max = 1.5 × amount/feather (the analytic peak slope of the smoothstep
     profile). Derivation: resampling a continuous field onto a different triangulation
     can shift the transition rim laterally by ~1.5 edges; on a slope s that reads as a
     depth difference of shift × s without any real shape change. Patient 15/30 mm,
     h≈3.15: bound 3.54 mm (measured 2.70); scan 15/30, h≈3.85: bound 4.33 (measured
     1.25). The global maxdd is still RECORDED in every run as a diagnostic.
6. **Resolution robustness** — the same style on 2 mm / 3 mm / 6 mm flat fixtures and
   on decimate-0.65/0.30 scan targets passes gates 1–4 and keeps
   `core_med ≥ core_med_min_frac`.
7. **Evaluated-surface correctness** — the import frame and the vertex field must be
   computed from the SAME geometry state (the evaluated surface the user sees). If the
   modifier stack changes the vertex count, the import must refuse with an actionable
   error and mutate NOTHING (no region, no vertex group, no vertex moved) — gated by a
   live-subdivision fixture.
8. **Determinism / state safety** — same inputs ⇒ same weights (bit-equal); a refused
   commit restores positions bit-exactly and keeps the live preview; a failed import
   mutates nothing; `regiontest.py` + `regionstyletest.py` preview/idempotence gates
   keep passing. *Pending evidence (hardening Wave 5): scripted undo/redo and .blend
   save/reopen round-trip are REQUIRED for release but not yet covered by a gate; do
   not cite them as verified until those tests exist.*
9. **Performance** — import + commit operators ≤ import_commit_max_s on the patient
   scan.
10. **Size semantics (Wave 2 decision)** — a style's authoritative size is measured
   ALONG THE SURFACE (geodesic mm) over its effective footprint (w > 0.05); the
   tangent chart's chord extent is diagnostic only and never defines the size. Amount
   stays normal-displacement mm; Feather stays surface mm. The import trim limit is
   the stored intrinsic size × 1.15 (legacy chord fallback for old entries), so
   distant lobes of non-convex pads survive. On a curved target the realized surface
   size must stay within surface_tolerance_frac of the authored size, else the import
   WARNS (never silently resizes). Measured chord-vs-geodesic divergence for a
   ~52 mm effective footprint: +3.5 % on an R=60 mm cylinder, +2 % on R=95 mm; the
   council's ±8–11 % figure applies to footprints approaching the chart's ~90°-of-arc
   envelope, where the fold guard (Wave 4) refuses before the divergence can lie.
11. **Non-convex fidelity (Wave 2)** — the snapshot anchor is snapped ONTO the pad
   (strong-member vertex nearest the weighted centroid; a horseshoe's raw centroid
   sits in its gap and shifted the imported pattern 40 mm / IoU 0.123 before this),
   and save→import of a C-shaped pad at its anchor keeps footprint IoU ≥ the parity
   iou_min.
12. **Pairing & mirror provenance (Wave 2 decisions 1–2)** — a style stores ONE
   region plus never-silently-discarded clinical facts: anatomical label, paired
   flag, counterpart kind/label/landmark/amount, counterpart center offset (mm),
   mirror provenance (`mirrored_from`), and whether a sided landmark was auto-mapped
   (only unambiguous L↔R pairs are mapped; midline labels never change). The UI must
   say when a selected style belonged to a pair. Mirror derives the opposite region
   from the UNdisplaced snapshot through the importer's continuous-field path — never
   from displaced geometry, never by nearest-vertex weight collapse.

Every result file opens with a provenance stamp (git commit, date, Blender version).

Verified by `tools/regionqualtest.py` (gated PASS/FAIL) and `tools/regionqualdbg.py`
(diagnostic numbers, no gates); `tools/contractcheck.py` guards doc/test consistency;
adversarial reproductions live in `tools/hardendbg.py`.
