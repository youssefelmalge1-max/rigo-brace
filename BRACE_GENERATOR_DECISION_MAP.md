# Brace Generator Redesign - Decision Map

Goal: replace the current scan-copy/face-delete generator with a clinically traceable,
smooth, measurable and manufacturing-safe brace pipeline. The map is sequenced; clinical
correctness remains the orthotist's decision.

## #1: What does a correct generator need to represent?

Blocked by: none
Type: Research

### Question

What workflow, clinical inputs, geometry stages and safety gates are supported by the
project references, LeoSpinal/Rodin4D public material and peer-reviewed literature?

### Answer

Resolved. See `orthoblender-spine-skill/knowledge/brace_generator_research.md`.
The current generator is structurally invalid: it deletes whole faces by face-center,
stores top/bottom as unrelated cyclic curves, and the auto-trim path omits the designed
opening. Smoothing cannot repair that representation. The target requires a prescribed
corrected inner surface, one continuous perimeter, exact contour insertion, explicit
inner/outer walls and rim, then geometric/manufacturing QA.

## #2: What is the minimum clinical prescription schema?

Blocked by: #1
Type: Discuss

### Question

Confirm the orthotist-entered fields that generation must require: Rigo subtype and side,
D modifier, curve/apex/end levels from X-ray, pelvic behavior, sagittal objective,
pressure/expansion pairs, opening side, superior/inferior coverage and strap levels.
Surface landmarks alone cannot infer these safely.

### Answer

Partially resolved for technical generation: Rigo type remains manually selected and all
templates require orthotist review. Existing surface landmarks provide the coordinate
frame and coverage anchors. Automatic clinical prescription remains excluded until the
full radiographic/prescription schema is agreed.

## #3: Can one editable continuous perimeter reproduce the A reference coverage?

Blocked by: #2
Type: Prototype

### Question

Build a single closed surface curve in cylindrical `(theta, z)` coordinates: upper trim,
first opening edge, lower trim, second opening edge, with tangent-continuous fillets at
all four joins. Drape it onto the corrected mold and compare it visually with A/B clinic
references.

### Answer

Implemented for A/B templates as one cyclic 42-point Bézier perimeter. It contains upper
coverage, both opening sides and reversed lower coverage; a live Shrinkwrap constraint
keeps evaluated edits on the corrected mold. A user visual check is pending.

## #4: Which exact mesh-cut method is robust on irregular scan topology?

Blocked by: #3
Type: Prototype

### Question

Compare edge-sign contour insertion/marching triangles against a watertight boolean
cutter on the supplied scans. Gate exact contour distance, manifoldness, triangle quality,
runtime and repeatability. Whole-face deletion is excluded.

### Answer

Implemented with cylindrical parameter-space polygon clipping. Crossed triangle edges are
split at the evaluated perimeter intersections; whole-face-center deletion is bypassed.
Sub-0.3 mm fragments and extreme-aspect short-edge triangles are collapsed and locally
beautified. A test requires one component and zero boundary/non-manifold edges.

## #5: How should the shell and rounded rim be constructed?

Blocked by: #4
Type: Prototype

### Question

Construct corresponding inner/outer surfaces and an explicit rim strip, preserving the
single perimeter topology. Determine safe offset handling, uniform thickness measurement,
corner fillet representation and surface-preserving fairing.

### Answer

Implemented with explicit paired inner/outer walls. The cut surface retains normals
interpolated from the complete corrected torso; the outer wall offsets along those
uncut-surface normals, and corresponding boundary edges form the rim strip. This replaces
Solidify, whose post-cut boundary normals folded the rim through the shell. The A fixture
rounds 2,614 rim junction edges with zero intersections; the reference profile rounds
2,294. Thickness QA excludes only the explicit tapered rim vertices and rejects the
exclusion if it exceeds 20% of shell vertices. For locally infeasible thick offsets, an
exact triangle narrow phase finds outer-wall crossings and relaxes only the involved
offset directions, capped at 12 passes and 25 degrees while retaining the requested
paired-vector length. A failed repair cancels transactionally and preserves the previous
valid brace and corrected body.

## #6: How are correction geometry and smoothing preserved?

Blocked by: #2, #5
Type: Prototype

### Question

Generate from the committed corrected mold, preserve pressure/expansion signed-deviation
maps, smooth only high-frequency asperities, and prove that smoothing does not erase
prescribed correction volumes or distort sagittal profile.

### Answer

Partially resolved. The legacy high-strength shrink smoothing was replaced by gentle
volume-preserving Laplacian fairing (default 5 passes). A signed-deviation preservation
gate for committed pressure/expansion regions remains open.

## #7: What quantitative gates define a releasable brace mesh?

Blocked by: #4, #5, #6
Type: Prototype

### Question

Implement unit/orientation, one-component, watertight/manifold, self-intersection,
thickness, perimeter continuity, rim curvature, triangle quality, clearance/deviation,
opening and reference-comparison reports. Material-specific limits remain configurable
and require manufacturing validation.

### Answer

Implemented except signed correction-deviation and anatomy/reference comparison. Current
blocking gates cover mm units, cyclic perimeter, one component, zero boundary/non-manifold
edges, zero zero-area faces, positive enclosed volume/normals, zero self-intersecting
triangle pairs, sampled wall coverage >=80%, configurable minimum sampled thickness,
p95 triangle aspect below 3 and maximum below 100. Export reruns these gates. The current
A fixture passes with 3.360 mm sampled minimum and zero intersections. The new
Rigo-Cheneau reference profile passes with 3.582 mm and zero intersections. BVH overlap
is now only a broad phase; every reported crossing is confirmed by an exact triangle
test, including coplanar cases.

## #8: Does the redesigned generator reproduce the clinic references?

Blocked by: #3, #4, #5, #6, #7
Type: Prototype

### Question

Run A and B model/reference fixtures, signed distance maps, section overlays and rendered
front/back/side comparisons; iterate until all geometry gates pass and the orthotist
accepts the visible trim, surface and rim.

### Answer

Technical trim iteration is complete on A and the independent Rigo-Cheneau reference
profile. The reference profile gates low anterior chest (0.304 normalized), one lateral
wing (0.998 versus 0.469 opposite), pelvic variation below 0.25, a measured 25 mm opening,
full evaluated-curve distance of 1.50 mm from the body, one manifold shell and zero
intersections. Clinical/reference equivalence remains open pending orthotist review.
The B technical fixture still is not clinically ready. Generation now detects that its
requested 4 mm outer wall remains overlapping beyond the 25-degree repair guard and
cancels before creating a canonical brace. B needs an orthotist-reviewed trim/surface
diagnosis; no invalid shell reaches QA or export.

## #9: What is the final clinical acceptance workflow?

Blocked by: #7, #8
Type: Discuss

### Question

Define prescription sign-off, preview approval, manufacturing report, physical fitting,
clinical/radiographic check and design-history evidence required before export.

### Answer

Partially implemented. Export is the last Design action and reruns manufacturing QA;
failed units/topology/intersection/thickness block the STL. Orthotist prescription
sign-off, physical fitting and clinical/radiographic evidence remain open and cannot be
automated by Blender.

## #10: Why does changing General Thickness appear to do nothing?

Blocked by: #5, #7
Type: Prototype

### Question

Distinguish requested paired-wall thickness, post-rim sampled minimum thickness and a
stale generated brace. Prove several requested values in millimetres and define what the
panel must report.

### Answer

Implemented. Thickness, offset, fairing and trim changes mark the existing brace
**OUT OF DATE**; the old geometry keeps its recorded built values and QA/export stay
blocked until **Update Brace** succeeds. The panel reports requested/built thickness,
exact pre-rim paired spacing and the add-on QA ray-sampled minimum. Installed 2/4/6 mm
gates measure exact 2.000/4.000/6.000 mm paired spacing. The add-on QA sampled minima are
1.740/3.654/5.386 mm; 2 mm correctly fails the configured 3 mm manufacturing threshold.

## #11: Should trim generation modify the corrected body or create another object?

Blocked by: #5, #9
Type: Discuss

### Question

Should the corrected patient mold be destructively converted into the brace, or retained
as the immutable clinical source while the generated brace is a separate final object?

### Answer

Recommendation: keep two objects internally. The corrected mold is required for trim
editing, correction traceability, regeneration and comparison; destructive conversion
would break those contracts. The current defect is visual state, not object separation:
the Patient Scan and Rigo Corset remain visible together and look like duplicate braces.
The UI should present one working object at a time.

## #12: What should the user-visible state machine be?

Blocked by: #10, #11
Type: Discuss

### Question

Define visibility, selection and update behavior for trim editing, brace preview and
parameter changes without expensive automatic regeneration.

### Answer

Implemented states:

1. **Edit Trimlines:** show corrected body + orange perimeter; hide generated brace.
2. **Brace Preview:** hide corrected body and perimeter; show/select only Rigo Corset.
3. **Change thickness/offset/fairing:** keep the old brace visible but mark it
   **OUT OF DATE**; change Generate to **Update Brace**. Do not rebuild on every slider
   movement.
4. **Update Brace:** rebuild once transactionally, restore Brace Preview, and display
   Requested Thickness plus Measured Minimum Wall.
5. Explicit **Edit Trimlines** and **Brace Preview** buttons control visibility and
   selection. Finishing tools are disabled outside a current Brace Preview.
6. QA fingerprints the corrected body and perimeter used for generation; native source
   edits also invalidate an apparently clean brace.

## #13: What proves thickness and object lifecycle work?

Blocked by: #10, #12
Type: Prototype

### Question

Define installed-copy regression and user acceptance gates before implementation.

### Answer

Implemented gates:

- Requests of 2, 4 and 6 mm rebuild the wall and change corresponding inner/outer vertex
  separation by the requested amount within 0.05 mm away from the rounded rim.
- Changing thickness after generation sets OUT OF DATE and does not falsely relabel the
  old geometry; Update Brace clears the state only after a successful rebuild.
- The panel shows requested thickness separately from QA sampled minimum thickness.
- Edit Trimlines shows body+line and hides brace; Preview Brace shows brace alone; active
  object and selection match the visible mode.
- Regeneration leaves the corrected mold byte-for-byte unchanged and replaces, rather
  than accumulates, the canonical Rigo Corset.
- QA/export still operate only on the canonical updated brace and all current A/reference,
  trim finishing, QA, export and negative B gates retain their expected results.

Observed installed results: material volume increases monotonically at 2/4/6 mm and an
independent bidirectional-ray sampler reports medians of 1.999/3.999/5.998 mm. The 6 mm
case repairs 25 exact outer-wall collision pairs to zero in seven passes with an
18.287-degree maximum direction change. A deliberately infeasible 12 mm update cancels
without a traceback, retains the valid 6 mm brace/base and removes both candidate
objects.

## #14: Implementation sequence after approval

Blocked by: #13
Type: Prototype

### Question

What is the smallest safe implementation order?

### Answer

Completed in the approved order: measurable-thickness regression; dirty-state callbacks
and source fingerprints; explicit Update Brace; collision-aware transactional rebuild;
trim/brace visibility operators; panel readout and finishing gates; installed-copy
geometry/UI/QA/export suite. The remaining step is the user's visual check on the actual
patient scan and orthotist review.

## #15: How is accidental editing of a hidden back-side trim point prevented?

Blocked by: #3, #12
Type: Prototype

### Question

When front and back controls overlap in screen space, ensure Edit on Body cannot select a
body-occluded point and distort the opposite trim. Define recovery for a mistaken drag.

### Answer

Implemented a front-surface visibility gate. Candidate controls are projected to the
viewport, but a reverse ray toward the viewer rejects any point blocked by the corrected
body; the pick radius is 18 pixels. The curve is not drawn through the body during the
modal edit. `Ctrl+Z` restores the last committed point movement, `Esc` restores the full
pre-edit snapshot, and the older searchable Edit Trim Line command routes to this guarded
editor. The strengthened regression invokes the registered modal operator, queues a
viewport-window click that is closer to the hidden control by screen distance, drags
24 pixels, verifies only the visible control moves, then queues Esc and verifies the
complete point snapshot and prior in-front display state are restored. It also retains
the transformed-scan visibility-kernel checks.
