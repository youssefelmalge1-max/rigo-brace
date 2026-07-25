# User Check - Surface-Fitted Trimline and Brace Generator

Readiness: **READY FOR ORTHOTIST VISUAL CHECK ON A/REFERENCE; NOT CLINICALLY APPROVED**

Restart Blender from the updated **Rigo Brace** desktop shortcut.

## Exact path

1. Import the patient STL/OBJ, apply the correct units, orient/clean it, and place accurate
   pelvic, waist, axilla, and shoulder landmarks. Importing another patient removes the
   previous patient's trim curves; create and review new Auto Trim Lines rather than
   reusing an old contour.
2. Complete and commit the intended pressure, expansion, and segment corrections.
3. In **Design > Auto Trim Lines (Rigo)** choose **Rigo-Cheneau Reference**, set
   **Opening Width (mm)**, and click **Auto Trim Lines**.
4. Click **Edit on Body**. Left-drag a visible point; hidden back-side points cannot be
   picked through the body. `Ctrl+Z` restores the last moved point, `Esc` restores every
   point to its pre-edit location, and `Enter` accepts the edit. Use **Fit** to repair an
   older/floating point.
5. Inspect the one orange perimeter from front, back, left, and right. It must remain on
   the body curvature with no gap, branch, spike, or uncontrolled lateral prong.
6. Click **Generate Brace**. The view changes to **Brace Preview** and hides the body and
   perimeter. Use **Edit Trimlines** to return to body+line view.
7. If thickness, offset, fairing, or trim geometry changes, confirm the panel says
   **BRACE OUT OF DATE**, then click **Update Brace**. Do not judge the old visible shell
   by the new field value.
8. Inspect the clean Brace Preview, set the clinic/material minimum wall, and click
   **Verify Manufacturing QA**. Export reruns the same gate.

## Installed-copy gates

- Reference curve raw and evaluated p95/max distance: 1.500 mm from the corrected body.
- Requested opening: 25 mm in the regression case.
- The registered trim modal passed real queued orthographic viewport events: an
  overlapping hidden back control was not selected, the visible control was dragged,
  remained 1.499955 mm from the body, and `Esc` restored the pre-edit contour.
  Orthographic view-ray origins are now clamped to a scan/view-derived distance for
  precision, followed by an unbounded BVH ray; this replaces the former fixed
  1000-Blender-unit cap without leaving the origin at the 100 km far clip.
- Reference shell: closed/manifold, one component, zero intersections, 3.582 mm sampled
  minimum wall, 2,294 rounded rim edges.
- A shell: closed/manifold, one component, zero intersections, 3.360 mm sampled minimum
  wall at a 3.0 mm threshold.
- Thickness sweep: exact paired spacing of 2.000/4.000/6.000 mm and independent
  bidirectional-ray medians of 1.999/3.999/5.998 mm. The add-on QA sampled minima are
  1.740/3.654/5.386 mm; 2 mm is therefore blocked by the 3 mm QA threshold.
- The 6 mm sweep repairs 25 local outer-wall crossings to zero in seven passes, with a
  maximum 18.287-degree direction change. An infeasible 12 mm test cancels and retains
  the last valid 6 mm brace/base rather than replacing it.
- Installed-copy `designviewtest`, `outlinetest`, `importtest`, `trimlinetest`,
  `referencetrimtest`, `trimtest`, `qatest`, `exporttest`, and `embosstest` all report
  `PASS=True`. This covers failed-generation transaction restoration, legacy-outline
  compatibility, new-patient isolation, unified/reference trim, finishing, QA, isolated
  export, and emboss geometry. The thin-wall QA fixture samples full coverage and records
  the 2.00 mm measured/3.00 mm required failure; export confirms QA reran before writing.

## Clinical checks that automation cannot approve

- Confirm laterality of the tall axillary wing.
- Confirm axilla, chest, pelvis, iliac crest, and trochanter coverage/clearance.
- Confirm pressure/expansion pairs and sagittal intent were preserved.
- Confirm opening location and width suit the prescription and donning plan.
- Complete fitting and clinical/radiographic validation before fabrication.

The B fixture remains blocked. Its requested 4 mm wall cannot be repaired within the
25-degree outer-wall guard, so Generate cancels before creating an invalid brace.
`SAFETY_PASS=True` records this containment; `READINESS_PASS=False` and `PASS=False`
record that B is not ready.
