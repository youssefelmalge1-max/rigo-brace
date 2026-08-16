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
