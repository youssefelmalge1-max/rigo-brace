# User Verification Guide - Surface-Fitted Trimline and Brace

Readiness: **READY FOR USER CHECK ON THE A/REFERENCE PATH; B IS BLOCKED**  
Clinical status: technical geometry only; orthotist approval is mandatory.

## Start a fresh installed session

Close Blender and reopen the **Rigo Brace** desktop shortcut. This reloads the installed
copy rather than testing only the source folder.

## Exact workflow

1. In **File**, click **Import STL** or **Import OBJ** and choose the patient scan.
   Importing a different patient intentionally removes the prior patient's trim curves;
   place/review this patient's landmarks and create new Auto Trim Lines. Generate also
   refuses a perimeter that is still attached to another scan.
2. In **Scan**, choose the source units, click **Apply Units**, orient the patient upright,
   clean the mesh, and verify its dimensions in millimetres.
3. In **Landmarks**, place the trochanters, ASIS, PSIS, waist, axilla/shoulder, and other
   prescription landmarks accurately. The automatic profile is only a starting shape.
4. In **Mesh Edit**, complete and commit pressure, expansion, and segment corrections.
5. In **Design > Auto Trim Lines (Rigo)**:
   - choose **Rigo-Cheneau Reference**;
   - set **Opening Width (mm)**, initially 25 mm for this verification;
   - click **Auto Trim Lines**.
6. Click **Edit on Body**. Left-drag a visible control point. A hidden back-side point is
   rejected even when it overlaps the front point on screen. Orbit/pan/zoom normally,
   press `Ctrl+Z` to restore the last moved point, `Esc` to restore the complete pre-edit
   contour, or `Enter` to accept. Enter rebuilds smooth, bounded tangents and refits every
   control to the body. Use **Smooth + Fit** to perform the same repair without editing.
7. Confirm the orange line is one continuous perimeter and remains attached to the body
   curvature in front, back, and both side views. Back-side sections are occluded instead
   of being drawn through the patient.
8. In **Select Design**, set **Trim Fillet Radius** (start at 1.00 mm) and **Segments**
   (start at 8), then click **Generate Brace**. The clean **Brace Preview** shows the
   brace alone; use **Edit Trimlines** to show only the corrected body and orange
   perimeter. The generator remeshes and fairs only a narrow trim band, constrains it
   to the body surface, builds the fillet last, and rejects a non-manifold result.
9. Changing thickness, offset, fairing, or trim geometry marks the existing shell
   **BRACE OUT OF DATE**. Click **Update Brace** once; QA/export and finishing remain
   disabled until the rebuild succeeds. A legacy shell without a complete source record
   is also out of date; an unrecorded built thickness is shown as unknown, not 0 mm.
10. For a strap slot, set **Slot Length**, **Slot Width**, and **Edge Fillet** in mm,
   click **Place on Corset**, and click the required local wall. The long axis is
   vertical on the brace and the wire marker is the real rounded capsule footprint.
   Keep the complete capsule away from the trim rim. Right-click or `Esc` ends
   placement; the trash icon clears markers. Click **Cut Slots** only after checking
   every marker. Success displays **CUT: ... vertical rounded slot(s)**. A marker that
   misses the brace, reaches an open rim, crosses multiple walls, or creates invalid
   geometry is rejected; the last valid brace and all markers are retained for
   repositioning.
11. Use trim smoothing, flare, ventilation, or emboss only in a current Brace Preview
   and only when the prescription requires them.
12. **Final Export (after finishing)** is now directly below the generated-brace status
   near the top of Design. Set the clinic/material minimum wall and click **Verify
   Manufacturing QA**, then **Save Brace STL...**. Export reruns the same check and
   stays blocked on failure.

If Auto Trim Lines reports that it cannot fit the scan, first restart the desktop
shortcut to load the current installed copy. Confirm the model is upright, the selected
units have been applied, and trochanter < waist < acromion in Z. The current build handles
non-applied object transforms and can fit isolated shoulder/edge misses to the nearest
body surface, then warns you to review all views.

## What should be visible

- One smooth, continuous perimeter: no gaps, branches, stair steps, or needle spikes.
- A lower anterior chest line, one prescribed tall lateral/axillary wing, and restrained
  pelvic coverage. Confirm the tall-wing side for this patient; do not accept it merely
  because the template generated it.
- The requested anterior opening, measured in millimetres rather than degrees.
- A closed, connected shell with a continuous rounded rim and no wall folding through
  itself. If a tight edited contour cannot accept the requested radius, generation is
  cancelled and the last valid brace is retained; smooth the contour or reduce the radius.
- Pressure/expansion and sagittal corrections retained in the intended regions.
- QA reports one component, zero boundary/non-manifold edges, zero self-intersections,
  and wall thickness at or above the chosen threshold.
- The panel's paired-shell number is the requested construction distance before rim
  rounding. The QA sampled minimum is a separate, usually lower, manufacturing measure.

## Automated evidence from the installed copy

- A fixture: one component, zero boundary/non-manifold edges, zero intersections,
  maximum triangle aspect 12.29, and 3.600 mm sampled minimum wall at a 3.0 mm threshold.
- Reference profile: a point deliberately moved 60 mm away refits to 1.500 mm from the
  body; the entire evaluated curve has 1.500 mm p95/max distance; a requested 25 mm
  opening is retained; the shell has zero intersections and 3.468 mm sampled minimum
  wall.
- Trim-quality stress: a forced `VECTOR` corner measured 33.626 degrees; **Smooth + Fit**
  reduced it to 17.523 degrees while the evaluated line stayed exactly 1.500 mm from the
  body. The current constrained cut loop measures 0.832 mm mean / 1.214 mm maximum edge
  spacing, with a closed manifold shell and zero intersections. The deliberately kinked
  fixture also generates safely after the stronger fairing pass.
- Rounded strap slot: the installed synthetic-wall test cut one vertical 40 x 12 mm
  capsule, changed surface Euler 2->0, retained zero boundary/non-manifold edges, and
  rounded 68 rim edges at 0.8 mm. An off-model marker cancelled with identical
  topology/volume and remained editable. The curved reference-brace test then cut a
  lateral 30 x 10 mm slot and an anterior 40 x 12 mm slot on one brace; Euler changed
  2->0->-2, boundary/non-manifold counts stayed zero, volume decreased twice, and final
  self-intersections remained zero.
- Visible-only editing: the installed registered modal was exercised with real queued
  viewport events in orthographic view. At one screen position shared by a front and
  hidden back control, the hidden point was rejected and the visible point moved while
  staying 1.499955 mm from the body; `Esc` restored the complete pre-edit contour and
  display state.
- Orthographic dragging now clamps the view-ray origin to a scan/view-derived distance
  for precision, then uses an unbounded patient-surface BVH ray. This replaces the former
  fixed 1000-Blender-unit ray limit without leaving the origin at the 100 km far clip.
- Trim finishing: 7,332 band vertices, zero movement outside the band, and exactly
  6.000 mm flare in the regression fixture.
- STL export: the canonical brace alone is written and reimports with zero measured
  dimension error in the fixture.
- Thickness sweep: 2/4/6 mm requests produce exact 2.000/4.000/6.000 mm paired spacing.
  An independent bidirectional-ray measurement produced medians of
  1.999/3.999/5.998 mm; add-on QA sampled minima were 1.586/3.468/5.222 mm. The 2 mm
  shell correctly fails a 3 mm minimum.
- The 6 mm shell repairs 25 outer-wall crossings to zero in seven local passes, with a
  maximum repaired-direction change of 18.287 degrees. A 12 mm infeasible request
  cancels cleanly and retains the valid 6 mm brace/base.
- Editing a source body vertex after generation is detected before QA/export and marks
  the brace out of date.
- Installed-copy `designviewtest`, `outlinetest`, `importtest`, `trimlinetest`,
  `referencetrimtest`, `trimtest`, `qatest`, `exporttest`, and `embosstest` all report
  `PASS=True`. This covers failed-generation transaction restoration, legacy-outline
  compatibility, new-patient isolation, unified/reference trim, finishing, QA, isolated
  export, and emboss geometry. The QA thin-wall fixture sampled full coverage and recorded
  “Minimum sampled wall is 2.00 mm; required is 3.00 mm”; export confirms QA reran
  immediately before writing the isolated brace.

## Known blocker

Do not fabricate/export the automatic B fixture. Its requested 4 mm wall still overlaps
beyond the allowed 25-degree local repair, so generation cancels before a canonical
brace is created. `btrimlinetest` reports `SAFETY_PASS=True`, but
`READINESS_PASS=False` and `PASS=False`. The B surface/trim prescription needs separate
repair and orthotist review.

Automated PASS means the software geometry contract passed. It does not certify fit,
biomechanical correction, clinical safety, or fabrication approval.
