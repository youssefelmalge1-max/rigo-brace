# Council Investigation — #49e: the residual crown of radial pleats is in the FIELD, not the mesh

2026-08-16. Third orthotist report on the same artifact ("you see still the
same"). Screenshots: A-model waist, 20 mm pressure, feather 15, committed and
smooth-shaded — the plateau floor reads clean, but the feather WALL carries a
crown of radial pleats all the way round, plus a scalloped outer silhouette.
The wireframe shot shows refinement clearly worked (dense triangles across the
whole footprint), so mesh density is NOT the remaining cause.

## Problem

Two prior rounds attacked the *tessellation* (#49b density robustness, #49c
curved splitting + harmonic field + smooth shading). Both improved the wall
and neither closed the artifact. That pattern — denser mesh, same ridges — is
itself evidence: whatever produces the ridges is being *reproduced* by the
refinement, not caused by it.

## Repository Evidence

`_region_weights_from_selection` (rigo_brace/operators/region_ops.py) baked the
falloff as an edge-walk Dijkstra distance seeded at the painted rim's
VERTICES; `_refine_footprint` then interpolated those authored samples (IDW +
a harmonic Gauss–Seidel pass) with the ORIGINAL vertices pinned as anchors.

`tools/fielddbg.py` — the discriminating experiment. Same mesh, same amount,
same feather, same falloff curve, same displacement direction, same repair;
only the FIELD differs between arms, so any difference in the wall is
attributable to the field alone.

Measured on the A-model waist patch (1001 selected verts, 117 rim verts,
mean edge 3.90 mm, feather 15 mm — only **3.8 vertex rings across the whole
feather**):

- **Dijkstra vs exact distance over the band: +8.5 % mean, +36.7 % p95,
  +43.9 % max.** A path forced onto mesh edges is longer than the surface
  path, and the excess depends on how the local edges happen to point, so it
  varies *around* the rim. At the steepest point of a smoothstep that is
  millimetres of radial wall undulation.
- Wall dihedral spectrum, ORIGINAL tessellation, field swapped:

  | field | dih_mean | p95 | >30° | ridges |
  |---|---|---|---|---|
  | Dijkstra-from-rim-vertices (production) | 15.1 | 43.3 | 89 | 187 |
  | exact distance to the rim POLYLINE | 12.1 | 29.1 | 34 | 200 |
  | exact distance to a MOLLIFIED rim polyline | 8.0 | 25.4 | 24 | 91 |
  | mollified distance field (rejected, see below) | 9.7 | 28.4 | 30 | 138 |

## Classification

`SURFACE_MATH` (scalar field / distance-metric), severity **P2** (workflow +
clinical surface quality; no corruption). Sub-class: the mathematical object
was mis-specified, not mis-implemented.

## Activated Experts

- **expert-keenan-crane** (primary) — geodesic distance, metrication, smooth
  scalar fields on a surface, Euclidean-vs-intrinsic, boundary conditions.
- **expert-olga-sorkine-hornung** (cross) — rings/creases at a region
  boundary, transition continuity, "smoothing iterations" as a non-answer.
- **expert-manuel-rigo** (governor) — the authored footprint, feather and
  profile are clinical inputs; mollifying the rim touches one of them.
- **geometry-reliability** — the measurement had to falsify, not illustrate.

Considered and dropped: ryan-schmidt (representation is fine — the region is
already a falloff-weighted group), mario-botsch (topology was #49d's problem,
and it is closed), campbell-barton (no Blender state involved).

## Root Cause

**The falloff was the exact answer to a badly-posed question.** Distance
measured from a *set of rim VERTICES* is only C0: its gradient jumps along the
bisector between neighbouring seeds — one crease per reflex corner of a rim
that the paint tool quantized onto triangles — and the graph walk adds an
anisotropic +8.5 %/+36.7 % distortion on top. Refining the mesh samples those
creases more faithfully; it can never remove them. That is precisely why two
rounds of density work did not close the artifact.

## Council Verdict — HARDEN (both the bake and the commit-time sampling)

Not REPLACE KERNEL: the region model, the transaction, the repair ladder and
the refinement criterion are all sound and stay. The defect is confined to how
one scalar field is defined and where it is evaluated.

### Keenan lens — recommended formulation (boundary conditions stated)

`d(v)` = distance to the **mollified rim curve**, computed as:

1. rim polyline Laplacian-mollified along itself (6 passes, λ=0.5). One pass
   annihilates the one-vertex zigzag (wavelength 2 → factor 0) and multiplies
   a 6-vertex wavelength by 0.75; six passes leave everything under ~6 rim
   edges at ≤18 % while the authored outline (mode 1 of a ~100-vertex loop)
   keeps **0.996 of its radius**. The scale is the rim's own sampling.
2. a multi-source walk from the rim recording each vertex's ROOT rim vertex —
   the intrinsic, surface-following part;
3. exact point-to-SEGMENT distance, restricted to rim segments within 3
   rim-steps of that root. **Euclidean measurement is admissible only because
   of that gate**: across the ≲12 mm it can reach, the chord/arc gap on a
   torso of R ≈ 120 mm is d³/24R² ≈ 0.005 mm, and no far-side sheet is
   reachable at all because the root came from a walk on the mesh. Same
   geodesic-gating discipline as the existing `_geodesic_trim`.
4. level set re-zeroed by the LARGEST rim residual, so every rim vertex lands
   at exactly 0 with no per-vertex pinning. `max(0, ·)` costs no continuity —
   every supported falloff has zero slope at t = 0.

Boundary conditions: `w = 0` on the painted rim, `w = 1` at `d ≥ f_eff`,
`w = falloff(d / f_eff)` between. Rejected alternatives, on measurement:

- **Heat method / linear solve** — correct but needs a sparse factorization
  Blender does not ship; the gated formulation above is already exact to
  ~0.005 mm over the feather band and is C¹.
- **Fast marching (triangle updates)** — fixes metrication but NOT the
  creases: exact distance from a jagged curve still creases at every reflex
  corner. Treats the symptom that measured smaller.
- **Mollifying the distance FIELD instead of the rim curve** — measured
  profile deviation 0.274 at p95 = a **5.5 mm** shift of the authored wall at
  20 mm. Violates the amount/profile contract. REJECTED.

### Olga lens — the interpolant was the second half

Fixing the bake alone left the wall at p95 23.0° because `_refine_footprint`
*interpolates* the authored samples with the ORIGINAL vertices pinned: no
interpolant can be smoother than the function it interpolates, and a coarse
scan's anchor lattice prints its own ring of kinks into the wall. Since the
authored falloff is now a closed-form function of the region's own boundary,
new vertices SAMPLE it instead (`_authored_rim_field` → `_refine_footprint(
field=…)`). Measured, same mesh and same field: **p95 23.0 → 16.9, >30° edges
35 → 10**. This is not "more smoothing iterations" — it is evaluating the
authored function where the geometry actually is.

### Rigo lens — clinical governance, no veto

- **Amount** unchanged (`magnitude_mm` untouched; core median 14.98/15.0).
- **Feather** unchanged in name and *more* accurate in fact: the old field
  over-measured distance by 8.5–36.7 %, so an authored 15 mm feather was
  realized narrower than 15 mm in places. The fix makes 15 mm mean 15 mm.
- **Footprint**: the rim mollification moves the boundary by 1.29 mm mean /
  3.08 mm max — under one mean edge (3.90 mm) — and removes a quantization
  artifact of the paint tool, not authored intent. The authored outline keeps
  0.996 of its radius. The region edge still lands on the untouched scan at
  **0.0000 mm** (verified by the feather gate on every fixture).
- **Plateau / profile**: unchanged by construction — same falloff curve, same
  `f_eff` rule.
- Library/style and legacy regions are **not** re-authored: the reconstruction
  is compared against the stored weights and rejected unless it agrees to 0.01
  (an unedited new-formulation region reconstructs to ~1e-9; a legacy
  Dijkstra-baked one deviates by 0.138 at p95). No schema change, no
  migration.

### Reliability lens — a second, separate finding

Switching the field made the wrinkled `paint15` gate fall back. Forensics
(`tools/paint15dbg.py`, three arms isolating bake vs sampling vs control)
found ONE blocking face: 53270, all-original, weights 0.912/0.806/0.941,
**self-flip −0.049** — yet every neighbour dihedral 0.77, no
self-intersection, 2.14 mm² area, and the neighbours had themselves rotated
0.64–0.72.

That exposed a latent flaw in the production predicate: `normal · pre_normal
≤ 0` asks a single triangle whether it turned past 90°, which conflates the
surface FOLDING BACK (a defect) with the surface legitimately TILTING under a
steep authored wall (the correction itself — 15 mm through a 10 mm feather is
a 2.19 mm/mm slope, a 65° tilt). On a coarse scan a thin triangle riding that
tilt crosses 90° while the surface around it stays sound.

Fix, after one wrong attempt: dropping the strict test from the repair TARGET
set measurably let real inversions through (the independent test oracle caught
`inv=1..2` on five circle fixtures — exactly what an independent oracle is
for). The two questions are now answered separately: the repair still AIMS at
every rotated face (cheap insurance, slides it back before it creases
anything), while what may not SHIP is the surface-confirmed subset — a face
must actually crease one of its edges past 90° (`_FLIP_CONFIRM_DOT = 0.0`,
still far stricter than the `_FOLD_DOT = −0.95` fold-over test it backs up).

## Outcome (measured)

Orthotist's exact case, A-model waist 20 mm / feather 15:

| | before #49e | after |
|---|---|---|
| wall dihedral mean | 12.2° | **4.7°** |
| wall dihedral p95 | 31.1° | **16.9°** |
| wall edges > 30° | 91 | **10** |
| ridge edges | 431 | **87** |
| seam defects at attempt 0 | 9 in 7 clusters | **0** |
| commit | 9.0 s (dissolve ladder) | **3.1 s, no ladder** |

`paint15` (wrinkled fixture) commits refined +141 with 0 defects;
`regiontest` commit 6.06 s → 2.24 s. Full battery green: regionqualtest
(failed_gates=[]), regiontest, regionstyletest, regionuitest, selftest,
downstreamtest.

## Regression Tests

`fold.flip_confirm_dot` is in the contract's machine-readable block and
asserted by `regionqualtest.contract_constants`. The existing independent
oracles (inverted / selfx / folds / feather-outside / profile / amount) are
what caught the wrong first attempt and are the standing guard.

## Open

- The circle path (`RIGO_OT_region_circle`) still builds its falloff from a
  Dijkstra distance to the seed VERTEX. Its isolines carry the same
  metrication anisotropy, radiating from the centre rather than the rim; it
  measures clean on today's fixtures (wall_dih_p95 27.9 → 33.7 → 27.6 across
  the change) but the formulation has the same weakness.
- Preview fidelity: the DISPLACE-modifier preview still shows the coarse
  authored field, which the commit no longer produces.
