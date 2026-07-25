# Code Provenance Register

All code in this repository is the **user's own work** unless an entry below says
otherwise. The add-on declares `SPDX:GPL-3.0-or-later`
(`rigo_brace/blender_manifest.toml`). No third-party add-on source has been copied.

---
## Provenance ID: PROV-0001
Date: 2026-06-13
Source project: rigo_brace (this repository)
Source path or URL: c:\Projects\Blender Add-on Braces\rigo_brace
Source file: all `rigo_brace/**`, `rigo_brace_template/**`, `tools/**`, `build.py`, `install.ps1`
Original license: SPDX:GPL-3.0-or-later (per manifest)
Copyright holder: Project owner (the user / orthotics professional)
Permission basis: User owns the project and authorizes modification
Copied / modified / rewritten / learned from: owned — full modify rights
Target file: same
Reason for reuse: ongoing development
Changes made: see git-less change history in this session (audit, pad library, deform fixes)
Compatibility risk: none (single GPL project)
Clinical risk: see clinical_safety notes per feature
Test added: see tools/*test.py
Notes: GPL headers/notices to be preserved on any future redistribution.

---
## Provenance ID: PROV-0013
Date: 2026-07-13
Source project: Video Content Factory / SpinalTech public 3D viewer assets
Source path or URL: `C:\Projects\Video Content Factory\assets\references\3d`; <https://spinaltech.com/design-your-orthosis>
Source file: `spinaltech_base1.glb` through `spinaltech_base4.glb` and matching angle sheets
Original license: not stated; third-party SpinalTech geometry
Copyright holder: SpinalTech
Permission basis: user explicitly requested an internal project copy; no redistribution permission inferred
Copied / modified / rewritten / learned from: copied as internal regression references; production generator remains independently implemented
Target file: `reference_assets/spinaltech_trimlines/*`
Reason for reuse: measure and visually compare brace-type-specific trimlines, opening, surface following, and shell quality
Changes made: none to the copied binary/image assets; added an internal-use README
Compatibility risk: high if bundled or redistributed; exclude from distributable add-on ZIP
Clinical risk: reference geometry is not a patient prescription and cannot be applied blindly
Test added: `tools/referenceaudit.py`, `tools/referenceprofile.py`, `tools/referencetrimtest.py`, four-view render
Notes: never copy reference vertices/faces into generated patient output; use measurements and independent algorithms only.

---
## Provenance ID: PROV-0002
Date: 2026-06-13
Source project: LeoSpinal (commercial orthotics software)
Source path or URL: Leospinal tutorial.md (transcript text only)
Source file: n/a (no source code)
Original license: proprietary
Copyright holder: LeoSpinal
Permission basis: none — **feature-level analysis only**
Copied / modified / rewritten / learned from: **learned-from-only** (workflow/UX concepts)
Target file: design_ops.py, deform_ops.py, pad_ops.py (independent reimplementations)
Reason for reuse: replicate the clinical workflow the user is familiar with
Changes made: clean-room reimplementation using Blender APIs; no LeoSpinal code exists or was seen
Compatibility risk: none (no code copied)
Clinical risk: workflow parity does not imply clinical equivalence — orthotist review required
Test added: outlinetest, planestest, padtest, padshapetest
Notes: Only the public tutorial transcript was read. UI terms ("From/To planes",
"pressure/relief") are descriptive, not copied assets.

---
## Provenance ID: PROV-0003
Date: 2026-06-13
Source project: Blender (Foundation) manual + Simple Deform modifier behavior
Source path or URL: docs.blender.org; MOD_simpledeform.cc (knowledge, not vendored)
Source file: n/a
Original license: GPL (Blender) / CC (manual)
Copyright holder: Blender Foundation
Permission basis: GPL-compatible; behavior verified empirically (tools/bendexp.py, stretchexp.py)
Copied / modified / rewritten / learned from: learned-from-only (axis semantics)
Target file: deform_ops.py
Reason for reuse: correct BEND axis (around Y for coronal) and STRETCH locks
Changes made: none copied — config derived from empirical headless experiments
Compatibility risk: none
Clinical risk: none
Test added: bendtest.py, stretchtest.py
Notes: Rodin4D research (shapemakers.nl page) yielded marketing only; no usable detail.

---
## Provenance ID: PROV-0004
Date: 2026-06-13
Source project: uFit Blender Add-on
Source path or URL: D:\ufit-blender-master\ufit-blender-master ; github.com/ortigital/ufit-blender
Source file: whole project (audited); key: base/src/operators/core/sculpt.py, utils/color_attributes.py, OT_circumference_length.py
Original license: GPL-3.0 (full GPLv3 text + README)
Copyright holder: Ugani Prosthetics
Permission basis: GPL-3.0 open-source; compatible with rigo_brace GPL-3.0-or-later
Copied / modified / rewritten / learned from: **learned-from-only so far** (audit). Any future port (e.g. push_pull_region_circular) → modified-with-attribution, log a new entry.
Target file: (future) rigo_brace area-carve / measurements / thickness modules
Reason for reuse: proven region-paint→deform, live circumference, variable thickness
Changes made: none yet (audit only)
Compatibility risk: low (same license family); Blender 3.5 API mostly compatible with 5.0
Clinical risk: prosthetics origin — adapt to spinal; orthotist review
Test added: n/a (no code ported yet)
Notes: DO NOT port cloud auth/platform/ini/reload-patch. Preserve GPL headers on any ported unit. See knowledge/ufit_feature_audit.md.

---
## Provenance ID: PROV-0005
Date: 2026-06-13
Source project: WASP-Med (Waspmed)
Source path or URL: D:\WASP-Med-master\WASP-Med-master ; github.com/wasproject/Blender-WASP-Med
Source file: whole project (audited); key: waspmed_deform.py (rotate_sections), waspmed_generate.py (weight_thickness), waspmed_scan.py (check_differences, measure_circumference)
Original license: GPL v2-or-later (header block; no separate LICENSE file)
Copyright holder: WASP (wasproject.it)
Permission basis: GPL-2-or-later; combinable with GPL-3 → result GPL-3
Copied / modified / rewritten / learned from: **learned-from-only so far** (audit). Future ports → modified-with-attribution, new entry each.
Target file: (future) rigo_brace derotation / variable-thickness / QA-deviation modules
Reason for reuse: multi-section derotation, gradient thickness, before/after deviation map
Changes made: none yet (audit only)
Compatibility risk: medium — Blender 2.91 API; transform/lattice/override calls need updating for 5.0
Clinical risk: low (orthopedic origin); orthotist review for correction logic
Test added: n/a (no code ported yet)
Notes: Preserve WASP GPL header on any ported unit. See knowledge/wasp_feature_audit.md.

---
## Provenance ID: PROV-0006
Date: 2026-06-17
Source project: WASP-Med (Waspmed)
Source path or URL: D:\WASP-Med-master\WASP-Med-master\waspmed_scan.py
Source file: OBJECT_OT_wm_next / OBJECT_OT_wm_back + status/patientID property model
Original license: GPL v2-or-later
Copyright holder: WASP (wasproject.it)
Permission basis: GPL-2-or-later, combinable into GPL-3 (rigo_brace)
Copied / modified / rewritten / learned from: **rewritten with attribution** — the
design-history versioning approach (numbered NN_<patient>_<stage> snapshots in a
per-patient collection; Next freezes the old version and edits a duplicate; Back/Rollback
reveal saved versions) was reimplemented clean for Blender 5.0 and brace stages, not
copied verbatim.
Target file: rigo_brace/operators/history_ops.py (Patch 2)
Reason for reuse: the design history the user explicitly preferred over uFit's storage
Changes made: modern API (object/data copy, collection link/unlink, hide_set, view_layer
active); BRACE_STAGES instead of WASP status_list; rollback-by-stage; forward-history
rebuild on re-Next; no per-step mode switches (deferred)
Compatibility risk: low (clean 5.0 reimplementation)
Clinical risk: none (non-destructive history)
Test added: tools/historytest.py (PASS)
Notes: history_ops.py docstring credits WASP + cites PROV-0005. GPL attribution preserved.

---
## Provenance ID: PROV-0007
Date: 2026-06-17
Source project: WASP-Med (auto_origin / check_differences) + uFit (Verify Clean Up step)
Source path or URL: D:\WASP-Med-master\...\waspmed_scan.py; uFit clean-up step
Source file: concept only (centering + pre-commit verification)
Original license: GPL-2+ (WASP) / GPL-3.0 (uFit) — both GPL-compatible
Copyright holder: WASP / Ugani Prosthetics
Permission basis: GPL-compatible
Copied / modified / rewritten / learned from: **learned-from-only** — clean reimplementation.
center_model uses Blender's origin_set; verify_clean uses standard bmesh manifold/boundary
counts + select_non_manifold. No source code copied.
Target file: rigo_brace/operators/clean_ops.py (Patch 3)
Reason for reuse: the Clean-stage centering + the "verify before closing the mesh" gate
Changes made: original implementation; counts stashed as custom props for the panel/tests
Compatibility risk: none
Clinical risk: none (verify is read-only + selection highlight)
Test added: tools/cleantest.py (PASS)
Notes: clean_ops.py docstring credits the WASP/uFit concepts + cites this entry.

---
## Provenance ID: PROV-0008
Date: 2026-07-06
Source project: WASP-Med (Waspmed)
Source path or URL: D:\WASP-Med-master\WASP-Med-master\waspmed_deform.py
Source file: OBJECT_OT_wm_add_lattice_to_object / wm_edit_lattice / wm_rotate_sections
Original license: GPL v2-or-later
Copyright holder: WASP (wasproject.it)
Permission basis: GPL-2-or-later, combinable into GPL-3 (rigo_brace)
Copied / modified / rewritten / learned from: **rewritten with attribution** — the
lattice-cage + per-section rotation approach was reimplemented clean for Blender 5.0
with two deliberate corrections: (1) WASP rotated via transform.rotate with no axis
(view-axis dependent) -> we rotate around global Z through the cage centre in code;
(2) scale-compensated rotation (uncompress -> rotate -> recompress) so a non-uniformly
scaled cage cannot shear the torso; plus auto-fit to the scan bbox (WASP used manual
dimensions), LINEAR interpolation (B-spline smears the dial gradient), and a gradient
seed dial on top of WASP's per-section dials.
Target file: rigo_brace/operators/lattice_ops.py (Patch 5)
Reason for reuse: the multi-section derotation the user asked to port "exactly as is"
Changes made: see above; no WASP code copied verbatim; module docstring credits WASP.
Compatibility risk: low (clean 5.0 implementation).
Clinical risk: derotation magnitude is orthotist-entered; undoable; discard restores.
Test added: tools/latticetest.py (PASS — gradient 0.8/14.1/29.2° vs dials 0/15/30,
radial drift 0.13 mm, apply bakes, discard restores exactly).
Notes: GPL header preserved in spirit via docstring attribution + this entry.

---
## Provenance ID: PROV-0009
Date: 2026-07-06
Source project: WASP-Med (Waspmed)
Source path or URL: D:\WASP-Med-master\WASP-Med-master\waspmed_scan.py
Source file: xray_shading() + update_smooth() (CorrectiveSmooth on a vertex group)
Original license: GPL v2-or-later
Copyright holder: WASP (wasproject.it)
Permission basis: GPL-compatible
Copied / modified / rewritten / learned from: **learned-from-only** — concepts (viewport
show_xray while checking trims; CorrectiveSmooth restricted to a vertex group with
use_only_smooth). Clean original implementation adapted to the corset: WASP inverted a
"keep" group and pinned boundaries; we bake a feathered TRIM BAND at Generate time
(while the cut is still an open boundary, before Solidify closes the rim) and smooth
that band unpinned. Flare (safe edge) is our own addition (uFit trim-flare concept).
Target file: rigo_brace/operators/trim_ops.py + design_ops.py band-bake hook (Patch 6)
Reason for reuse: the trim-stage X-ray view + one-button edge smoothing the plan calls for
Changes made: original implementation; no code copied.
Compatibility risk: none. Clinical risk: edge finishing only; undoable.
Test added: tools/trimtest.py (PASS).
Notes: trim_ops.py docstring credits the WASP concepts + cites this entry.

---
## Provenance ID: PROV-0010
Date: 2026-07-08
Source project: the user's own clinical reference braces
Source path or URL: "A type model/Brace.stl", "B type model/Brace.stl" (project root)
Original license: user-owned clinical data (their design work)
Copyright holder: the user / their clinic
Permission basis: owner provided the files expressly for template extraction
Copied / modified / rewritten / learned from: DERIVED DATA — coverage-boundary trim
templates (rigo_brace/templates/trimline_A.json / trimline_B.json) extracted by ray
coverage (80 mm along vertex normals), 72 theta-bins, 98/2-percentile profiles, circular
smoothing, normalized to bottom/waist/top anchors. No third-party code or geometry.
Target file: rigo_brace/templates/*.json, core/trim_templates.py, operators/trimline_ops.py
Reason for reuse: auto-generate starting trim lines per Rigo type (user request)
Changes made: n/a (original implementation)
Compatibility risk: none. Clinical risk: templates carry requires_orthotist_review;
lines are a STARTING POINT the orthotist refines; subtype calibration pending the
user's Rigo classification graphics.
Test added: tools/trimlinetest.py (PASS).
Notes: patient/clinic geometry stays local; nothing uploaded.

---
## Provenance ID: PROV-0011
Date: 2026-07-12
Source project: LeoSpinal tutorial and Rodin4D/LeoShape public product material
Source path or URL: project `Leospinal tutorial.md`;
https://www.rodin4d.com/app/uploads/2023/08/Rodin-DOC-EN.pdf;
https://leopoly.com/leoshape/2026/05/20/leospinal-release-notes-20-05-26/
Source file: feature descriptions only; no source code accessed
License: proprietary vendor material/public documentation; local transcript supplied by
the user for feature analysis
Copyright holder: respective vendors
Permission basis: analysis and interoperability research; no code or assets copied
Copied / modified / rewritten / learned from: **learned-from-only** — three-loop
segment-limited deformation and reusable JSON template behavior.
Target file: original implementation in core/region_library.py, operators/region_ops.py,
operators/deform_ops.py and ui/panels.py
Reason for reuse: reproduce user-requested workflow behavior in Blender.
Changes: three active-pair rings implemented with Blender drivers/Simple Deform; weighted
selection styles implemented as original surface-local sample transfer.
Compatibility risk: none from source reuse. Clinical risk: orthotist review required.
Tests added: regionstyletest.py and segmentdeformtest.py.
Notes: public Rodin4D material does not reveal exact algorithms; no parity claim made.

---
## Provenance ID: PROV-0012
Date: 2026-07-12
Source project: LeoShape/LeoSpinal public product page; Rodin4D public brochure; Rigo et
al. 2010 open-access classification; 2016 SOSORT guidelines; Guy et al. 2024 automated
brace study; Storm et al. 2022 additive-manufacturing study.
Source path or URL: links recorded in `knowledge/brace_generator_research.md`.
Source file: public product descriptions and published articles only.
License: mixed proprietary documentation and open-access scholarly publications.
Copyright holder: respective vendors/authors/publishers.
Permission basis: interoperability/research analysis and factual workflow learning.
Copied / modified / rewritten / learned from: **learned-from-only**; no source code,
vendor assets, meshes or text copied into production.
Target file: research/specification and decision map only; no production implementation.
Reason for reuse: define clinical inputs, geometry architecture and QA gates before the
brace generator is replaced.
Changes: none to production in this research ticket.
Compatibility risk: none. Clinical risk: mitigated by mandatory orthotist prescription
and review; published study parameters are explicitly not defaults.
Test added: `tools/generatoraudit.py` baseline on user-owned A model/reference pair.
Notes: exact LeoSpinal/Rodin4D algorithm parity is neither known nor claimed.

---
## Provenance ID: PROV-0014
Date: 2026-07-18
Source project: uFit Blender Add-on 2.2.2
Source path or URL: `D:\ufit-blender-master\ufit-blender-master`
Source file: vertex-color selection and annotation-to-curve workflow
Original license: GPL-3.0
Copyright holder: Ugani Prosthetics / uFit contributors
Permission basis: GPL-compatible with this GPL-3.0-or-later add-on
Copied / modified / rewritten / learned from: **learned-from-only** — green/white
POINT color masking and the high-level concept of converting an annotated region into
an ordered smooth boundary. No uFit production code was copied.
Target file: `rigo_brace/operators/custom_trim_ops.py`
Reason for reuse: provide a custom painted brace region when a clinical trim template
is not appropriate.
Changes: original marching-triangle contour extraction, branch/self-touch validation,
surface-constrained fairing, bounded Bezier fitting, and transactional shell reuse.
Compatibility risk: low. Clinical risk: painted coverage remains an orthotist decision;
generation rejects disconnected, undersized, insufficient-wrap, or unsafe geometry.
Test added: `tools/customtrimtest.py` (paint colors/API, black-stroke recovery,
surface fit, no UV crossings, mask agreement, manifold shell generation).
Notes: the paint mask is design input, not an automated clinical prescription.
