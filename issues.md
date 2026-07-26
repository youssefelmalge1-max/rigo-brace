# Rigo Brace Designer — Tool Audit / Issues Log

**Audit:** 2026-07-03, all 70 `rigo.*` operators exercised in a live Blender 5.0.1
session via the MCP bridge against `Brace Sample.stl` (53,865 verts), measuring real
geometry (vertex displacement, bbox, counts), not just return codes.
**Re-verify + fix wave:** same day (DEC-0015). Every finding was re-checked against the
source code and a fresh live session before fixing — **most original findings turned out
to be audit-method artifacts**, documented below so we don't re-chase them.
**Trim/state/thickness hardening:** 2026-07-13 (DEC-0035). Visible-only trim editing,
complete source records, explicit TRIM/BRACE state, exact outer-wall intersections and
transactional collision cancellation are recorded in issues 16–18.

**Sample note:** `Brace Sample.stl` is in **mm** (raw bbox 638×396×252), watertight,
looks like a **limb scan** (not a torso), and imports lying on its side (long axis on X).

---

## Status summary

| # | Finding | Status |
|---|---|---|
| 1 | Remold crash on Blender 5.0 | ✅ **FIXED** (Patch A) |
| 4 | History ignores `brace_patient` | ✅ **FIXED** (Patch B) |
| 12 | Viewport capture black late in pipeline | ✅ **RESOLVED** — not reproducible after #1's fix; hardening documented (Patch C) |
| 2 | "Corset has no shell" | ❌ **INVALID** — audit artifact |
| 3 | Object/collection accumulation | ⤵ **DOWNGRADED** — mostly audit artifact; 1 real edge logged (#13) |
| 5 | `place_landmark` no-op | ❌ **INVALID** — audit artifact |
| 6 | Silent CANCELLED (emboss/slots/landmarks) | ❌ **INVALID** — all three `self.report()` properly |
| 7 | `pad_type` enum empty | ❌ **INVALID** — callback returns 8 items |
| 9 | `align_quad` leaves quad on | 🔵 **BY DESIGN** — Quad View button is the off-toggle |
| 10 | Measure ops unverified | ✅ verified indirectly — corset shell + emboss + pads all measurably work; keep an eye on `scale_girth` in Patch 7 |
| B1 | Modal-only operators untestable headlessly | 🔵 open (by design) — execute fallbacks are a Patch-4+ nicety |
| 13 | Corset generated mid-deform copies the live SIMPLE_DEFORM | ✅ **FIXED** — Generate requires Apply/Reset |
| 15 | Pressure-library GUI failure modes | ✅ **FIXED** — modifier, visibility and cursor guards |
| 14 | Pinch/non-manifold trim edge in legacy shell path | ✅ **FIXED/SUPERSEDED** — paired wall + explicit rim + QA gate |
| 16 | Back-side trim point selected through the body | ✅ **FIXED** — visible-only picker + modal recovery |
| 17 | Thickness/source edits leave a stale brace actionable | ✅ **FIXED** — TRIM/BRACE state + Update Brace gate |
| 18 | Outer offset intersections at larger thickness / B | ✅ **CONTAINED TECHNICALLY** — exact repair-or-cancel; B clinical readiness remains blocked |

| 19 | Painted trimline torn at the FRONT seam -> shell fragments / "does not create" | ✅ **FIXED** — unwrap + replica containment; 0.33 % → 99.47 % mask agreement |
| 20 | Fragmented multi-piece brace passed every manufacturing gate | ✅ **FIXED** — `components != 1` now blocks in `_validate_finished_rim` |
| 21 | "Smooth Mask" passes meant 12 mm on a 1 mm mesh, 49 mm on a 4 mm mesh | ✅ **FIXED** — `trim_smooth_mm`, one Gaussian pass in millimetres |
| 22 | Smoothing deviation under-reported (dense loop, not delivered curve) | ✅ **FIXED** — measured post-decimation on the delivered curve |
| 23 | Trim control density capped at 84 by the RIM FILLET, not the trimline | 🔴 **OPEN** — 168/240 give 5-8 rim overlaps; needs rim rework |
| 24 | Curve generator not reproducible run-to-run (same inputs, different mesh) | ✅ **FIXED** — unordered BMVert set fed to `remove_doubles`; now index-sorted, 4/4 |
| 25 | Cylindrical projection is non-injective over arms/axilla (multi-sheet) | 🔴 **OPEN** — reviewer measured 8.29 % of a slice hitting 2+ sheets |
| 26 | Legacy `rigo.generate_corset` ignores the paint mask entirely | 🔴 **OPEN** — can keep the complement of what was painted (~10 % retention) |
| 27 | `designtest` fails: 2 non-manifold edges from the legacy generator | 🔴 **OPEN, PRE-EXISTING** — identical failure with the seam fix disabled |
| 28 | `outlinetest` fails: `rigo.edit_outline.poll()` context incorrect | 🔴 **OPEN, PRE-EXISTING** — identical failure with the seam fix disabled |

---

## ✅ Fixed

### #1 — Remold crash on Blender 5.0  → FIXED (Patch A)
`remold_ops.py` used `tool_settings.unified_paint_settings`, **removed in Blender 5.0**
(moved onto the per-mode `Paint` struct — verified empirically: only
`tool_settings.sculpt.unified_paint_settings` exists). Fix: enter Sculpt mode *first*
(`ts.sculpt` is created on first entry), then set unified size/strength via a
version-tolerant helper `_unified_paint_settings()`; `remold_apply_sliders` now warns
"Enter Remold mode first" instead of crashing outside sculpt.
**Proof:** `tools/remoldtest.py` → `remoldtest_result.txt` PASS=True (SCULPT entered,
unified size == 77 exactly, strength == 0.660 exactly, re-apply 42/0.330, back to
OBJECT). Also cycled live over MCP with no exception.

### #4 — History now keyed to the patient  → FIXED (Patch B)
`history_ops.py::_init_history` read only `obj.name` and then overwrote
`settings.brace_patient`. Fix: the orthotist's typed patient name wins —
`patient = (settings.brace_patient or "").strip() or obj.name`; existing histories keep
their stamped `obj["rigo_patient"]`.
**Proof:** `tools/historytest.py` extended → PASS=True: versions named
`00_QA Patient_FILE` / `01_QA Patient_CLEAN` in a "QA Patient" collection; empty-name
fallback still uses the object name; Next/Back/Rollback/forward-rebuild all still green.

### #12 — Black viewport captures  → RESOLVED (Patch C)
Bisect in a clean session: capture is bright (mean RGB ≈ 0.73) at baseline, after
`generate_corset`, during outline Edit Mode, with quad view on/off, and after the FULL
heavy pipeline (fixed remold cycle + pads + bend applied + emboss). **Not reproducible
once #1 no longer crashes** — the audit's black frames directly followed the remold
`AttributeError`, and an operator dying mid-execute can corrupt UI state. Hardening
documented in `orthoblender-spine-skill/docs/blender_mcp_setup.md`: brightness-check
every capture, `wm.redraw_timer` retry once, restart the bridge if it persists.

---

## ❌ Invalidated by re-verify (audit-method artifacts — lessons logged in ERR-0009)

### #2 — Corset shell works
`generate_corset` → `_build_corset` adds a Solidify "Shell" (`corset_thickness`) and
**applies** it ([design_ops.py:120-126](rigo_brace/operators/design_ops.py#L120)).
Re-verify: "Rigo Corset" exists with **89,860 verts ≈ 2× the trimmed surface** (inner +
outer wall baked) and survives the edit→apply outline round-trip. The audit had (a)
inspected `Rigo Corset Base` — the intentionally hidden single-wall cache — and (b) used
a "has a live SOLIDIFY modifier" heuristic, which is blind to *applied* modifiers.

### #5 — `place_landmark` works
It places the selected landmark at the 3D cursor ([landmark_ops.py:63](rigo_brace/operators/landmark_ops.py#L63)).
Re-verify created `LM_C7`. The audit counted landmarks **after** running
`clear_landmarks` in the same batch — ordering bug in the audit script, not the add-on.

### #6 — No silent cancels
`emboss_text` reports "Type some text first", `cut_slots` reports "Place at least one
slot first", `toggle_landmarks` reports "No landmarks placed yet". Scripted `bpy.ops`
calls can't see `self.report()` output — the messages exist and show in the UI.

### #7 — Pad dropdown populates
`pad_library` enum callback returns **8 items** (builtin clinical entries). The audit's
`bl_rna.enum_items` introspection returns empty for *dynamic* callback enums by design.

### #3 — Object accumulation: mostly the audit's own doing
The `Brace Sample.001…007` dupes came from the audit re-importing the STL 7 times; the
lingering `Rigo Bend Axis` came from the audit **abandoning** a deform session mid-way.
Real behavior: `deform_apply` freezes drivers then removes all helpers
([deform_ops.py:341](rigo_brace/operators/deform_ops.py#L341)); `deform_reset` calls
`_clear_deform`. One real edge remains → #13.

### #9 — `align_quad` is a one-way "on" by design
It comments this explicitly; the View panel's Quad View button is the toggle off.

---

## Mixed follow-up records (current status is stated per item)

### #13 — `generate_corset` during a live deform session copies the modifier
✅ **FIXED (Patch 7, DEC-0021):** `generate_corset` now refuses with "Apply or Reset the
active Bend/Twist/Stretch before generating" — the orthotist decides the deform's fate.
Verified in venttest (guard phase).

### #15 — Pressure library "does not work" (user report) → 4 GUI failure modes, FIXED
Live re-verify (DEC-0022) proved the engine exact (apply == set depth to 0.01 mm;
favourites persist across real restart). The real bugs were UX: (1) 🔴 **hard freeze**
placing a shape while the scan had a live modifier (reproduced, >2 min wedge) — now
refused instantly with the modifier named; (2) misleading "reset the active deform"
message — now names the actual modifiers; (3) invisible result when a visible corset
hides the scan being modified — now warned on place/apply; (4) At-Cursor snapping to an
unexpected spot when the 3D cursor was never placed — now warned when the snap travels
> 200 mm. Proof: tools/padfavtest.py PASS (7 phases); padtest + padshapetest + selftest
regression green.

### #14 — NEW: `generate_corset` can leave a pinch edge at the trim
**FIXED/SUPERSEDED (2026-07-13):** the active generator no longer uses the diagnosed
post-trim Solidify path. It builds corresponding inner/outer walls and one explicit rim,
then applies manifold and exact-intersection QA. Current 2/4/6 mm reference fixture runs
have zero boundary and non-manifold edges. Requests that cannot meet the collision gate
cancel before replacing the valid shell. The historical limb-sample observation remains
here to explain why the old path must not return.

### #B1 — Modal-only operators have no headless path
`pick_landmark`, `pick_deform_range`, `place_pad`, `place_slot` require a real viewport
(click-on-surface) — fine for users, invisible to tests. Add execute fallbacks
opportunistically as their stages get rebuilt (Patch 4+).

## ✅ Fixed in the 2026-07-13 trim/state/thickness wave

### #16 — Back-side trim point selected through the body → FIXED
`Edit on Body` previously picked the nearest control in screen space, so a hidden back
control could win when it projected to the same pixel as the intended front control.
The picker now reverse-ray tests each candidate against the evaluated corrected body and
temporarily disables in-front curve display. Ctrl+Z restores the last completed point
move, Esc restores the full edit-session snapshot, and Enter commits. The legacy edit
entry routes to this guarded surface editor. Edit-on-Body raycasts now clamp the
orthographic view origin to a scan/view-derived distance for precision and use an
unbounded BVH travel distance. This replaces the former fixed 1000-Blender-unit limit
without leaving the origin at the 100 km viewport far clip.
**Regression:** `tools/trimvisibilitytest.py` invokes the registered modal, queues a
viewport-window click that proximity alone would assign to the hidden control, verifies
that only the visible control is selected and dragged, then queues Esc and verifies the
full snapshot and prior in-front state are restored. It retains transformed-scan kernel
checks, runs the modal in orthographic view, and measures the moved point at 1.499955 mm
from the body.

### #17 — Stale brace after thickness or source edits → FIXED
The generated brace is now explicitly derived from its requested settings, corrected
body and unified perimeter. Changes call `mark_brace_dirty`; native source edits are
detected by `geometry_signature`. **Edit Trimlines** shows/selects only the source body
and perimeter, while **Brace Preview** shows/selects only a clean canonical brace.
Finishing, QA and export refuse stale geometry until **Update Brace** succeeds.
Both source signatures are mandatory. A new patient import removes the prior trim curves,
and Generate rejects a perimeter whose Shrinkwrap target is not the current scan. UI and
operators share `brace_ready_for_finishing`; an unrecorded built thickness is shown as
unknown rather than 0 mm.
**Proof:** `tools/designviewtest.py` and `tools/thicknesstest.py` → `PASS=True`; a 4-to-6
mm change blocks QA/export and writes no STL until regeneration.

### #18 — Outer-wall intersections at larger requested spacing → CONTAINED
BVH candidates now pass exact coplanar/non-coplanar triangle narrow-phase checks. Only
outer directions belonging to colliding triangles are blended toward neighbours; every
direction remains normalized, so paired inner/outer construction distance stays at the
request and the patient-contact inner surface is unchanged. Repair stops after 12 passes
or 25 degrees from the original direction. Unresolved candidates cancel transactionally.
Known and unexpected generator exceptions remove both private candidate objects and
restore the previous view/outline state before return or propagation.
**Proof:** `tools/meshintersectiontest.py` and `tools/thicknesstest.py` → `PASS=True`.
The current reference fixture generates exact 2/4/6 mm paired distances, with independent
bidirectional-ray medians of 1.999/3.999/5.998 mm and add-on QA minima of
1.740/3.654/5.386 mm. The 2 mm case fails the configured QA threshold; the 6 mm case
repairs 25 collision pairs to zero in seven passes with a maximum 18.287-degree direction
change. A 12 mm attempt retains the prior valid 6 mm shell/base and leaves no candidates.
`tools/btrimlinetest.py` reports the unresolved 4 mm B overlap separately as
`SAFETY_PASS=True`; `manufacturing_qa_ready=False`, `READINESS_PASS=False` and overall
`PASS=False`. B design readiness is unresolved.

---

## Verified-working map (from the audit, unchanged)
- **View/UI:** view_axis, ortho, quad, fullscreen(poll), align_quad, tabs, ground,
  measure, workspaces(poll).
- **Clean:** center_model, verify_clean (counts stashed), fill_holes, smooth,
  erase_toggle, recenter_floor, remesh (107k→43k faces, watertight).
- **Align:** realign_tool, move_tool, recenter_floor.
- **Landmarks:** place (3D cursor), clear, toggle; pick = modal.
- **Shape:** paint_select, grow/shrink/invert/clear, **push_selection exact 10.000 mm**,
  thicken, smooth, delete.
- **Deform:** start (modifier + Origin/From/To helpers), bend verified (eval bbox),
  apply (drivers frozen, helpers removed), reset.
- **Pads:** add/edit/update/apply/mirror/record/favourite/clear/delete (8 library items).
- **Correction cage:** build (lattice), edit, apply, reset.
- **Remold:** toggle + apply_sliders (post-fix).
- **Design:** unified surface trim, visible-only trim picking, exact paired-shell
  generation with repair-or-cancel, explicit TRIM/BRACE states, stale-output blocking,
  edit/apply/reset legacy outline compatibility, emboss (with text), cut/clear slots.
- **History:** next/back/rollback, patient-keyed (post-fix), forward-rebuild.
- **IO:** import_scan/import_xray/export_brace poll OK (file dialogs), xray_grab modal.

## 2026-07-25 — painted-trim seam wave (issues 19-26)

### #19 — Painted trimline torn at the front seam → FIXED
The brace region is decided in a cylindrical `(theta, z)` plane; every consumer stored
`angle % tau`, putting the seam at **theta = 0, the patient's front**. Any painted
region covering the front was split across both ends of the domain and the odd-even
containment test was meaningless. **Measured on the A fixture: perimeter-vs-mask IoU
0.003329 before, 0.994659 after.** Fixed by `_unwrap_uv_polygon` (continuous unwrap +
winding check), `_inside_unwrapped_polygon` (test every 2π replica in span) and
`_clip_triangle_cylindrical` (triangle-local unwrap).
**Why it hid for months:** the Rigo template's opening sits ON the seam, so every
existing painted-trim test painted a region that never crossed it — 0/1512
misclassified for the template case vs 792/1512 for a front-covering one.
**Proof:** `tools/customtrimseamtest.py` PASS=True; customtrimtest, trimqualitytest,
curvebuildtest, selftest all green.

### #20 — Disconnected ribbons passed every gate → FIXED
`_validate_finished_rim` checked boundary edges, non-manifold edges, zero-area faces
and self-intersections — **but never the connected-component count**, so N detached
closed ribbons were "valid". This is what let a fragmented mesh reach the user.
`_connected_component_count` + a `components != 1` refusal now block it in production,
not only in tests.

### #23 — Trim control density is limited by the rim fillet → OPEN
`_MAX_CUSTOM_CONTROLS = 84` gives ~24 mm control spacing on a 2 m perimeter, so
smoothing requests finer than that are limited by the curve rather than the filter.
Raising it to 168 or 240 produces a faithful perimeter but then 5-8 local rim overlaps
from `_validate_finished_rim` — the fillet profile self-intersects at tight turns.
**The ceiling belongs to the rim builder.** Reverted to 84; the delivered-curve
deviation is reported so the limit is visible rather than hidden.

### #24 — Curve brace build was not reproducible → FIXED
`curvebuildtest`'s determinism check was flaky **both before and after** the seam fix
(fixed code True/False/False, pre-fix False/True/True over three runs each) — so it was
never caused by the seam work. `tools/curvestagedbg.py` hashes the candidate mesh after
each build stage and localized it exactly, reproducibly:

```
stage                     pos_same  set_same   nverts
00_before_intersect          True      True     44574
01_after_exact_intersect     True      True     52506
02_after_keep_interior       True      True     27937
03_after_weld_slivers       False      True     27579   <- diverges here
04_after_paired_shell       False      True     80554
```

`set_same=True` with `pos_same=False` means identical geometry in a **different vertex
order**. Cause: `_cut_boundary_vertices` returned a Python `set` of BMVert, whose
iteration order follows memory addresses and changes between sessions;
`remove_doubles` keeps whichever member of a coincident pair comes first. Fixed by
pinning the order to `vertex.index`. After the fix every stage is positionally
identical and `curvebuildtest` passes **4/4** (was ~1/3).
**Same patient + same settings must give the same brace** — this was a genuine
clinical-reproducibility defect, found only because the seam work forced an A/B.

### #25/#26 — Found by adversarial review, not yet addressed → OPEN
The cylindrical projection assumes the body is star-shaped about a vertical axis at
every z; with arms/axilla, **8.29 %** of a measured slice has rays hitting 2+ sheets,
and both sheets are retained — a plausible source of the "large flat wing" in the user
screenshot that the seam fix does **not** touch. Separately, the legacy
`rigo.generate_corset` never reads the paint mask (only `curve_build_ops` votes on
keep-inside/outside), so it can retain the complement of the painted region. The
proposed resolution for both is a mesh-native flood fill from the painted seed,
replacing the parameterization in the containment step only.

---

### #27 — Serrated / pinched / spiky rim → FIXED
Root cause measured, not assumed: cut-boundary spacing varied 51x, and the per-vertex
fillet ceiling (0.35 x spacing) dragged the rim amplitude with it — 8.6x radius spread,
1455 adjacent jumps >25 %, 2 genuine frame reversals, aspect p99 7.95. Fixed upstream by
uniform arc-length resampling of the cut boundary before the rim is built
(`_resample_cut_boundary`): desliver, split (`use_single_edge=True` — without it faces
become n-gons with collinear midpoints that later triangulate to zero area), corner-
anchored collapse, tangential relaxation with fold-revert, crossing repair, and ear
removal (interior chords and quad DIAGONALS that shortcut a trimline kink — the
diagonal never exists as an edge, so only face-level repair sees it).
After: spacing ratio 3.6, radius 0.17-0.30 (uniform at request), 2 jumps, 0 reversals,
0 self-intersections, aspect p99 3.40. Verified by `rimqualitydbg` and gated forever by
`rimresampletest` (uneven reference cut + hostile crowded/notched trimline + thin-wall
QA negative). Commit follows this entry.

### #28 — Rim-exclusion export guard still blocks curve braces → OPEN (user decision)
With the resampled rim, a 4 mm curve-built brace passes every substantive export check
(min wall 3.46 mm vs 3.0 required, coverage 1.0, one component, manifold, zero
self-intersections) but `thickness_excluded_fraction` = 29.7 % > 20 % (was 40.5 %
before resampling). The guard was calibrated for the legacy bevel rim; the rounded rim
is legitimately vertex-dense. Decision deliberately deferred to the user.

### #29 — Deep or zero-radius trimline notches are refused upstream → OPEN (documented)
Measured while building the hostile regression fixture: a 30 mm vector-cornered notch
folds the Exact cutter (non-manifold boundary, pre-resample); at 20 mm the 4 mm outer
wall cannot offset around a zero-radius corner (outer-wall repair refuses); a 30 mm
fully-rounded notch still folds the cutter; 15 mm rounded + a 3-controls-in-10-mm
cluster builds cleanly. All refusals are transactional with the previous brace
retained — correct behaviour for unmanufacturable input, but the error text could
name the notch. The auto trimline itself contains one hairpin (~1.8 mm across) that
the cut cannot follow, producing a single 5.1 mm boundary-fidelity outlier (p95 is
0.95 mm).

### #27 addendum — default 1.0 mm fillet exposed a spacing ceiling
The trio slotbracetest / referencetrimtest / thicknesstest run the DEFAULT 1.0 mm
fillet, which drove the resample target to 2.5 mm spacing — too coarse to articulate
the trimline's 1.8 mm hairpin nub, whose collapsed fold the rim strip then crossed
(4 wall-vs-rim overlaps; every audit had accidentally overridden the radius to
0.3 mm and missed this). Fixed by capping target spacing at 1.2 mm — the finest
configuration proven clean — so delivered fillet radius is spacing-limited to
~0.42 mm regardless of larger requests, reported in `rigo_trim_fillet_*` and
consistent with the property's documented contract. Two supporting fixes landed with
it: the ear splitter prefers INTERIOR corners (connecting kink to boundary corner
re-created the chord it was removing — a livelock), and boundary fidelity is now
measured against the trimline POLYLINE, not its ~0.6 mm-spaced samples (sliding
along the curve is not deviation; measured honestly the reference p95 fell
0.948 -> 0.026 mm and the hairpin max 5.085 -> 2.733 mm - the resample barely
moves the trimline at all).
After all three: slotbracetest PASS; referencetrimtest and thicknesstest build
perfect geometry (median walls 2.000/3.999/5.998 mm) and fail ONLY on the #28 guard.

### #30 — Visible shading seam where the rim strip meets the shell → DIAGNOSED, fix scoped
User-visible tonal break along the trimline (screenshots 2026-07-26). Measured with
`tools/rimseamdbg.py`: it is GEOMETRIC, not shading and not mesh density — the rim
strip meets both wall faces at a 75.2/75.1-degree median dihedral along the whole
trimline (2245 edges each side), producing a 35.7-degree median vertex-normal jump at
ring 0; wall rings 1-6 measure 0.9-1.2 degrees (smooth), so the density transition
theory (external review) is refuted. Root cause: the curve generator's sine-bulge
profile never cuts the wall back, so the corner the fillet should remove still stands.
SIX profile-level cut-back constructions were implemented and measured (tangent
arc-flat-arc: 568 overlaps from wall-fan folds; two depth-clamp variants: 10/12;
fan-edge slide: 58 from ring zigzag; translation + both-wall clamp: 12; +20-degree
junction margin: 15). The residuals are tens-of-micrometre grazes of the arc against
wall FACETS — fillet radius (~0.35 mm), facet size (~1 mm) and fan depth (~0.5-1 mm)
have no separation of scales, so per-vertex heuristics cannot win against the exact
(0.1 um) intersection validator. All attempts REVERTED; the shipped rim is the green
sine-profile build. The scoped fix is `bmesh.ops.bevel` (clamp_overlap) applied to the
two junction edge loops after the shell is built, with rim/band vertex groups remapped
from the bevel output — pending user approval. Measurement tooling kept:
`rimseamdbg.py` and a report-only junction-dihedral line in `rimresampletest`.

### #28 UPDATE — Rim-exclusion guard replaced with a structural-wall metric → FIXED
The old guard divided excluded vertices by EVERY shell vertex, so it measured rim
tessellation density, not safety: a correctly built rounded rim reported 29.7 % (and
rose to 41-47 % as rim detail increased) while the wall it protects measured 3.41 mm
against a 3.0 mm requirement. Replaced in `qa_ops` by
`structural_wall_exclusion_fraction`: rim-provenance vertices (ring, fillet profile,
and any future bevel output - all carried in the semantic `RIGO_RIM_BOUNDARY` group,
never index ranges) leave BOTH sides of the ratio, and a structural-wall vertex counts
as excluded only when EVERY triangle carrying it also touches rim geometry, so no
sampling stride could ever reach it. Measured: reference brace 0.01 % (4/47886) and
QA now PASSES; fillet segments 4 -> 12 moved the rim fraction 34.0 -> 47.1 % while the
guard moved 0.00pp; a diffusely shadowed wall still fires at 41.5 %; a 1.5 mm wall
still fails on minimum thickness; ring-only and untagged (legacy) braces evaluate
correctly. Diagnostics keep reporting all three percentages. Gated by
`tools/qaexclusiontest.py`.

### #30 UPDATE — Junction bevel measured and rejected; seam remains OPEN
`bmesh.ops.bevel` on the two junction loops does remove the crease and, unlike the six
profile-level constructions, produces NO self-intersections (it only cuts material
away). But it trades the seam for sliver triangles, monotonically:

    segments  aspect_p99  aspect_max  seam normal-jump  hostile trimline
    none         3.40         41          37.5 deg      builds
    3          151.35        218.55        6.9 deg      fails (14 overlaps)
    2           98.87        144.19       10.0 deg      fails (6 overlaps)
    1           48.74         75.15       18.7 deg      builds, but p99 4415 / max 47064

Mechanism: `clamp_overlap` buys intersection-safety precisely BY collapsing the offset
toward zero wherever geometry is tight, and a collapsed offset IS a sliver - so safety
and mesh quality are in direct opposition, and no segment count escapes it. Skinny
triangles near the trimline were item 3 of the original artifact report, so this is not
an acceptable trade. REVERTED; shipped geometry is unchanged.
Conclusion for the next attempt: the seam is not fixable by local surgery at this
scale - the rim (0.3 mm) is an order of magnitude smaller than the wall facets
(~3.7 mm). A tangent fillet needs room to exist, which means a finer, graded wall mesh
in a band around the trimline FIRST. That is the one part of the external review's
proposal the measurements support - not as the cause of the seam, but as the
precondition for fixing it.

### #30 UPDATE 2 — Graded transition band measured and rejected; seam CLOSED as not-fixable-here
The external review's core proposal - widen the trimline band and grade edge length
gradually outward - was implemented and measured. The grading itself worked exactly as
specified: wall edge length now stepped 0.75 -> 0.83 -> 1.55 -> 2.83 -> 3.69 -> 3.76 mm
outward from the trimline (ratios 1.11/1.87/1.83/1.30/1.02), the build stayed clean,
and the cost was +24k faces (118k -> 142k).

The seam did not move: JUNCTION vertex-normal jump 37.484 -> 37.518 degrees.

Reason, which settles the argument: the wall is locally FLAT over its 3.7 mm faces, so
every sub-face produced by subdivision inherits the same normal. Refining a flat region
cannot change vertex normals at all - density only affects shading where the surface
curves. The 75-degree crease is a genuine geometric corner and only geometry can soften
it.

Band + bevel together was then measured, on the theory that a finer wall would let the
bevel cut cleanly: it did not. Aspect p99 went from 98.87 (coarse wall) to 196.84 (fine
wall), and the hostile trimline failed with 19 collapsed faces. The finer mesh amplified
the bevel's failure mode instead of relieving it.

Ten distinct constructions have now been measured for this seam: six profile-level
tangent arcs (all self-intersect), three bevel configurations (all produce slivers,
monotonically trading seam against aspect), and the graded band (no effect). All
reverted. CONCLUSION: the seam is not fixable within the present rim architecture. It is
cosmetic only - trimline position, wall thickness, manifoldness, self-intersection and
QA are all unaffected, and the physical edge is hand-finished after thermoforming.
Any future attempt should change the architecture (build the rim as a swept solid
unioned onto a trimmed-back wall, rather than a strip bridging two offset walls), not
tune the current one.

### #31 — Rim cap made tangent; the seam is FIXED
The crease was the cross-section curve, not the architecture. `_rim_profile` placed its
points at LINEAR fractions across the wall with a sin(pi*f) outward bulge; substituting
f = u/t that is a sine arch w(u) = r*sin(pi*u/t), whose slope where it meets the wall is
pi*r/t. It therefore left a crease of atan(t / (pi*r)) against BOTH walls at EVERY
radius - 74.7 degrees predicted for t = 4.0 mm and r = 0.349 mm, against 75.2/75.1
measured. Because that slope is finite for any finite radius, a sine arch can never be
tangent, which explains all ten earlier failures at once: they were treating a symptom
of a wrong curve.
Replaced by a quarter arc leaving the inner wall along +outward, a straight closing run,
and a quarter arc arriving at the outer wall along -outward (r clamped to t/2, where it
degenerates to an exactly tangent semicircle). Chords are allocated to the arcs, not
spread by arc length: junction dihedral is exactly 45 deg / (chords per arc), and
uniform sampling spends the budget on the flat and leaves 45 degrees.
Measured: seam normal jump 37.48 -> 7.58 deg median (40.07 -> 9.44 p95), cap dihedral
p95 75.68 -> 30.01, self-intersections 0, zero-area 0, aspect p99 3.40 -> 7.99 (max
41.0 unchanged), trimline p95/max 0.026/2.733 mm unchanged, vertex and face counts
IDENTICAL. Hostile hairpin builds clean. Battery 12/12, determinism 4/4. Visually the
hard black seam line is gone and the rim reads as a rounded edge (rimshot_*.png).
Commit 8668f95.

### #32 — The 0.35 x spacing radius ceiling is REAL, not conservative padding
The architecture review argued this term was unmotivated, since spacing runs ALONG the
boundary while the cap bulges PERPENDICULAR to it, and that overlap is governed by
curvature alone. That argument is WRONG, and the sweep proves it:
    4 mm wall, reference trimline : clean at 0.35/0.5/0.75/1.0/1.5/2.0
    4 mm wall, hostile hairpin    : clean to 0.75, then 12/13/19 overlaps
    6 mm wall, reference trimline : clean ONLY at 0.35; 0.5 already gives 2 overlaps
Raising it to 0.75 on the strength of the 4 mm results alone broke the 6 mm wall in
thicknesstest (10 overlaps). Thicker walls carry the cap further from the surface, so
neighbouring profiles converge sooner - a limit the curvature clamp does not cover.
Reverted to 0.35, now a named constant carrying this evidence. The delivered radius
therefore stays ~0.35 mm against a 1.0 mm request; closing that gap needs a
thickness-aware ceiling (a function of wall thickness, not a constant), which is
unbuilt. Do not raise it without sweeping wall thickness as well as trimline shape.
