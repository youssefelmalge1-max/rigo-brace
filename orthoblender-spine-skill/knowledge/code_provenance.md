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

## PROV-0015 — 2026-09-05 — Shell performance diagnosis
Source project: user-owned Rigo Brace Designer repository and local Windows resource counters.
Path/source files: curve_build_ops.py, design_ops.py, trimverify_ops.py, gentimedbg_result.txt, finishtimedbg_result.txt; details in shell_performance_audit_2026_09_05.md.
License/copyright: existing project terms; no external code or assets acquired.
Permission basis: user-requested local performance investigation.
Copied|modified|rewritten|learned-from-only: learned-from-only; original diagnostic documentation.
Target file: knowledge/shell_performance_audit_2026_09_05.md and session ledgers.
Reason: distinguish implementation costs from machine/session confounders.
Changes: documentation only. Compatibility risk: none. Clinical risk: none introduced.
Test added: none; reviewed saved timing artifacts and compared installed/source hashes; live read-only resource probes.
Notes: no external source reuse, new production code, or fresh Blender benchmark claimed.

### PROV-0015 follow-up — 2026-09-06
Original diagnostic harness tools/genbench.py uses the existing user-owned tools/bracefixture.py and repository GUI timer/result-file convention; existing project license/permission basis applies. No external source or assets copied. Records unprofiled elapsed times and build metadata in separate fresh processes. Verified by three successful runs against the unchanged installed add-on; separate existing gentimedbg.py profile also completed. No production geometry or clinical behavior changed.

## PROV-0016 — 2026-09-06 — tools/subdivshot.py subdivision before/after probe
Source project: user-owned Rigo Brace Designer repository.
Path/source files: tools/subdivshot.py (new, diagnostic only), built from the existing tools/smoothdbg.py chain and tools/rimshot.py camera/shading helpers.
License/copyright: existing project terms; no external code or assets.
Permission basis: user-requested test with pictures.
Copied|modified|rewritten|learned-from-only: modified from in-repo probes.
Target file: tools/subdivshot.py; outputs subdivshot_L*.png/.txt and subdivshot_compare.png in the project root.
Reason: measure and show whether pre-subdividing the scan smooths a committed library pressure.
Changes: none to the add-on. Compatibility risk: none. Clinical risk: none.
Test added: the probe itself (RIGO_SUBDIV=0|1, RIGO_SUBDIV_MODE=editsub|subsurf), one Blender process per arm.

## PROV-0017 — 2026-09-08 — #53 region commit speed-up and Subdivide Scan
Source project: user-owned Rigo Brace Designer repository.
Path/source files: rigo_brace/operators/region_ops.py (_fan_collapse, _ekey/_fkey, worklist purge, numpy helpers), rigo_brace/operators/mesh_ops.py (RIGO_OT_subdivide_scan), rigo_brace/ui/panels.py (button), tools/selftest.py (registration check), tools/collapseequivdbg.py, tools/collapsereplaydbg.py, tools/refinetracedbg.py, tools/vecequivdbg.py, tools/subdivshot.py (all diagnostic).
License/copyright: existing project terms; numpy is bundled with Blender; no external code copied.
Permission basis: user request ("make the load be on numpy / compiled code").
Copied|modified|rewritten|learned-from-only: modified in place; old bodies kept verbatim inside the probes for differential proof.
Reason: 61% of commit time was one mesh-wide bmesh op called per collapse; the rest whole-mesh Python loops.
Changes: see DEC-0062. Compatibility risk: purge order semantics (documented). Clinical risk: none.
Test added: the four probes above; selftest op_subdivide_scan.

## PROV-0018 — 2026-09-08 — #54 Task 1: stored outline distance + live feather/falloff
Source project: user-owned Rigo Brace Designer repository.
Path/source files: rigo_brace/core/__init__.py (feather_mm, update callbacks), rigo_brace/operators/region_ops.py (_store/_load/_drop_distance, _falloff_np, _weights_from_distance, _refresh_snapshot_weights, reevaluate_region, sync_preview; Add/circle/Update/Apply/Remove wiring), rigo_brace/ui/panels.py (active-region Feather/Falloff rows), tools/feathertest.py (new test), knowledge/transition_authoring_plan.md (task specs), knowledge/correction_region_model.md (data-model table).
License/copyright: existing project terms; numpy is bundled with Blender; no external code copied.
Permission basis: orthotist approval of the DEC-0064 plan, 2026-09-08.
Copied|modified|rewritten|learned-from-only: modified in place.
Reason: the transition profile was baked into vertex-group weights at Add time; only Amount was live (DEC-0064, proposition E).
Changes: see DEC-0065. Compatibility risk: saved .blends without the attribute behave as before (feather via Edit Selection -> Update). Clinical risk: none — weights are bit-for-bit the same formula.
Test added: tools/feathertest.py (11 gates); regression battery recorded in DEC-0065.

## PROV-0019 — 2026-09-08 — #54 Task 2: ROUNDED profile (fillet ramp)
Source project: user-owned Rigo Brace Designer repository.
Path/source files: rigo_brace/core/__init__.py (REGION_FALLOFF_ITEMS, top/bottom radius, depth_mm, scene defaults), rigo_brace/operators/region_ops.py (_rounded_profile, _region_profile, profile_readout, _weights_from_distance profile argument, _authored_rim_field region argument, style/mirror wiring), rigo_brace/ui/panels.py (radius sliders + readout), tools/profiletest.py (new), tools/targetsurfdbg.py (round_<top>_<bottom> arm).
License/copyright: existing project terms; the fillet-ramp construction is elementary geometry written here; no external code.
Permission basis: orthotist approval of the DEC-0064 plan, 2026-09-08.
Copied|modified|rewritten|learned-from-only: new code + modified in place.
Reason: DEC-0064 — the authored profile's corner sharpness was not controllable.
Changes: see DEC-0066. Compatibility risk: none for classic kinds (regression identical); library entries gain three optional fields. Clinical risk: none — geometry only, labelled in mm, review flag untouched.
Test added: tools/profiletest.py (7 gates).

## PROV-0020 — 2026-09-08 — #54 Task 3: corner-aware sampling, deterministic n-gon split, corner readout and commit note
Source project: user-owned Rigo Brace Designer repository.
Path/source files: rigo_brace/operators/region_ops.py (_CORNER_TURN / _CORNER_EDGE_FLOOR_M / _CORNER_SKIP_TURN, _corner_edge_floor, _drawable_corner_mm, transition_readout, field.distance / corner_radius / min_corner_radius on _authored_rim_field, corner_requirement in _refine_footprint, _split_refined_ngons, commit note in region_apply, edge_mm at Add/circle/Update), rigo_brace/core/__init__.py (edge_mm, commit_note), rigo_brace/ui/panels.py (readout for every kind, commit note), tools/cornertest.py (new test), tools/cornerdbg.py + tools/cornerdbg2.py (probes), tools/targetsurfdbg.py (round_ arm).
License/copyright: existing project terms; the 1→2/1→3/1→4 split patterns are textbook; no external code.
Permission basis: orthotist approval of the DEC-0064 plan, 2026-09-08.
Copied|modified|rewritten|learned-from-only: new code + modified in place.
Reason: DEC-0064 — the slope-only refinement criterion is blind to corner turning.
Changes: see DEC-0067 / ERR-0038. Compatibility risk: refinement topology changes for every refined commit (deterministic split instead of beauty); golden route measured in DEC-0067. Clinical risk: none — geometry only; the note never blocks a commit.
Test added: tools/cornertest.py (8 gates).

## PROV-0021 — 2026-09-08 — #54 Task 6: hinge guard
Source project: user-owned Rigo Brace Designer repository.
Path/source files: rigo_brace/operators/region_ops.py (_HINGE_DEG / _HINGE_PRE_DEG / _HINGE_MIN_HEIGHT_M, _folded_pairs hinge branch, _face_height), orthoblender-spine-skill/knowledge/region_quality_contract.md (fold.hinge_deg / hinge_pre_deg + prose), tools/regionqualtest.py (contract_constants gate), tools/hingetest.py (new test), tools/cornerdbg.py / cornerdbg2.py / ngondbg.py (probes, diagnostic only).
License/copyright: existing project terms; no external code.
Permission basis: orthotist approval of the DEC-0064 plan, 2026-09-08 (Task 6).
Copied|modified|rewritten|learned-from-only: modified in place.
Reason: validators accepted 123° and 150.9° fold-backs (DEC-0064 / DEC-0067).
Changes: see DEC-0069. Compatibility risk: commits that previously shipped a hinge now repair or refuse it; classic routes unchanged (golden identical). Clinical risk: none — the guard only refuses geometry that folds back on itself.
Test added: tools/hingetest.py (2 gates); hingetest joins the battery.

## PROV-0022 — 2026-09-08 — tools/featherdbg.py (probe only; no add-on code changed for DEC-0070)
Source project: user-owned Rigo Brace Designer repository. New file tools/featherdbg.py: inward-feather plateau share, A·w realized depth, outward-band recruit count, preview/commit dihedrals binned by rim/wall/core. License: project terms, no external code. Permission basis: the orthotist's request 2026-09-08 to debate the feather semantics with Codex. Copied|modified|rewritten|learned-from-only: new, patterned on tools/hingetest.py. Compatibility risk: none (probe). Codex's caveat recorded: arms move the patch between feathers and keep earlier commits; "realized depth" is A·median(w), not measured displacement.

## PROV-0023 — 2026-09-09 — #54 Task 7: outward feather (production code + tests)
Source project: user-owned Rigo Brace Designer repository. Files: rigo_brace/core/__init__.py (feather_outside, region-index update callback), rigo_brace/operators/region_ops.py (contact/signed-distance storage, _band_weights/_band_members/_stored_band_mm, _outward_distance, _mesh_neighbours, _outward_fields_from_contact, _adopt_outward, _reevaluate_outward, _mark_refined_nonmember, _outward_rim_field, sync_outline/_outline_geometry/_boundary_edge_pairs/_region_member_flags, operator edits in region_add/edit/update/apply/style_save/style_import/mirror/remove), rigo_brace/ui/panels.py (label). Tests: tools/featherlifecycletest.py (file content authored by Codex gpt-6-astra round A from Claude's interface contract; harness fixes, overlap semantics and 10 mm overlap fixture by Claude), tools/makelegacyfixture.py (bakes the gitignored legacy_inward_region.blend with the pre-Task-7 add-on), tools/task7_uishot.py (UI screenshots), tools/hingedbg.py (ladder trace), tools/featherdbg.py (DEC-0070 measurements); tools/feathertest.py, profiletest.py, cornertest.py gates updated to the outward contract (DEC-0071). License/copyright: project terms; no external code. Permission basis: the orthotist's written instruction 2026-09-09 ("Proceed with Task 7 ... delegate it to codex Astra") and his test of the installed build. Copied|modified|rewritten|learned-from-only: modified in place; new helpers. Compatibility risk: newly painted regions change semantics (pad = paint, feather outside); stored regions, circle regions, styles saved before Task 7 and the golden route are unchanged by construction and by test. Clinical risk: the band moves surface OUTSIDE the paint — that is the orthotist's stated intent and it is drawn as the outer outline.
