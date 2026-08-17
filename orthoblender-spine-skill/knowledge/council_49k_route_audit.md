# #49k — end-to-end execution audit of the REAL user workflow

Question put by the orthotist after three rounds of "measured a cause, changed
the code, battery went green, screen looked the same":

> the exact clinical workflow I am using may not actually be executing the
> stage or algorithm we think we are fixing.

**It was not.**  Proven by runtime instrumentation, not by reading names.

Evidence: `tools/userpathdbg.py`, `tools/routematrixdbg.py` (both wrap the
INSTALLED production functions and call through; no production file is edited).

## Phase A — the runtime is what we think it is

    repo HEAD        d368c02
    blender          5.0.1
    region_ops       %APPDATA%\...\extensions\user_default\rigo_brace\operators\region_ops.py
    installed sha256 f73557d7... == repo sha256 f73557d7...   (all 38 modules identical)
    resident rigo modules 38, duplicate module paths []
    one install only; no rigo_brace under scripts/addons

So "installed successfully" was true.  The problem was never a stale copy.

## Phase C — the route matrix (runtime-observed, A-model waist, 20 mm / 15 mm)

| user workflow | field kernel | rim field | refinement kernel | geodesic fade | wall p95 | max | >30° | ridges |
|---|---|---|---|---|---|---|---|---|
| painted new region | rim-curve distance (#49e) | **FIELD** | **FIELD (#49e)** | no | **17.57** | 38.76 | 8 | 38 |
| circular new region | seed-vertex Dijkstra | rejected | IDW+harmonic (+0 verts) | no | **31.09** | 58.47 | 22 | 54 |
| **library style v2 (USER)** | **bilinear grid, 2 mm cells** | **rejected** | **IDW+harmonic** | YES | **27.22** | **76.10** | 21 | 98 |
| library style v1 (legacy) | IDW over samples | rejected | IDW+harmonic | YES | 26.14 | 75.79 | 15 | 92 |
| mirrored style (commit) | bilinear grid v2 | rejected | IDW+harmonic | YES | 24.81 | 36.29 | 10 | **142** |
| reopened .blend (painted) | weights from file | FIELD | FIELD (#49e) | no | 17.57 | 38.76 | 8 | 38 |

**One of six routes reaches the #49e field. It is the only route the whole
regression battery exercises.**  The orthotist's route — Library Pressure →
Import at Cursor → Commit — is not it.

This was not hidden.  `_authored_rim_field`'s own docstring says library/style
and legacy regions "keep their existing interpolation path untouched".  That
sentence was written as a safety property (no silent re-authoring of a saved
correction) and it is a good property — but it also means the fix shipped for
the reported artifact never ran on the workflow that reported it, and nothing
in the battery could notice.

## Phase D — where the ridges first exist

The authored field, evaluated at the ORIGINAL vertices and displaced with no
refinement, no repair, no smoothing:

    FIELD-ONLY  library route  p95 6.34  max 12.56  >30° 0
    FIELD-ONLY  painted route  p95 8.95  max 12.56  >30° 0

Both fields are smooth where they are sampled.  The library field is if
anything *smoother* than the painted one at that stage.  The ridges are **not**
authored into the field at the original lattice — they are created during
commit.  The 2 mm bilinear grid's C0 cell edges are NOT the dominant defect
(hypothesis raised and rejected on measurement).

## Phase F — ablation on the user's own route

| arm | p95 | max | >30° | ridges | wall edges |
|---|---|---|---|---|---|
| production (IDW + harmonic) | 27.22 | **76.10** | **21** | 98 | 571 |
| refinement disabled entirely | 23.88 | 38.31 | 3 | 57 | 320 |
| refinement fed a closed-form chart field | **21.50** | 38.91 | 6 | 72 | 571 |

**Refinement makes the user's wall worse than not refining at all** — the stage
that exists to raise quality is the stage injecting the visible defect on this
route.  Max dihedral 76.1° with it, 38.3° without.

The mechanism is exactly the one #49e identified and fixed for painted regions:
new-vertex weights come from an interpolant *pinned at the coarse original
vertices*, so the anchor lattice prints its own ring of kinks into the wall.
Feeding refinement a closed-form field instead recovers most of the loss
(76.10 → 38.91 max, 21 → 6 edges over 30°) while keeping the extra sampling.

A library style DOES have a closed form available — the stored grid evaluated
in its chart frame.  It is simply never handed to refinement.

Residual gap: the best library arm (21.50) is still worse than the painted
route (17.57).  Two candidates remain unattributed — the `_geodesic_trim`
Dijkstra fade multiplied on top of the chart field (anisotropic graph distance,
the metrication error #49e removed from the painted path, re-entering here as a
multiplier), and the chart field's own C0 cell edges.

## Phase G — is the stage ordering wrong?

Partly.  The current order is not wrong so much as **incomplete**: the pipeline
assumes an authored region carries a *continuous* representation into commit,
and that assumption holds for exactly one of the six routes.  Everywhere else
the region degrades to a per-vertex weight sample set at the scan's own
coarseness before refinement runs, and no later stage can recover what the
discretisation already threw away — refinement then interpolates the damage
and displacement amplifies it by the full 20 mm amount.

The missing stage is not a new smoothing pass at the end.  It is a
**continuous field contract at the boundary between authoring and commit**:
every route should hand commit a `co -> weight` evaluator, not only a
dictionary of vertex weights.  Three of the six routes already have one in
closed form (rim-curve distance; chart grid; seed Dijkstra + radius); they just
do not expose it.

## Answers to the stop-condition questions

1. **Which runtime path the workflow executes** — `region_style_import` →
   `_weights_from_style` (bilinear grid v2) → `_connected_subset` →
   `_geodesic_trim` → `region_apply` → `_authored_rim_field` **rejects** →
   `_refine_footprint` **IDW+harmonic** → displace → `_repair_folds` (0
   remaining) → accept → `smooth_selection` → `_smooth_selection_hc`.
2. **Does every recent fix run on it** — no.  #49e does not.  #49c (curved
   split placement, harmonic relaxation), #49d (amount-scaled refinement),
   #49f/#49h (Smooth Area) do.
3. **First stage where the ridges exist** — commit, specifically new-vertex
   weight assignment in refinement.  Not the authored field, not shading.
4. **Does a legacy/fallback branch bypass the intended algorithm** — yes,
   `_authored_rim_field` returning `None` is a silent, by-design fallback to
   pre-#49e behaviour, taken by 5 of 6 routes.
5. **Which recent changes materially alter the real-user mesh** — of the #49e
   work, none.  Smooth Area does (27.22 → 15.63 p95 on the library route).
6. **Is the ordering wrong** — see Phase G: incomplete, not misordered.

## Consequences for the test suite

The golden regression for this defect must be built on the **library import**
route, not the painted one, and `w49e.*` gates must be understood as covering
one route out of six.  Same-session save/load of a painted region is still not
cross-version evidence.

## Not yet closed

- exit code 11 from Blender after `wm.open_mainfile` inside a timer callback
  (test-harness artifact; all results were written before it, DONE=True).
- the circular route refines by **0 vertices** at 20 mm / 30 mm radius and is
  the single worst route measured (p95 31.09) — unexplained, not yet filed.

---

# #49k steps 2-3 — the fix, and what it did NOT fix

A schema-v2 style owns a continuous displacement field (its resampled grid).
`_applied_field_record` now records that field, with the chart frame it was
placed in, onto the region at placement; `_style_applied_field` rebuilds it at
commit and hands it to refinement, so refinement-born vertices SAMPLE the
authoring representation instead of re-interpolating the coarse weights the
placement just wrote. Self-validating against the stored weights
(`_STYLE_FIELD_TOLERANCE` 0.05, contract-pinned), so a region without a
recorded field keeps the old path exactly — no migration, no re-authoring.

## Step 3 ablation (A-model waist, 20 mm / 15 mm, same body and place)

| arm | p95 | max | >30° | wall edges |
|---|---|---|---|---|
| 1 old library path (field=None) | 27.22 | 76.10 | 21 | 571 |
| 2 no refinement at all | 23.88 | 38.31 | 3 | 320 |
| 3 continuous field (test-side reconstruction) | 21.50 | 38.91 | 6 | 571 |
| 4 **fixed production** | **20.73** | 38.91 | **3** | 571 |

The fixed path beats the no-refinement control on p95 (20.73 vs 23.88) at equal
`>30°` count and with 78 % more wall sampling — it is better than not refining,
not merely valid. It also beats the test-side reconstruction (arm 3) because
production anchors the chart at `_target_surface`'s projected surface point
rather than the raw cursor.

## Route matrix after the fix

| route | refinement | p95 | max | >30° | state |
|---|---|---|---|---|---|
| painted | FIELD | 17.57 | 38.76 | 8 | ok |
| **library v2 (user)** | **FIELD** | **20.73** | 38.91 | 3 | **fixed** |
| mirrored style, import | FIELD | 20.73 | 38.91 | 3 | fixed |
| reopened .blend | FIELD | 17.57 | 38.76 | 8 | ok |
| library v1 (legacy) | IDW | 26.14 | 75.79 | 15 | **open** |
| mirrored style, commit | IDW | 25.17 | 34.32 | 12 | **open** |
| circular | IDW, +0 verts | 31.09 | 58.47 | 22 | **open (step 5)** |

## Two things measurement stopped

**v1 must NOT be routed through this path.** It was, in the first cut, and it
made the wall *worse*: p95 26.14 to 27.00, max 75.79 to 71.78. A v1 style's
authoring representation is itself a per-vertex sample cloud at the authoring
scan's coarseness, so IDW over it is the same pinned interpolant commit already
uses. There is no authoritative continuous field to sample, and inventing one
is not neutral. `_applied_field_record` now returns `None` for v1 and the dead
sample branch was removed from the evaluator.

**Mirrored regions were not given the field.** `region_mirror` builds a
mirrored SAMPLE cloud (no grid) and runs it through `_weights_from_style`, so
it is the v1 case. Mirroring the grid in `u` would be exact and cheap, but it
needs its own route gate first — shipping it without one would repeat exactly
the mistake this audit found. Recorded, not done.

## The golden gate is 7/8, and the 8th is honest

`golden_user_pressure.shading_tail` fails at 20.04° against a 20.0° ceiling set
BEFORE the fix was written. The ceiling was not moved. The library route's
shading tail is still worse than the painted route's (17.71°), which is the
same residual the p95 gap shows (20.73 vs 17.57) — the gate now tracks step 4
rather than pretending the route reached parity.

---

# #49k step 4 — `_geodesic_trim` is NOT the cause of the library/painted gap

Suspected because it multiplies a smoothstep of an edge-walk Dijkstra distance
onto the placed weights, and edge-walk Dijkstra is the anisotropic metric #49e
removed from the painted path. Measured before replacing anything
(`tools/trimgapdbg.py`):

**The anisotropy is real.** Graph distance / straight-line distance over the
footprint: mean 1.110, p95 1.298, max 1.393. By 30° direction bucket the mean
ratio swings 1.032 → 1.288 — a **directional spread of 0.256, i.e. 23 % of the
mean**. The metric genuinely is direction-dependent.

**But it barely touches the wall.** limit 35.8 mm, fade starts at 28.7 mm; of
134 transition-wall vertices only **8 (6.0 %)** lie in the fade band at all.

**And removing it changes nothing:**

| arm | members | p95 | max | >30° |
|---|---|---|---|---|
| A production (fade active) | 317 | 20.73 | 38.91 | 3 |
| B cutoff kept, fade removed | 315 | **20.74** | 38.90 | 3 |
| C trim removed entirely | 324 | 21.49 | 38.90 | 3 |

Removing the fade moves p95 by **0.01°**. Removing the trim entirely makes the
wall *worse* (it admits marginal vertices). **Verdict: not the cause. Do not
replace it.** The far-side cutoff is doing real work and the taper is
harmless — an anisotropic metric acting on 6 % of the wall is not a defect.

## So what IS the residual 20.73 vs 17.57?

Bilinear grid sampling is C0 — its gradient jumps across every 2 mm cell
boundary — and since step 2 refinement SAMPLES that grid at sub-cell
resolution, those seams are resolved for the first time. Re-running with a C1
Catmull-Rom sample of the *same* grid data:

| arm | p95 | max | >30° |
|---|---|---|---|
| production, bilinear (C0) | 20.73 | 38.91 | 3 |
| Catmull-Rom (C1) | 20.67 | **32.72** | 4 |

The C0 seams own part of the worst crease (max 38.91 → 32.72, −16 %) but
essentially none of the p95 bulk (−0.06°). So the remaining ~3.2° p95 gap is
**neither the trim nor the interpolation order**. The leading remaining
candidate is chart-projection distortion: the style's field is defined in a
flat tangent chart projected onto a curved torso, so its level sets are not
surface-equidistant and the wall's steepness varies around the pad — a
different class of error from anything measured so far. Not yet demonstrated;
recorded as the next hypothesis, not a conclusion.

# #49k step 5 — the circular route: refinement is innocent, the field is not

`tools/circledbg.py`, 20 mm amount, 30 mm radius, A-model waist.

**Refinement is not skipped by a guard.** Reproducing the production split test
over the 697 candidate edges: slope g mean 0.434 / max 0.997, and
`predicted / (1.4 * h_required)` has **max 0.851** — never above the 1.0 needed
to split. A 20 mm cone spread over a 30 mm radius is a genuinely gentle wall
and the scan already meets the sampling requirement. Adding vertices would not
help, and forcing them would be the wrong fix.

**The field is the defect.** The circle's weights come from an edge-walk
Dijkstra ball around a single seed VERTEX. Its graph/straight ratio by
direction swings 1.039 → 1.297 — a **directional spread of 22.9 %** — which at
20 mm amount is up to **4.6 mm of direction-dependent wall error, written
straight into the authored weights and never refined away**. That is the
star-shaped isoline pattern #49e diagnosed, in the one route that still authors
with raw Dijkstra, with no refinement stage to soften it.

**Therefore the circular fix is not a refinement change.** It is to author the
circle's weights from the same mollified-rim-curve distance the painted route
uses — the ball's boundary is a rim polyline, and `falloff(d_rim / radius)`
reproduces the same clinical cone semantics on a smooth metric. That would also
let `_authored_rim_field` accept the region, so refinement inherits the field
contract for free where it does apply.

Not implemented: per the lesson this audit exists to teach, the circular route
needs its own permanent end-to-end gate FIRST.

---

# #49l — why `Mesh ▸ Smooth Vertices` collapses the patient mesh

The orthotist dragged Blender's native **Smooth Vertices** to factor 1.9146 and
the corrected pad shredded into spikes. Not the sculpt brush, not our Smooth
Area — Blender's own Edit-Mode operator.

Blender's operator is a plain Laplacian step per pass:

    p  <-  p + factor * (mean(neighbours) - p)

A contraction only for `0 < factor < 1`. At `factor = 1` a vertex lands exactly
on its neighbours' centroid; above 1 it **overshoots past** the centroid, and
the overshoot is amplified every pass. For the highest-frequency mesh mode the
per-pass multiplier is about `|1 - 2·factor|`, which at 1.9146 is ≈ 2.8 — so
the error grows ~2.8× per pass. Measured (`tools/smoothsafetydbg.py`,
A-model, committed 20 mm / 10 mm pad, factor 1.9146):

| repeats | max vertex move | longest edge | slivers | |
|---|---|---|---|---|
| 1 | 4.93 mm | 8.83 mm | 0 | bounded |
| 5 | 17.45 mm | 24.72 mm | 0 | bounded |
| 10 | **184.64 mm** | 356.59 mm | 2 | COLLAPSED |
| 20 | **48 678 mm** | 97 075 mm | 57 | COLLAPSED |

48 metres of travel from a 20 mm correction. The blow-up is exponential in the
pass count, exactly as the eigenvalue predicts — this is not a defect in the
add-on, it is the operator being driven past its stability limit.

By factor at 5 passes: 0.5 → 2.86 mm, 0.9 → 3.86, 1.0 → 4.08, 1.5 → 5.88,
1.9146 → 17.45 mm with the longest edge stretching 8.83 → 24.72 mm. The tearing
starts the moment factor exceeds 1.

**Our Smooth Area cannot do this.** `select_smooth_factor` is hard-capped at
1.0 and `select_smooth_iters` at 50 (`core/__init__.py`), and the kernel is the
Vollmer HC-Laplacian, which pulls back toward the original points each pass.
Measured at the maximum the UI allows: strength 1.0 × 50 passes → max move
**1.71 mm**, zero slivers. Fifty passes move less than five passes of the
native operator at 0.5.

Guidance for the orthotist: keep native Smooth Vertices below 1.0 — it is not a
"strength" slider with a safe top end, it is the step size of an iteration that
diverges above 1.

# #49m — Commit crashed on any quad scan (P0, found by accident)

Surfaced while measuring the above: the smoothing probe remeshed the scan and
the commit died.

    ValueError: BVHTree.FromPolygons: non triangle found at index 0
                with length of 4
    _static_faces_bvh (region_ops.py:593)  <-  RIGO_OT_region_apply

`BVHTree.FromPolygons(..., all_triangles=True)` is a hard ASSERTION, not a
hint. Three sites in `region_ops.py` used it — `_footprint_self_intersections`,
`_static_faces_bvh`, `_cross_sheet_pairs` — and the patient scan is routinely
NOT triangles:

* the Mesh stage's own **Remesh** emits 100 % quads — measured, 89 144
  triangles in → **46 098 quads** out;
* the **Exoside Quad Remesher** result is adopted verbatim by
  `RIGO_OT_use_quad_remesh_result` with no triangulation.

So `Remesh → Paint → Commit` — an ordinary workflow, and the one the
orthotist's screenshots are taken on — ended in a Python traceback popup. **No
suite in the battery had ever committed a region on a quad mesh.** Another
route with different semantics and no gate, exactly the #49k lesson.

Fixed with one shared helper, `_tri_bvh`, which fan-triangulates and returns a
triangle → owning-face map. Fan-triangulating ourselves rather than passing
`all_triangles=False` keeps the hit indices meaningful: callers look faces up
by the index the tree reports, so the owner map has to be ours. Two triangles
of the same quad are excluded from self-intersection pairs.

Gated by `quad_scan.*` in `tools/goldenroutetest.py`, demonstrated RED on the
unfixed code (`commit_does_not_crash=FAIL RAISED`) and green after.

## …and the quad route's wall quality is the worst measured

With the crash gone, the commit completes and delivers full depth (core
19.95 mm of 20 mm) — but the wall is far worse than any other route:

| route | p95 | max | >30° | shading max |
|---|---|---|---|---|
| painted (triangles) | 17.57 | 38.76 | 8 | 17.71 |
| library v2 (triangles) | 20.73 | 38.91 | 3 | 20.04 |
| circular (triangles) | 31.09 | 58.47 | 22 | — |
| **quad remesh, painted** | **59.61** | **134.59** | **86** | **51.30** |

A 134° dihedral is a fold, not a crease. This is very likely what the
orthotist's screenshots show — the hard plate down the left side of the pad on
a quad-remeshed model. Recorded as the next defect; **not** gated on quality
yet, because a second permanently-red gate would normalise a red suite.
