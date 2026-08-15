# Decision Log

## Decision ID: DEC-0001
Date: 2026-06-13
Decision: Adopt the OrthoBlender Spine Skill operating discipline; keep an in-repo `knowledge/` base + `SKILL.md`, read/update each session.
Reason: User (project owner) mandated a file-based memory + audit-first workflow.
Alternatives: rely on harness memory only; ad-hoc development.
Why rejected: project needs durable, reviewable clinical/engineering provenance.
Clinical risk: none directly; improves traceability for a medical device.
Technical risk: doc drift if not maintained — mitigated by session loop rule.
Rollback plan: delete `knowledge/` + `SKILL.md`.
Files affected: SKILL.md, knowledge/*.
Tests required: none (docs).

## Decision ID: DEC-0002
Date: 2026-06-13
Decision: Pads are editable draped Bezier outlines with a per-PC JSON library (replaces circular point pads).
Reason: Matches LeoSpinal workflow; user-confirmed "replace entirely / global library".
Alternatives: keep circular pads; store library per .blend.
Why rejected: circular pads can't be fitted; per-.blend loses reuse across patients.
Clinical risk: shape fidelity (AUTO handles only on respawn) — acceptable for v1.
Technical risk: dynamic-enum lifetime, file IO — mitigated (LM-0007, atomic save).
Rollback plan: revert pad_ops.py/pad_library.py/core props/panel.
Files affected: rigo_brace/operators/pad_ops.py, rigo_brace/core/pad_library.py, core/__init__.py, ui/panels.py.
Tests required: padtest.py, padshapetest.py — passing.

## Decision ID: DEC-0003
Date: 2026-06-13
Decision: Simple Deform axes — BEND=Y, TWIST=Z, STRETCH=Z with lock_x/lock_y.
Reason: Empirical + source-confirmed correct planes for an upright torso.
Alternatives: axis Z bend (original) / rotated empty.
Why rejected: produced torso roll-up / unnecessary folklore.
Clinical risk: correction direction — orthotist validates via slider.
Technical risk: low.
Rollback plan: revert deform_ops.py axis lines.
Files affected: rigo_brace/operators/deform_ops.py.
Tests required: bendtest.py, stretchtest.py — passing.

## Decision ID: DEC-0004
Date: 2026-06-13
Decision: Deform range = two draggable semi-transparent discs + red axis, driving modifier limits/origin via drivers.
Reason: LeoSpinal-style direct manipulation; numeric fields insufficient.
Alternatives: numeric From/To only; thin ring curves.
Why rejected: not the clinical feel; rings unclickable.
Clinical risk: none.
Technical risk: driver "Invalid" warnings on apply — mitigated by freezing values pre-apply.
Rollback plan: revert deform_ops.py plane code + core range props.
Files affected: rigo_brace/operators/deform_ops.py, core/__init__.py, ui/panels.py.
Tests required: planestest.py — passing.

## Decision ID: DEC-0005
Date: 2026-06-13
Decision: Treat LeoSpinal/Rodin as learn-from-only (workflow), never copy code/assets.
Reason: proprietary; only public transcript/marketing seen.
Alternatives: n/a.
Why rejected: license.
Clinical risk: workflow parity ≠ clinical equivalence (orthotist review).
Technical risk: none.
Rollback plan: n/a.
Files affected: knowledge/code_provenance.md (PROV-0002/0003).
Tests required: none.

## Decision ID: DEC-0006
Date: 2026-06-13
Decision: Audit-only this session; no add-on source modified. Only `knowledge/` + `SKILL.md` created.
Reason: explicit user instruction ("ابدأ Audit فقط، لا تعدّل أي كود الآن").
Alternatives: start coding the area-select feature now.
Why rejected: user wants the audit + knowledge base + roadmap first, then a proposed small patch.
Clinical risk: none.
Technical risk: none.
Rollback plan: delete the new docs.
Files affected: SKILL.md, knowledge/*.
Tests required: none.

## Decision ID: DEC-0007 (PROPOSED — awaiting approval)
Date: 2026-06-13
Decision: First safe patch = "Area-Select → Editable Contour Lines → Carve/Add" tool.
Reason: top user-value gap (P0); current request.
Approach (small, reuses existing code):
  1. Use existing Edit-mode paint-select as the region input (already mesh-based).
  2. From the selected faces, generate N editable cross-section contour lines (curves
     with movable control points), spaced along the region's dominant axis.
  3. Drag control points (reuse deform_ops driver/handle pattern) to set local
     add/carve offset per line.
  4. Apply: displace selected vertices along normals interpolated between the contour
     lines, with smoothstep feather (reuse pad_ops feather/inside logic).
Alternatives: pure sculpt brush (rejected — user wants selection-based);
  single-outline pad (already exists, not "lines along the region").
Clinical risk: over-deformation — clamp offsets, orthotist review, undoable.
Technical risk: contour generation on noisy scans — start with planar slices, test.
Rollback plan: new module `operators/area_ops.py` + panel box; deletable in isolation.
Files affected (when approved): NEW operators/area_ops.py, core props, ui/panels.py,
  selftest.py, NEW tools/areatest.py.
Tests required: areatest.py (select→lines exist→drag→apply moves only selected,
  feathered; far mesh untouched).

## Decision ID: DEC-0008
Date: 2026-06-13
Decision: Adopt uFit's workflow UX as the target for the brace add-on, adapted to
spine — recorded as Requirements v1 (10 items) in knowledge/requirements_v1.md.
Reason: User walked through uFit 2.2.2 and specified exactly which features to take
(import, quad/ortho/fullscreen view, clean tab, checkpoints/assistance/progress/
annotation shell, verify-clean gate, quad-view alignment, spine-level circumferences,
measurable highlight push/pull sculpt, manual trim lines + X-ray + flared width,
part-selection → scale → unified thickness → flare %).
Alternatives: keep current 5-stage wizard as-is; cherry-pick only a few features.
Why rejected: user wants the proven uFit clinical flow; both source apps are
GPL-compatible so reuse is permitted.
Clinical risk: workflow parity ≠ clinical validity — orthotist review per template.
Technical risk: large UI restructure (the shell) — phase it; reuse existing operators.
Rollback plan: requirements are docs only; no code changed yet.
Files affected (future): ui/panels.py shell, new view/checkpoint/assistance/progress
operators, measurements + sculpt + trimline-flare + part-selection modules.
Tests required (future): per-module result-file tests (areatest, viewtest,
circumferencetest, trimlinetest, thicknesstest).
Open question: full UI replacement vs incremental layering (asked).

## Decision ID: DEC-0009
Date: 2026-06-13
Decision: Full uFit-style rebuild of the brace UI — a workflow shell with step state,
Checkpoints + Rollback, Assistance (image+text), Progress, View/View-Modes, and the top
annotation/select tools — replacing the current 5-stage wizard over successive patches.
Reason: user chose "Full uFit-style rebuild" over incremental layering.
Alternatives: layer onto existing wizard.
Why rejected: user wants the full uFit clinical UX.
Clinical risk: none added; improves guidance.
Technical risk: large restructure — MUST be phased (one module per patch), keep
existing operators registered so nothing breaks mid-migration; test each slice.
Rollback plan: per-patch; keep wizard panel until shell reaches parity.
Files affected (phased): ui/panels.py (new shell), new operators/view_ops or ui_ops
additions, core step-state props; later checkpoints/assistance/progress modules.
Tests required: per slice (first: view/alignment).

## Decision ID: DEC-0010
Date: 2026-06-13
Decision: First build slice = Req 2 + Req 6 — View panel (Quad View / Ortho / Full
Screen + View-Modes Top/Front/Left/Right/Back/Bottom) and quad-view alignment.
Reason: user chose it first; clean alignment underpins all later steps.
Alternatives: P0 sculpt first; or shell-assistance first.
Why rejected: user preference; alignment is foundational.
Clinical risk: none.
Technical risk: quad-view + fullscreen via screen ops need correct context override.
Rollback plan: isolated new operators + one panel section; deletable.
Files affected: operators/ui_ops.py (+ view ops), ui/panels.py (View section), selftest.
Tests required: a GUI result-file test asserting the new view operators register +
toggle (quad/ortho/fullscreen) and view-axis ops run.

## Decision ID: DEC-0011
Date: 2026-06-17
Decision: Patch 2 shipped — Workflow shell (Progress + Assistance + Design History).
Design history ports WASP wm_next/wm_back as one snapshot per major brace stage
(NN_<patient>_<stage> in a per-patient collection), with rollback-by-stage and
forward-history rebuild on re-Next. Additive — the existing 5-stage wizard
(RIGO_PT_main) is untouched and still works.
Reason: user-chosen next build; the backbone every later stage plugs into.
Alternatives: snapshot every edit (rejected — heavy); replace wizard now (deferred).
Clinical risk: none (non-destructive history).
Technical risk: mesh-copy memory per stage — acceptable at major-stage granularity.
Rollback plan: new module history_ops.py + panel RIGO_PT_workflow + core props are
isolated/deletable; wizard unaffected.
Files affected: core/__init__.py (BRACE_STAGES, brace_stage/brace_patient),
operators/history_ops.py (new), operators/__init__.py, ui/panels.py (RIGO_PT_workflow),
ui/icons.py (assist images), selftest.py, tools/historytest.py.
Tests required: historytest.py (PASS), selftest (ALL_PASS). Provenance PROV-0006.

## Decision ID: DEC-0012
Date: 2026-06-17
Decision: De-noise the Scan stage (UI-only). Shaping (Push/Pull/Thicken/Smooth-region)
lives ONLY in the Mesh/Shape stage; Scan gets a cleanup-only selection
(`_draw_clean_select`: paint/grow/shrink/clear/invert/delete) and the Transform box
(Rotate/Move/Recenter) is relocated into the View panel's "Align" group.
Reason: user reviewed the Scan panel and asked to remove repeated/unnecessary tools; the
shaping suite was the same shared `_draw_select_box` drawn in Scan+Mesh+Design.
Alternatives: leave shared block in all 3 (rejected — repetition); fold into Patch 3.
Why now: UI-only, low-risk, reversible, operators untouched → nothing orphaned (alignment
reachable in View; shaping in Mesh).
Clinical risk: none. Technical risk: none (no operator/registration change).
Rollback plan: restore `_draw_select_box` call in `_draw_scan`; remove Align box from View.
Files affected: ui/panels.py (_draw_clean_select new; _draw_scan trimmed; RIGO_PT_view
Align box).
Tests required: selftest (ALL_PASS), scanshot (draws clean, no errors). Done.
Follow-up: dedupe Design stage's shaping block when Patch 4 (Shape) lands. [DONE same day:
removed _draw_select_box from _draw_design; dead props SELECTION_VGROUP/select_symmetry/
select_brush_size removed; stale root result files deleted; selftest/selecttest/designtest PASS.]

## Decision ID: DEC-0013
Date: 2026-06-17
Decision: Patch 3 shipped — Clean stage. New operators/clean_ops.py adds `center_model`
(origin→bounds-centre, sit on world origin; distinct from Align's drop-to-floor) and
`verify_clean` (counts non-manifold/boundary-holes/loose, stashes them on the object as
rigo_boundary/nonmanifold/loose/verify_ok, highlights non-manifold edges in Edit Mode).
Auto-Remesh reuses the EXISTING `rigo.remesh` (voxel) presented with a "Detail (mm)"
slider — no duplicate operator. Scan tab reorganized into "Clean Up" + "Verify Clean-up".
Reason: planned next slice; Auto-Remesh control is the WASP feature the user wanted; the
verify gate is the uFit "Verify Clean Up" step.
Alternatives: add a new auto_remesh op (rejected — duplicate); add center via recenter_floor
(rejected — that floors; center is a distinct working step).
Clinical risk: none. Technical risk: none (additive; verify is read-only + selection).
Rollback plan: delete clean_ops.py + its registration + the panel Clean/Verify edits.
Files affected: operators/clean_ops.py (new), operators/__init__.py, ui/panels.py
(_draw_scan Clean+Verify), selftest.py, tools/cleantest.py.
Tests required: cleantest.py (PASS — center→hole→detect→fill→remesh watertight),
selftest (ALL_PASS). Provenance PROV-0007.

## Decision ID: DEC-0014
Date: 2026-06-18
Decision: Adopt three tooling upgrades to reduce geometry mistakes and raise productivity
(user-approved after reviewing a ChatGPT advisory). Explicitly REJECT the advisory's
18-sub-skill explosion and its external GitHub packs.
  1. **Blender MCP live loop** (ahujasid/blender-mcp, MIT) — a see→measure→fix loop so the
     agent can screenshot the viewport and read vertex/bbox/manifold/self-intersection
     live, instead of the current BLIND text-result-file loop. Root-cause fix for the past
     3D errors (Bend axis, apply-units off-camera) that only the user could see. User
     installs + authorizes on their machine; agent supplies config + usage discipline.
  2. **CorrectionRegion data-object model** — pressure/expansion becomes measurable data
     (anatomical_label, center, direction, magnitude_mm, radius_mm, falloff, surface_mask,
     opposing_expansion_region, enabled, kind), NOT untracked moved vertices. Becomes the
     backbone of Patch 4 (Guided sculpt). Matches the user's standing "measurable not
     hand-painted" principle (pads/ventilation).
  3. **Quantitative acceptance gates + fixtures** — upgrade tests from PASS=True to hard
     numeric gates (timing, zero non-manifold, no self-intersection, exact undo restore,
     original scan unchanged) over a fixtures/ set of torso scans + golden outputs.
Reason: the one real weakness in our process is that the test loop is blind (text only);
MCP fixes that. The region model + numeric gates make corrections reproducible and
provable — directly serving "minimize mistakes, maximize productivity".
Alternatives: 18 small skills + vendor OpenAEC/computational-design/Blender-Dev-Tools
packs (REJECTED — over-scaffolding/drift; wrong domain AEC/BIM/artistic; one is
CC-BY-NC-ND = not usable in a commercial medical product). trimesh dependency (DEFERRED —
bmesh already covers manifold/boundary/loose; add only on a real self-intersection need).
Clinical risk: none (infra + data model); region model IMPROVES reviewability.
Technical risk: MCP add-on must run on Blender 5.0 (patch if it errors); region model is a
new isolated module. Rollback: MCP is external (remove server); region model deletable.
Files affected: docs/blender_mcp_setup.md (new guide), knowledge/correction_region_model.md
(new design), roadmap.md; (future code) operators/region_ops.py + core props + tests.
Tests required: connection check for MCP; regiontest.py with numeric gates for Patch 4.
Provenance: MCP = learned-from/config-only (log a PROV entry if any code is adapted);
CorrectionRegion schema = concept adapted from the advisory, clean original implementation.

## Decision ID: DEC-0015
Date: 2026-07-03
Decision: Issue-fix wave from the first full live audit — verify-then-fix, one patch per
issue. Patch A: remold_ops 5.0 API fix (enter Sculpt first; version-tolerant
_unified_paint_settings; warn instead of crash). Patch B: history keyed to the typed
brace_patient (fallback obj.name; stamped rigo_patient untouched). Patch C: black
captures declared resolved-by-A after a clean-session bisect (bright ~0.73 through the
full heavy pipeline incl. fixed remold, pads, bend, emboss); capture-hardening rules
documented instead of patching the MIT bridge add-on. Patch D: issues.md rewritten as a
status board — 5 findings invalidated with evidence, 1 new low-priority edge (#13:
generate_corset mid-deform copies the live modifier).
Reason: the user asked to solve the audit issues one by one; planning re-verify showed
most findings were audit-method artifacts, so fixing them would have been wasted/harmful.
Alternatives: fix all 12 as written (rejected — 5 were false); fold remold into Patch 4
now (rejected — 2-line compat fix keeps a working tool per preserve-tools rule; folding
stays on the Patch-4 agenda).
Clinical risk: none; patient-keyed history IMPROVES record traceability.
Technical risk: low — two small module edits, both numerically gated.
Rollback plan: revert remold_ops.py / history_ops.py hunks; issues.md is docs.
Files affected: operators/remold_ops.py, operators/history_ops.py, tools/remoldtest.py
(new), tools/historytest.py (extended), issues.md, docs/blender_mcp_setup.md,
error_log (ERR-0008/0009), learned_memory (LM-0012), roadmap.
Tests required: remoldtest PASS=True, historytest PASS=True, selftest ALL_PASS. ERR-0008/0009.

## Decision ID: DEC-0016
Date: 2026-07-03
Decision: Quad meshing = Blender's built-in QuadriFlow, exposed as `rigo.quad_remesh` +
`quad_target_faces` setting in the Clean stage next to Auto-Remesh. The operator
pre-checks watertightness (bmesh boundary/non-manifold) and refuses with "run Fill Holes
or Auto-Remesh first" — turning QuadriFlow's hard input requirement into clinical
guidance that enforces the correct Clean order. Exoside Quad Remesher (ZRemesher author's
commercial add-on): NOT bundled (closed-source, paid, GPL-incompatible to ship); optional
runtime detection explicitly declined by the user for now.
Reason: user asked for ZRemesher-style quad meshing; empirical probe on Brace Sample.stl:
107,726 tris -> 7,556 faces, 100% quads, watertight, manifold, 7.2 s. Flow quads deform
better under Bend/Twist/Stretch, the coming lattice (Patch 5) and Guided sculpt (Patch 4).
Alternatives: Exoside (better flow/robustness/speed but every winning dimension is one our
pipeline doesn't stress, plus licensing); voxel-only (grid quads, wrong topology for deform).
Clinical risk: none — export re-triangulates for STL; detail loss bounded by target faces.
Technical risk: low; guard prevents the known QuadriFlow failure mode.
Rollback plan: remove operator + prop + panel rows + test.
Files affected: core/__init__.py (quad_target_faces), operators/mesh_ops.py
(RIGO_OT_quad_remesh), ui/panels.py (Clean box rows), tools/selftest.py, tools/quadtest.py.
Tests required: quadtest.py PASS=True (guard refuses holed mesh; 7,697/7,697 quads,
boundary 0, non-manifold 0, within target band), selftest ALL_PASS=True.
Note: scripted bpy.ops turns report({'ERROR'})+CANCELLED into RuntimeError — tests must
expect the exception (ERR-0009 family).

## Decision ID: DEC-0017
Date: 2026-07-03
Decision: Patch 4a shipped — Guided Sculpt on the CorrectionRegion data model
(knowledge/correction_region_model.md). Core: RigoCorrectionRegion PropertyGroup
(anatomical_label, kind PRESSURE/EXPANSION, center, mean-normal direction, magnitude_mm,
radius_mm, falloff, surface_mask vgroup, opposing_region, enabled, requires_review)
mounted as Object.rigo_regions + rigo_region_index — corrections travel WITH the mesh.
Operators (region_ops.py): region_add (paint selection -> BFS ring feather from the
boundary, mm feather converted via mean selected edge length, weights normalized so the
core always reaches 1.0), region_apply (co += mean_normal * ±mm * weight; PRESSURE
inward), region_mirror (KDTree nearest-vertex weight transfer across X=0, kind flipped,
opposing linked both ways), region_remove (mask deleted, opposing indices re-pointed).
Panel: Guided Sculpt box in the Mesh stage (defaults + UIList RIGO_UL_regions + per-region
kind/amount/landmark + Apply/Mirror/Remove).
Resolved design choices: store on OBJECT; direction = mean surface normal; MANUAL mirror.
Reason: the P0 core shaping tool; measurable-not-hand-painted per the user's standing rule.
Alternatives: uFit-style vertex-color regions (rejected — our Edit-Mode selection IS the
region, LM-0002); per-vertex-normal displacement (deferred — uniform mean normal is the
clinical "pad direction" and makes the mm gate exact).
Clinical risk: guided by orthotist-entered mm; requires_review=True on every region.
Technical risk: low; mirror on asymmetric anatomy degrades to nearest-vertex clustering
(fine on real torsos, noted on the limb sample).
Rollback plan: remove region_ops.py + core class/props + panel box + tests.
Files affected: core/__init__.py, operators/region_ops.py (new), operators/__init__.py,
ui/panels.py, tools/selftest.py, tools/regiontest.py (new).
Tests required: regiontest.py PASS=True — max_err 0.0000 mm, max_disp 10.000 mm exact,
outside_moved 0, verts unchanged, no new non-manifold, 0.05 s (<2 s gate); mirror couple
created + applies; remove cleans mask + links. selftest ALL_PASS=True. Live MCP demo:
quad remesh -> paint -> add -> 12 mm apply at 0.01 s.
Remaining for Patch 4b: circular quick-region variant, X-ray overlay Move/Rotate/Scale +
apply, fold/retire remold into Free box, per-region falloff rebake.

## Decision ID: DEC-0018
Date: 2026-07-06
Decision: Patch 4b shipped — (1) `rigo.region_add_circle`: circular quick-region at the
3D cursor using edge-walk Dijkstra GEODESIC distance capped at region_radius, so the
region cannot bleed through to the far side of the body the way a euclidean sphere
would; weight = falloff(1 - d_geo/r), seed forced to 1.0; refuses when the cursor is off
the surface. (2) Falloff choice (SMOOTH/LINEAR/SHARP) at Add time for both region ops,
stored per-region. (3) X-ray overlay transforms: `rigo.xray_transform` (MOVE constrained
to the coronal XZ plane / ROTATE in-plane around Y / SCALE uniform — native modal
transforms via INVOKE_DEFAULT; execute path selects only, for scripts), and
`rigo.xray_lock` toggle — parents the overlay to the scan with matrix_parent_inverse so
there is NO visual jump, making it follow every later model move; unlock preserves the
world transform. (4) Remold presented as "Free Sculpt (brushes)" in the Mesh stage with
a note that freehand edits carry no mm record.
Reason: the remaining Patch-4 items the user approved (LeoSpinal X-ray overlay
move/rotate/scale + apply; uFit circular push/pull analog).
Alternatives: euclidean-sphere circle (rejected — bleeds to the opposite wall on thin
bodies); custom modal transform code (rejected — native transforms are better UX).
Clinical risk: none added; overlay is reference-only imagery, kept local.
Technical risk: low. Rollback: remove the two ops + panel rows + props.
Files affected: core/__init__.py (region_radius, region_falloff),
operators/region_ops.py (region_add_circle + falloff wiring),
operators/deform_ops.py (xray_transform, xray_lock), ui/panels.py (Guided box circle
row, X-ray Move/Rotate/Scale + Lock row, Free Sculpt relabel), tools/selftest.py,
tools/regiontest.py (circle phase), tools/xraytest.py (new).
Tests required: regiontest PASS (circle: seed weight 1.000 exact, geodesic containment
max_d 29.0 <= 30 mm, rim falloff -> 0, 241 verts); xraytest PASS (lock jump 0.00e+00,
follows model dx exactly 0.123 m, unlock jump 1.19e-07); selftest ALL_PASS.

## Decision ID: DEC-0019
Date: 2026-07-06
Decision: Patch 5 shipped — Lattice cage + multi-section derotation (WASP port,
PROV-0008). New operators/lattice_ops.py: lattice_add (auto-fit 3x3xN cage to the scan
bbox +5%, LINEAR interpolation, use_outside), lattice_edit (toggle point editing),
lattice_twist (per-section dials r0..r9 in the redo panel; button seeds a 0->total
gradient from settings.lattice_twist — pelvis anchored; scale-compensated rotation
around Z through the cage centre; every press adds), lattice_apply (bake + remove cage),
lattice_discard (remove without touching the scan). Panel box "Lattice Derotation" in
the Mesh stage. Settings: lattice_sections (2-10), lattice_twist (degrees).
Reason: the spine derotation stage of the rebuild; user-approved next patch.
Alternatives: WASP verbatim port (rejected — view-axis rotation is nondeterministic;
manual dimensions; B-spline smear); Simple Deform TWIST (already exists — whole-body
twist only, no per-section control; both kept, different clinical jobs).
Clinical risk: magnitudes orthotist-entered, undoable, discard restores exactly.
Technical risk: caught pre-ship — ERR-0011 (lattice rest span = points-1, not 1).
Rollback plan: remove lattice_ops.py + registration + panel box + props + test.
Files affected: core/__init__.py (lattice_sections/lattice_twist),
operators/lattice_ops.py (new), operators/__init__.py, ui/panels.py, tools/selftest.py,
tools/latticetest.py (new).
Tests required: latticetest PASS (gradient 0.8/14.1/29.2° vs dials 0/15/30; radial
drift 0.13 mm — no shear; apply bakes exactly; discard max_delta 0.00e+00), selftest
ALL_PASS. Provenance PROV-0008.

## Decision ID: DEC-0020
Date: 2026-07-06
Decision: Patch 6 shipped — Trim-edge finishing. New operators/trim_ops.py:
toggle_seethrough (viewport show_xray, WASP concept), smooth_trim_edge
(CorrectiveSmooth restricted to the trim band, unpinned, baked+applied), flare_edge
(radial-XY safe edge, mm-exact at the rim, feathered over the band). KEY DESIGN: the
solidified corset has ZERO boundary edges (Solidify closes the rim), so the feathered
RIGO_TRIM_BAND vertex group is baked in design_ops._build_corset AFTER _trim_and_open
and BEFORE Solidify — the only moment the cut is an open boundary; Solidify propagates
the weights to both walls and the rim. Trim ops consume the baked group and tell the
user to re-Generate if it is missing. Panel: "Trim Edge Finishing" box in Design stage.
Reason: planned Patch 6 (trim lines: X-ray view + one-button smoothing + flared width).
Alternatives: detect the rim geometrically post-solidify (rejected — fragile);
boundary-based band at op time (impossible — no boundary).
Clinical risk: low — finishing ops, undoable; flare default 6 mm, band 15 mm.
Note: default 50 smooth passes contracts the band strongly (area 0.071->0.015 on the
sample); orthotist can lower the passes — revisit default after real-torso feedback.
Rollback plan: remove trim_ops.py + registration + panel box + the design_ops hook.
Files affected: core/__init__.py (trim_smooth_iters/edge_flare/edge_band),
operators/trim_ops.py (new), operators/design_ops.py (band bake hook),
operators/__init__.py, ui/panels.py, tools/selftest.py, tools/trimtest.py (new).
Tests required: trimtest PASS (band 7,638 members; smooth: band area shrinks, far vert
frozen 0.00e+00, count unchanged; flare: 2,026 rim verts radial 6.000 mm err 0.000,
dz 0; see-through toggles), selftest ALL_PASS. Provenance PROV-0009.

## Decision ID: DEC-0021
Date: 2026-07-07
Decision: Patch 7 shipped — Parametric ventilation + #13 guard. New
operators/vent_ops.py: vent_paint (activates the corset + reuses the paint-select
pipeline) and vent_grid — a measured hole grid over the painted area: tangent-plane grid
at spacing S, BVH raycast along the region normal onto the painted faces, one merged
cylinder cutter (16-seg, ±30 mm along each hit normal), single BOOLEAN DIFFERENCE with
the MANIFOLD solver (EXACT fallback), then 1 µm remove_doubles + dissolve_degenerate
hygiene. Safety: refuses bridge (spacing − Ø) < 3 mm (manufacturing_constraints);
skips grid points touching the RIGO_TRIM_BAND so holes can never break the rim; hole
cap 400. #13 guard: generate_corset now REFUSES while a Bend/Twist/Stretch session is
live ("Apply or Reset first"). Panel: Ventilation box in Design with live bridge
readout. Scope note: uFit "keep-part"/scale/unified-thickness NOT duplicated — already
covered by Box Erase/paint-delete, scale_girth, and Generate's thickness (noise rule).
Reason: the user's chosen "measurable, not hand-painted" ventilation (DEC-0014 plan).
Alternatives: WASP hand-painted holes (rejected by user); per-hole modal placement
(rejected — not measurable/regular).
Clinical risk: ventilation zone is orthotist-painted; bridge floor + rim protection
enforced; undoable.
Technical risk: boolean robustness — mitigated by MANIFOLD solver + hygiene pass +
genus-verified test. Rollback: remove vent_ops.py + registration + panel box + props +
the design_ops guard.
Files affected: core/__init__.py (vent_diameter/vent_spacing), operators/vent_ops.py
(new), operators/design_ops.py (#13 guard), operators/__init__.py, ui/panels.py,
tools/selftest.py, tools/venttest.py (new).
Tests required: venttest PASS — #13 refusal, 2 mm-bridge refusal, and the topology gate:
holes = (χ_before − χ_after)/2 = 11 exactly, boundary 0→0, non-manifold 1→1 (the cut
adds ZERO defects). selftest ALL_PASS.
Discovered: issue #14 — generate_corset itself can leave a pinch edge (one 4 mm edge
with 4 link faces) at the trim on some geometry; fold a manifold-repair pass into
Patch 8 Export QA.

## Decision ID: DEC-0022
Date: 2026-07-07
Decision: Pressure-library fix wave (user report "does not work"). Live investigation
proved the ENGINE fully functional — prefill, place 0.03 s, apply dents EXACTLY the set
depth (8.0 / 12.0 mm measured), record -> disk -> survives real Blender restart,
re-place + re-apply exact. Four GUI failure modes found and fixed in pad_ops.py:
 1. FREEZE (reproduced, wedged Blender >2 min): placing with a live modifier on the
    scan makes all 12 drape raycasts re-evaluate the heavy evaluated mesh. Fix:
    _modifier_block_msg guard on add_pad AND place_pad BEFORE any drape work.
 2. Misleading refusal: apply_pads always said "reset the active deform" — now all
    guards NAME the offending modifiers.
 3. Invisible result: shapes correctly modify the SCAN (the mold) which a visible
    corset hides -> _warn_if_corset_hides_result on place/apply + scan unhidden.
 4. At-Cursor trap: cursor at origin snaps to an unexpected spot -> warn when the
    snap travelled > 200 mm, pointing to Shift+Right-Click / Place on Scan.
Reason: user-reported breakage; verify-before-fixing (LM-0012) again separated a
healthy engine from real UX bugs.
Clinical risk: none — guards/messages only; behavior of apply unchanged (exact mm).
Rollback: revert pad_ops.py hunks; delete padfavtest.py.
Files affected: operators/pad_ops.py, tools/padfavtest.py (new).
Tests required: padfavtest PASS (7 phases: prefill; apply == depth exactly, 658 verts;
record; favourites on disk; force-reload prefill; favourite re-apply 12.00 mm; guard
refuses in 0.00 s naming the modifier). Regression: padtest PASS, padshapetest PASS,
selftest ALL_PASS. User's real library restored (builtin favourites reset, QA entries
removed, user's own MY_SHAPE preserved).

## Decision ID: DEC-0023
Date: 2026-07-08
Decision: Auto Trim Lines by Rigo type (user-reported generation bug + feature request).
(1) Templates: trim boundaries extracted from the user's reference pairs as top/bottom
angular profiles in normalized body coordinates (72 theta-bins around the pelvis axis,
front = ASIS midpoint; z piecewise-linear over bottom=trochanter / waist=WAISTLINE /
top=acromion anchors); JSON in rigo_brace/templates/ + core/trim_templates.py loader
(cached dynamic enum). (2) operators/trimline_ops.py: auto_trimline drapes the template
onto the patient scan via landmark anchors (graceful fallbacks with warnings; exact
parameterization STAMPED on the curves), producing TWO editable Bezier curves (top red,
bottom green) the orthotist refines; edit_trimline / clear_trimlines. (3) design_ops:
trim-curves path in _trim_and_open — faces survive only where bottom(theta) <= z <=
top(theta) (dense evaluated-curve sampling; _profile_height interpolation); flat trims +
parametric opening remain the fallback. This FIXES the reported bug (flat bbox trims on
real torso scans produced a barely-trimmed full-body shell — head/arms now fall outside
the profiles automatically).
User decisions: full landmark set; expansion windows manual in v1; subtype calibration
via the user's forthcoming Rigo classification graphics; files = A1-A3/B1-B2 family.
Clinical risk: guided-not-prescribed — requires_orthotist_review on templates, lines are
refinable starting points; anchors warn when landmarks are missing.
Technical risk: extraction noise (mitigated: percentile + smoothing; validated visually
against the real brace rim); test-side chord-vs-bezier mismatch documented in the test.
Rollback: remove trimline_ops.py + templates/ + trim_templates.py + design_ops hunk.
Files affected: rigo_brace/templates/trimline_{A,B}.json (new), core/trim_templates.py
(new), core/__init__.py (trim_type), operators/trimline_ops.py (new),
operators/__init__.py, operators/design_ops.py, ui/panels.py, tools/selftest.py,
tools/trimlinetest.py (new).
Tests required: trimlinetest PASS — 24+24 control points, drape max 1.5 mm off-surface,
top_mean > waist > bot_mean, corset faces within [bottom-12, top+12] per angle (3 rim
faces at the steep front-V allowed of 100,156), czmax <= top+15 mm; selftest ALL_PASS.
Provenance PROV-0010.

## Decision ID: DEC-0024
Date: 2026-07-08
Decision: Calibrated the trim-line template system against the user's Rigo 2010
classification paper (PDF now in the project root; rendered + read). Recorded the full
type→brace-design correlation in rigo_cheneau_design_rules.md (A1 / A2+A3 / B1+B2 /
C1+C2 / E1 / E2 categories). Template JSONs updated: subtype + brace_design +
classification_ref fields — user's A = 3C Classical (A2+A3), B = 4C Classical (B2-like);
both verified closed-pelvis via the 72/72-bin coverage. Template ids stay "A"/"B" until
subtype-specific references (A1/B1 open-pelvis, C, E1, E2) are provided.
Reason: user supplied the canonical classification source for precise subtype anchoring.
Clinical risk: none — documentation + metadata; classification remains the orthotist's
radiographic decision.
Files affected: rigo_brace/templates/trimline_{A,B}.json (metadata),
knowledge/rigo_cheneau_design_rules.md.
Tests required: none (metadata); trimlinetest remains green.

## Decision ID: DEC-0025
Date: 2026-07-08
Decision: Shell Smoothing stage in Generate (user report: "the splint does not wrap
around the body correctly"). Diagnosis (measured vs the REAL A brace, 4000-sample BVH
nearest-distance): the trim SHAPE was correct, but the shell surface copied every body
fold/crease (shrink-wrap look) because offset+solidify follows the mold 1:1, while a
real splint is a smooth rigid envelope. Fix: `corset_smooth` setting (default 40 passes,
0 = old behavior) — a strong SMOOTH modifier applied to the corset base AFTER the liner
offset, BEFORE trim+solidify, so the shell bridges folds. Deviation vs the real brace:
median 9.5 mm / p90 24 mm — unchanged by smoothing, as expected: that gap is the
EXPANSION-ZONE standoffs, which per the user's decision are manual v1 work (windows /
Guided-Expansion regions), not surface texture.
Edit round-trip PROVEN (user request "test the full migration"): moved 3 top control
points down 60 mm at patient-left and 3 bottom points up 30 mm at the front →
regenerated shell followed with 59.3 mm drop and 31.0 mm rise at those angles, 0.0 mm
change on the untouched back. Edits are local and exact.
Clinical risk: smoothing slightly rounds sharp corrective prominences — orthotist
controls via the slider; 0 disables.
Rollback: corset_smooth=0 or revert the design_ops hunk.
Files affected: core/__init__.py (corset_smooth), operators/design_ops.py (Shell Smooth
in generate), ui/panels.py (slider).
Tests required: trimlinetest PASS (with smoothing default), selftest ALL_PASS. Both green.

## Decision ID: DEC-0026
Date: 2026-07-11
Decision: Replaced the two disconnected workflow states with one canonical five-stage
state (`brace_stage`: File, Scan, Landmarks, Mesh Edit, Design). Removed the duplicate
Brace Workflow/Design History panel and `active_tab`. Panel buttons, panel Next/Back,
the viewport header and optional workspace synchronization now share that state. The
single-mesh history operators remain registered but hidden and marked legacy until a
complete patient-project checkpoint prototype replaces them.
Reason: the nine-stage shell and five-stage tool panel could advance independently, and
the exposed rollback copied only `scan_object`, not the complete brace design.
Alternatives: keep and synchronize both states; expose the old history until replacement;
delete history code immediately. Rejected because two state machines invite future drift,
the old UI overpromises restoration, and immediate deletion would discard migration
reference before ticket #3.
Clinical risk: reduced — users no longer see a rollback control that can omit pads,
trimlines, landmarks, shell and reference objects.
Technical risk: saved files no longer expose `active_tab`; the canonical enum retains the
five stage identifiers already used by the functional tool panel.
Rollback plan: restore `active_tab`, `RIGO_PT_workflow`, and their previous navigation
references from the pre-DEC-0026 source copy.
Files affected: core/__init__.py, ui/panels.py, ui/icons.py, operators/ui_ops.py,
operators/history_ops.py, tools/selftest.py, tools/historytest.py, screenshot scripts,
tools/workflowtest.py.
Tests required: workflowtest PASS; selftest ALL_PASS; hidden legacy historytest PASS;
source/install hash equality; visual Blender panel inspection.

## Decision ID: DEC-0027
Date: 2026-07-11
Decision: Pressure-library schema v2 removes clinical claims from built-ins. New installs
receive only neutral Blank Oval and Blank Rounded Rectangle primitives. Existing v1 JSON
is backed up byte-for-byte once, then all entries are preserved; eight clinical-named
circles move to `UNVERIFIED_LEGACY`, become deletable non-builtins, retain their actual
kind/depth/size, and record missing-handle fidelity. All entries require orthotist review.
Reason: every old clinical preset had identical circle geometry, and stored kind could
contradict the clinical label. User approved backup + legacy migration.
Alternatives: delete old entries; silently rename them; keep them as builtins. Rejected
because deletion loses user data, silent rename hides provenance, and builtins preserve a
false clinical promise.
Clinical risk: reduced; legacy geometry remains accessible but visibly unverified.
Technical risk: migration writes user config. Mitigated by atomic write, byte-identical
v1 backup, isolated real-filesystem regression and idempotence test.
Rollback plan: restore `pad_library.json.v1.backup.json` as `pad_library.json` and use the
pre-DEC-0027 add-on.
Files affected: core/pad_library.py; pad tests/debug scripts; new padlibrarytest.py;
pressure feature spec and decision map.
Tests required: padlibrarytest PASS; padtest, padshapetest, padfavtest PASS; selftest
ALL_PASS; installed/source hashes equal.

## Decision ID: DEC-0028
Date: 2026-07-11
Decision: Implemented the approved first user-operable Pressure/Expansion slice: modal
surface-click Draw New Boundary, Boundary terminology, exact evaluated Bézier point and
left/right handle persistence, Generate Saved handle restoration, and Edit Boundary.
Reason: schema migration alone did not satisfy the requested authoring workflow and was
correctly rejected by the user as “not working.”
Clinical risk: authoring only; user guide explicitly forbids treating the legacy
destructive Apply as validated iterative preview.
Technical risk: curved-surface handle draping can change world-space tangents, but the
normalized template round-trip on a controlled surface is `≤6.77e-08` and remains
editable per patient.
Rollback plan: remove `RIGO_OT_draw_boundary`, UI button/labels, schema-v2 handle fields,
and boundarytest; schema-v1 backup remains untouched.
Files affected: operators/pad_ops.py, ui/panels.py, tools/selftest.py,
tools/boundarytest.py, tools/padshot.py, QA/spec/user-guide documentation.
Tests required: boundarytest PASS; existing pad tests PASS; selftest ALL_PASS; visual
edit capture; manual orthotist UI check pending.

## Decision ID: DEC-0029
Date: 2026-07-12
Decision: A committed CorrectionRegion can be saved as a global reusable style and
imported at the 3D cursor onto another scan. `region_library.json` stores surface-local
millimetre point/weight samples, mesh-spacing and curvature tolerances, kind, magnitude,
falloff and `requires_orthotist_review=true`. Import reprojects to the target surface,
adapts to target edge spacing and creates an editable live region before Commit.
Reason: the user needs to reuse the exact authored pressure/expansion area after Commit,
not return to the rejected floating curve workflow.
Alternatives: save vertex indices; save a world-space mesh; reuse the curve-pad JSON.
Rejected because indices/topology differ by patient, world coordinates are not portable,
and curve templates discard the authoritative weighted selection.
Clinical risk: saved geometry is descriptive, not prescriptive; every import requires
orthotist review.
Technical risk: tangent-plane projection can distort very large/high-curvature masks;
sampling tolerance and user edit are retained, while scale/rotation remain future work.
Rollback plan: remove region_library.py and the three style operators/properties/UI.
Files affected: core/region_library.py, core/__init__.py, operators/region_ops.py,
ui/panels.py, tools/regionstyletest.py, documentation.
Tests required: regionstyletest PASS on a decimated different-topology target; regiontest
PASS; selftest ALL_PASS; installed/source hashes equal.

## Decision ID: DEC-0030
Date: 2026-07-12
Decision: Replace the primary two-plane deform UI with three filled draggable rings
(Lower, Middle, Upper) and active intervals Lower–Middle, Middle–Upper, or full
Lower–Upper. The active pair drives one Simple Deform modifier. Twist and Stretch add a
live height-mask vertex group that fades to zero at both rings, keeping both outside
zones fixed. Bend retains its manually approved rigid-continuation behavior. Stretch is
entered in millimetres and calibrated against the active mask so requested peak movement
matches evaluated movement.
Reason: the project LeoSpinal transcript explicitly describes three-loop segment-limited
Stretch and multiple bounding curves for Twist; the user requires the same segment
control for Bend, Twist and Stretch.
Alternatives: two rings only; separate mesh segments; multiple stacked modifiers.
Rejected because two rings cannot choose either adjacent segment, splitting tears the
body, and stacked modifiers accumulate/complicate Apply and Reset.
Clinical risk: the orthotist selects ring levels and amount; no automatic correction is
claimed.
Technical risk: the mask is rebuilt from ring world-Z after every ring movement; a
re-entrancy guard prevents dependency-graph recursion. Tests gate absolute outside
movement for Twist/Stretch, evaluated-vs-requested millimetres, and internal-distance
preservation for Bend.
Rollback plan: restore From/To panel and two disc creation; legacy properties remain.
Files affected: core/__init__.py, operators/deform_ops.py, ui/panels.py, deformation tests.
Tests required: segmentdeformtest, planestest, bendtest, stretchtest PASS; visual capture;
selftest ALL_PASS; installed/source hashes equal.
Status update 2026-07-12: user manually validated Bend, Twist, and Stretch. Marked
technically complete. Future icon, naming, label, or ring-shape work is UI-only and must
keep all DEC-0030 tests and numeric thresholds unchanged.

## Decision ID: DEC-0031
Date: 2026-07-12
Decision: Freeze production brace-generation changes until a unified-perimeter and exact
surface-cut prototype are validated on the supplied A fixture. Replace whole-face trim
deletion and post-hoc band smoothing rather than tuning their pass counts.
Reason: code audit and rendered baseline prove the current representation necessarily
creates jagged/spiked rims; A generated-to-reference RMS is 14.098 mm.
Alternatives: increase Corrective Smooth passes; remesh the entire finished brace;
continue with independent top/bottom cyclic curves.
Why rejected: smoothing cannot recover the intended contour, global remesh risks erasing
prescribed correction volumes, and two rings do not represent the one physical perimeter.
Clinical risk: no auto-prescription from surface landmarks; orthotist-defined curve type,
force pairs, sagittal objective and coverage are required.
Technical risk: exact arbitrary contour insertion and offset self-intersection handling
need isolated prototypes before production integration.
Rollback plan: no production code changed in this decision.
Files affected: research, decision map, provenance, baseline diagnostic only.
Tests required: future A/B perimeter overlay, exact-cut, manifold, thickness, curvature,
signed-deviation and visual gates described in the decision map.

## Decision ID: DEC-0032
Date: 2026-07-12
Decision: Integrate the first unified-perimeter generator after its A fixture geometry
gate passed. Preserve the hidden legacy top/bottom curves only for backward compatibility;
the visible/editable authority is `Rigo Trim Perimeter`.
Reason: the new curve and exact cut remove the deterministic spike mechanism while keeping
the result editable and attached to the corrected mold.
Alternatives: boolean cutter volume; global voxel remesh; continue face-center deletion.
Why rejected: boolean robustness was not yet demonstrated, global remesh can erase clinical
corrections, and face-center deletion is the proven failure source.
Clinical risk: templates are starting geometry only and still require orthotist review;
surface landmarks do not prescribe Rigo correction.
Technical risk: isolated triangle aspect max is 50.66 although p95 is 1.45 and the shell is
manifold; thickness/self-intersection and signed-deviation reports remain follow-up gates.
Rollback plan: remove perimeter object/UI and clipping helpers, then restore legacy trim
curve precedence; baseline diagnostic remains for comparison.
Files affected: trimline_ops.py, design_ops.py, core/__init__.py, panels.py and tests.
Tests required: trimlinetest, trimtest, designtest, exporttest, workflowtest, selftest PASS;
manual A visual check next.

## Decision ID: DEC-0033
Date: 2026-07-12
Decision: Make the unified perimeter mandatory for Generate, retire the duplicate
top-only outline and standalone-thickness controls from the clinical UI, and make
manufacturing QA a blocking export gate. Round only true rim-junction edges.
Reason: the legacy fallback produced defective geometry and hidden trim defaults; the
global bevel introduced three A-shell self-intersections; export previously proved file
creation but not printability.
Alternatives: keep both trim systems; warn but export; reduce the global bevel width.
Why rejected: competing authorities drift, warnings do not prevent unsafe artifacts, and
the same three intersections remained even at half bevel width.
Clinical risk: QA proves technical geometry only; orthotist sign-off remains mandatory.
Technical risk: thickness is deterministic sampling rather than a formal all-surface
minimum proof; coverage and threshold are reported and configurable.
Rollback plan: restore the removed panel controls and non-blocking export; keep QA code
for diagnostics. Do not restore the global bevel without an intersection-safe method.
Files affected: qa_ops.py, io_ops.py, design_ops.py, core settings, panels and tests.
Tests required: qatest, trimlinetest, trimtest, venttest, designtest, embosstest,
outlinetest, exporttest, workflowtest and selftest.

## Decision ID: DEC-0034
Date: 2026-07-13
Decision: Make `Rigo-Cheneau Reference` the first/default trim profile, express its
anterior opening in millimetres, and edit it through a surface-raycast modal tool. Build
the final wall as corresponding inner/outer surfaces offset along normals interpolated
from the complete corrected torso, then bridge and round one explicit rim.
Reason: the project owner's SpinalTech base4 reference proved the previous A/B-derived
default had the wrong design grammar. Generic Blender curve movement left controls off
the body, and Solidify recomputed normals after cutting, folding a concave rim into the
adjacent wall.
Alternatives: copy the reference mesh; use exact extracted reference vertices; increase
global fairing; enable Solidify thickness clamp; retain free 3D curve editing.
Why rejected: the external mesh has no redistribution licence and is not patient-specific;
global fairing risks corrections; thickness clamp removed intersections by collapsing a
wall to 0.03 mm; free movement did not preserve surface curvature.
Clinical risk: the profile is a starting silhouette, not a prescription. Tall-wing side,
coverage, pressure/expansion pairs, sagittal intent and any windows require orthotist
review. No reference vertices or faces enter patient output.
Technical risk at this decision's date: the B fixture produced two components,
16 intersections and a 0.358 mm local wall. Superseded by DEC-0035: that defective shell
is no longer installed; generation cancels safely when bounded outer-wall repair cannot
remove overlap, while B clinical readiness remains unresolved. Rim vertices are excluded
from thickness sampling only because a rounded edge tapers by construction; QA blocks
exclusions above 20% of vertices.
Rollback plan: remove `trimline_RIGO_CHENEAU.json` and the two surface-edit operators;
restore Solidify only together with the retained failing diagnostics and export block.
Files affected: trim templates/settings/UI, trimline/design/trim/QA operators, reference
assets, installed-copy tests and user guide.
Tests required: referencetrimtest, trimlinetest, trimtest, qatest, designtest, exporttest,
selftest; four-view render. Superseded by DEC-0035: B now cancels safely, but clinical
readiness remains blocked.

## Decision ID: DEC-0035
Date: 2026-07-13
Decision: Treat the perimeter/body pair and generated shell as two explicit workflow
states: TRIM is the source-edit state and BRACE is the clean generated-preview state.
Select trim controls only when visible from the active view. Mark the shell stale after
any requested-parameter or source-geometry change, and require Update Brace before
finishing, QA or export. Treat a missing source signature as stale, remove old trim
curves when a different patient scan is imported, and reject a perimeter that targets a
different scan. During generation, use exact triangle intersection results to
relax only colliding outer offset directions, preserving normalized requested pair length
and the inner patient-contact surface. Limit repair to 12 passes and 25 degrees; if it
still intersects, cancel candidate replacement transactionally. On any generator
exception, remove both private candidates and restore prior view/outline state before
reporting the known overlap or propagating an unexpected error.
Reason: hidden back-side clicks changed the wrong perimeter, stale-shell visibility made
thickness edits appear ineffective, and corresponding normal offsets can intersect even
when every vertex pair has the requested separation. The accepted workflow must make the
editable authority and the generated artifact unambiguous while containing geometry that
cannot meet the wall gate.
Alternatives: keep the scan, perimeter and brace simultaneously editable; regenerate on
every slider event; accept BVH overlap pairs as final intersections; reduce local pair
length to remove collisions; smooth or move the corrected inner surface; replace the
canonical shell before all checks finish.
Why rejected: simultaneous authority permits stale finishing; live regeneration is too
expensive for each UI change and hides failure; BVH is broad phase only; shortening pair
length silently violates requested thickness; moving the inner surface changes the
clinical mold; early replacement destroys the last valid result on failure.
Clinical risk: visibility, freshness, exact intersections and paired spacing are technical
guards only. They do not validate laterality, trim coverage, B-type force strategy or
fabrication. B remains unresolved even though its unsafe generation attempt is contained.
Technical risk: opposing-surface sampled wall thickness can be lower than the exact paired
construction spacing, especially near shaped rims. The QA sampler is deterministic but
is not a formal continuous minimum proof. A repair that exceeds the bounded direction
envelope is rejected rather than silently weakened.
Rollback plan: remove `design_view_mode`, dirty/signature checks and local direction
repair, but retain the exact-intersection and export gates. Do not restore stale export,
through-body point picking, thickness collapse or pre-validation object replacement.
Files affected: core settings/signatures; trimline, design, mesh-intersection, QA and IO
operators; Design panel; installed-copy regressions and user documentation.
Tests required: `trimvisibilitytest`, `designviewtest`, `meshintersectiontest`,
`thicknesstest`, `btrimlinetest`, `qatest`, `exporttest` and `selftest`. Orthotist
four-view review remains required before any B readiness claim. `btrimlinetest` reports
controlled cancellation through `SAFETY_PASS`, but its `READINESS_PASS` and overall
`PASS` remain false until generation and manufacturing QA succeed.
Installed evidence: the actual trim modal rejected the overlapping hidden point, dragged
the visible point to 1.499955 mm from the body and restored the session on Esc in
orthographic view. Its view origin uses a scan/view-derived precision clamp followed by
an unbounded BVH travel distance rather than a fixed 1000-Blender-unit cap.
`designviewtest`, `outlinetest`, `importtest`, `trimlinetest`, `referencetrimtest`,
`trimtest`, `qatest`, `exporttest` and `embosstest` report `PASS=True`. Independent
bidirectional-ray medians for 2/4/6 mm requests are 1.999/3.999/5.998 mm. The 6 mm wall
repairs 25 collision pairs to zero in seven passes with a maximum 18.287-degree direction
change; an unsafe 12 mm request cancels with the valid 6 mm shell/base retained. The
4 mm B overlap is contained (`SAFETY_PASS=True`) but remains unready
(`READINESS_PASS=False`, overall `PASS=False`).
The final QA negative fixture samples full coverage and records its 2.00 mm
measured/3.00 mm required result; export confirms QA reran before writing the isolated
canonical brace, and emboss confirms a real mesh change with temporary text removed.

## Decision ID: DEC-0036
Date: 2026-07-25
Decision: Fix the serrated/spiky rim by uniform arc-length resampling of the cut
boundary inside the curve generator (`_resample_cut_boundary`, called from
`_cut_surface` before normals are baked), keeping the ordered-ring frames and the
curvature clamp, and adding an explicit corner spike guard. Do NOT recalibrate the
20 % rim-exclusion export guard yet; measure and report it instead (29.7 %, down
from 40.5 %).
Reason: measured causal chain — 51x boundary spacing spread x (0.35 x spacing rim
ceiling) = 8.6x fillet amplitude swing = the visible serration; two radius-field
smoothing attempts measurably worsened the rim, proving the fix belongs upstream.
Alternatives: keep post-processing the radius field; raise fillet segments; shading
tricks (all explicitly forbidden by the user and/or measured worse). Ray-cast wall
clearance clamp was implemented, measured ineffective (rays coplanar with the
offending geometry), and removed the same session.
Why rejected: they treat the symptom while the per-vertex ceiling still tracks a
51x-uneven boundary.
Clinical risk: boundary vertices move along the trimline during resampling; fidelity
is measured after against the trimline polyline (p95 0.026 mm, max 2.73 mm at a
hairpin the trimline itself cannot follow) and gated in `rimresampletest`
(1.0 mm reference / 1.5 mm hostile). Target spacing is capped at 1.2 mm, so
delivered fillet radius is limited to ~0.42 mm regardless of larger requests.
Technical risk: the resample phases can create geometry defects of their own; every
one found was measured and closed (fold revert, valence-safe repair collapses,
ear-chord dissolve, forced n-gon fan triangulation, zero-area edge rotation), and the
pre-existing transactional validator remains the final gate.
Rollback plan: remove the `_resample_cut_boundary` call from `_cut_surface`; the
generator returns to the serrated-but-buildable state of commit eec0bec.
Files affected: `rigo_brace/operators/curve_build_ops.py` (resample pipeline, corner
guard, `_corner_spike_limits`); `tools/rimresampletest.py`, `rimqualitydbg.py`,
`rimstagedbg.py`, `rimresampledbg.py` (new diagnostics/regression).
Tests required: `rimresampletest`, `curvebuildtest` 4/4 determinism,
`customtrimseamtest`, `curvefinishtest`, `selftest`, `importtest`, `thicknesstest`,
`trimqualitytest`, `slotbracetest`, `referencetrimtest`.

## Decision ID: DEC-0037
Date: 2026-07-26
Decision: Fix the rim seam by correcting the cap cross-section in `_rim_profile`
(tangent quarter-arc / closing run / quarter-arc), NOT by any of the four architectures
proposed in the review - explicit swept solid with Boolean union, localized SDF smooth
union, hybrid implicit patch, or an external geometry kernel.
Reason: the closed form atan(t / (pi*r)) predicts the measured crease to 0.5 degrees and
proves a sine arch cannot be tangent at any radius. The defect was a wrong curve, so no
architecture change was warranted. The repository also already holds what a swept solid
would have to rediscover: `design_ops._paired_coordinates` gives exact index
correspondence between the inner and outer walls (i <-> i + vertex_count) and
`_ordered_boundary_ring` gives the sweep path.
Alternatives: A swept solid + Exact Boolean; B localized SDF; C hybrid patch; D external
kernel. All rejected as high irreversible risk (Boolean instability at hairpins, lost
provenance, voxel-resolution dependence, deployment constraints) against a problem that
a correct cross-section removes for free.
Clinical risk: none identified - vertex and face counts, trimline fidelity, delivered
radius, wall thickness and rim provenance are all bit-identical; only the cap's shape
changed. No shrinkage, no thickness loss, and no pre-compensation was needed, so the
deformation budget the brief authorised went unused for the primary fix.
Technical risk: the bullnose fills more of the same radius envelope than the sine arch
did, so concave overlap was left to the exact validator rather than argued from the
envelope; it reported zero on both the reference and hostile fixtures.
Rollback plan: revert `_rim_profile` and its two helpers; the guard, resampling and
projection commits are independent.
Files affected: `rigo_brace/operators/curve_build_ops.py` (`_rim_profile`,
`_cap_offsets`, `_cap_chord_budget`, `_soften_boundary_cusps`,
`_debur_projected_curve`); `tools/rimseamdbg.py`, `rimcornerdbg.py`, `rimwavedbg.py`,
`radiussweepdbg.py`, `rimshot.py`.
Tests required: rimresampletest, curvebuildtest, qaexclusiontest, thicknesstest,
referencetrimtest, qatest, selftest, importtest, customtrimseamtest, curvefinishtest,
trimqualitytest, slotbracetest - all green.

## Decision ID: DEC-0038
Date: 2026-07-27
Decision: Ship the upstream trimline patches P1 (display truth) and P2 (one
curvature-continuous clinical curve) independently, each behind its own numeric and
visual gate. Change the hostile-fixture contract in `rimresampletest` from "a
hand-mangled trimline must still build" to "it must be refused safely, with a specific
user-facing reason, no partial geometry, an intact prior brace, honest handle-model
metadata, and a refusal that re-solving repairs".
Reason: the generated trimline was C1, not one continuous curve — junction curvature
jumps measured 9.70x the within-segment variation, which is the "connected segments"
defect the orthotist reported. Handles derived from a point's own neighbours cannot do
better than C1; only a global solve couples the curvature entering a station to the
curvature leaving it. The closed non-uniform C2 system delivers 1.01 while staying
exactly representable in the existing Bezier form, so nothing downstream changes.
Alternatives measured and REJECTED — all of them either failed to fix the defect or
broke the build, and two produced a BETTER curve that still could not be built:
per-side Bessel tangents (9.91, no better than baseline — the disproof that any local
rule can work); handle clamps at 0.45 own-span (never binds), 0.45 min-span (reference
build fails), 0.35 and 0.25 (ratio 14.4 and 24.3, worse than the rule replaced);
centripetal parameterisation at alpha 0.7 and 0.5 (ratio 0.43 and 1.30 — the best
curves measured — reference build fails, 2 rim overlaps); sagitta-driven station
refinement at 1.2 and 0.6 mm (6 rim overlaps / outer-wall overlap).
Why rejected: the pattern "better curve, failed build" places the constraint in the
rim/offset stage rather than in the spline. Clamping in particular is self-defeating —
it truncates the handle lengths the C2 solution encodes, so it destroys the continuity
it is meant to protect.
Clinical risk: the trimline is smoother and its cut lands where it is drawn
(displayed-vs-built on the body 0.146 p95 / 0.685 max mm; opening corner drift
0.0000 mm). A directly hand-mangled curve now refuses instead of building — accepted by
the project owner because that curve is mangled outside the add-on's tools and the
refusal is safe, specific and repairable. Ordinary editor operations must still build,
and a brush-then-generate failure found during the battery was FIXED rather than
accepted under that narrowing.
Technical risk: C2 halves the trimline's self-clearance (23.3 -> 13.7 mm against a
3.0 mm cutter merge floor). A stamped fallback reverts a spline to the previous
tangent-continuous rule below 6 mm; it does not fire on any tested fixture and is proven
to engage by a test that raises its trigger.
Rollback plan: revert 3f1c561 and 2c3fe7d independently; each is self-contained, and P1
is provably display-only (identical corset hash before and after).
Files affected: `rigo_brace/operators/trimline_ops.py` (C2 solve, self-approach
fallback, staleness measurement, brush re-solve), `rigo_brace/operators/curve_build_ops.py`
(overlay from the cutter's projected path, stale-handle pre-flight),
`rigo_brace/core/__init__.py` and `ui/panels.py` (overlay toggle), `tools/trimgentest.py`
(new), `tools/trimshot.py` (new), `tools/curvebuildtest.py` and `tools/rimresampletest.py`
(contracts updated), P2 prototypes and diagnostics.
Tests required: trimgentest, rimresampletest, curvebuildtest, trimqualitytest,
trimbrushtest, trimbrushcanceltest, selftest, qatest, exporttest, thicknesstest,
referencetrimtest, customtrimseamtest, curvefinishtest — all green; front/side/oblique
captures unchanged in silhouette.
Follow-up: P3 (editor locality) and P4 (exact De Casteljau refine) remain. The offset-mold
self-intersection is scheduled as the next ARCHITECTURAL task (issues.md #37): it is the
shared constraint behind this decision's rejected variants and three previously capped
features, and trimline quality cannot rise further until it is fixed.

## Decision ID: DEC-0039
Date: 2026-07-27
Decision: The authoritative clinical trimline is a curve constrained to the GENERATED
BRACE INNER SURFACE, not to the patient body and not to a fixed mold assumption. Clearance
belongs to brace generation, not to the trimline, and the inner brace surface becomes a
persistent first-class authoring object rather than a transient artifact created inside
Generate. Recorded as issues.md #42; implementation blocked behind #37.
Reason: the trimline carried its own `SURFACE_OFFSET = 1.5 mm` standoff from the body,
independent of the user's clearance setting. Measured against the generated inner surface,
93.06 % of the evaluated curve is on the wrong side of it, 2060.1 mm of 2241 mm of
continuous arc penetrates, worst -7.468 mm, maximum float-away +8.580 mm. The deviation
has two independent components: a systematic -1.500 mm from the trimline's own offset
(visible cleanly in the control points, all at exactly -1.500 mm) and +/-7-8 mm of
inter-station sagitta on top.
Explicit guard: removing `SURFACE_OFFSET` alone is FORBIDDEN as a standalone change. It
corrects the constant bias only, leaves the sagitta failure intact, and would make every
control station read ~0.000 mm - i.e. it would look fixed while the evaluated curve still
cut through the surface. The two must land together.
Alternatives rejected: constraining the trimline to the BODY (the previous framing - it
makes the trimline define a clearance that is not the user's setting); keeping the inner
surface transient and conforming only at Generate time (the orthotist would author against
a surface that does not exist yet, and display, editing and cutting would again diverge);
a band constraint against the body (prototyped and rejected, issues.md #41).
Clinical risk: none from the decision itself, which changes no code. It removes a real
risk - the authored line and the cut line currently follow different surfaces, and the
trimline's standoff does not track the clearance the orthotist selected.
Technical risk: promoting the inner surface to persistent gives it the transactional and
staleness discipline the brace already has (requirements 10-12), touching
`_capture_generation_snapshot` / `_commit_generation` / `_restore_failed_generation` and
`core/signatures.py`. That is design work, not a rename.
Rollback plan: none needed yet; nothing is implemented.
Files affected (future): `trimline_ops.py` (remove SURFACE_OFFSET, conform to the inner
surface), `design_ops.py` (persistent inner surface + transactions), `curve_build_ops.py`
(consume the one authoritative path), `core/__init__.py` and `core/signatures.py`
(clearance property, sync hashes), `ui/panels.py`, plus the gate battery.
Tests required (future): the #42 acceptance gates, all measured against the generated
inner brace surface, against the baseline above.
Sequencing: blocked behind #37 (offset-mold self-intersection). The #41a opening policy -
hard protection only at semantic landmarks and intentional features, outward-only
correction between them - applies to this work, refined by requirement 9: protection pins
features, it does not license penetration between them.

## Decision ID: DEC-0040
Date: 2026-07-28
Decision: Trimline editing gets ONE shared transactional acceptance contract covering all
four modes (Smooth All, Smooth Arc, Straighten Arc, Blend Junction), not per-mode guards.
Sliders and the redo panel stay live preview with no verification and no build; a single
explicit **Apply & Verify** builds a hidden transactional candidate through the real
pipeline and either stamps the trimline VERIFIED for its signature or restores the previous
trimline bit-exactly. Implemented as `operators/trimverify_ops.py`.
Reason: the evidence rejected per-mode safety assumptions. Over seven arcs, a **1.03 mm**
Smooth Arc edit at (17,21) destroyed a brace that builds unedited, while a **60 mm**
Straighten elsewhere built fine; failure is neither monotonic in edit size nor confined to
one mode. Every mode can therefore hand the orthotist an accepted-looking trimline that only
fails later at Generate, and a guard written per mode would be the wrong shape of fix.
Verification runs the REAL pipeline - offset mold, projection, cut, boundary resample, rim,
wall join, manifold check - because a proxy check is precisely what let a 1.03 mm edit through.
Safety property: the candidate is built under `_CORSET_CANDIDATE_NAME`, never `CORSET_NAME`,
so a committed brace is untouched whichever way verification goes. That is what lets a
rejection honestly promise the last valid brace is unchanged.
Signature: the VERIFIED stamp is bound to the EVALUATED body (LM-0039), the raw trimline
controls, handles and handle types, the edit parameters, and every build-affecting setting
(`BUILD_SETTINGS`: thickness, offset, fairing, fillet radius and segments, transition width,
edge band, design style, trim top/bottom, opening width). Adding a build-affecting setting
without registering it there would let a stamp outlive its inputs, so that list is part of
the contract. Measured: changing thickness, fillet radius, offset or deforming the body all
flip the state to STALE; restoring them returns it to VERIFIED; any edit clears it outright.
Cost: one full build per Apply, which is why it is an explicit step and never runs on a
slider movement.
Sequencing: this is the product contract for #46. The architectural half - making valid local
edits less likely to produce rim overlaps at all - is separate and still open.

## Decision ID: DEC-0041
Date: 2026-07-29
Decision: rebuild the reusable correction pipeline on a continuous field + consistent
geometry state + validity-or-refusal commit (#48).
- Styles (schema v2) store BOTH the raw sample cloud (v1 compat) and a regular 2D
  tangent-frame grid resampled by IDW with a core plateau snapped to 1.0 and a hull
  taper; import evaluates the grid bilinearly (v1 entries: k-NN IDW with smooth taper).
- The style snapshot is captured at region BAKE time from UNdisplaced geometry
  (`rigo_style_src_<mask>` on the object); frame origin = the authoring anchor (circle
  seed / import cursor), frame normal = `_target_surface` at that anchor (identical
  derivation to the import side, else the projection shears on creased surfaces).
- Import and circle regions read the EVALUATED vertex positions (refuse with an
  actionable error if the modifier stack changes the vertex count); soft normal guard
  fades over [tol, 2·tol]; only the cursor-connected component survives; a soft geodesic
  trim (Dijkstra inside the footprint, limit 1.35× sample span, smooth fade) removes
  across-the-fold bleed.
- Painted feather is geodesic millimetres (multi-source Dijkstra from the boundary), not
  integer rings.
- Commit displaces analytically along geodesically FAIRED unit normals (|d| = amount×w
  exactly), then a bounded tangential-only repair loop clears inverted/degenerate/
  self-intersecting slivers (pre-existing scan defects baselined out). If repair cannot
  converge, commit REFUSES and restores bit-exactly, keeping the live preview.
Rejected: warn-and-keep-torn-geometry (violates state safety), remesh-as-default
(destroys clinical fidelity), reducing the requested amount (forbidden by task).
Cost: import+commit 1.9 s on the 45k-vert patient scan.

## DEC-0042 — 2026-08-14 — #48 hardening: reconciled single-source quality contract (Wave 0)

The council's evidence audit found the written contract and the executable gates had
drifted (test parity maxdd 0.25×amount vs written 2.5 mm; measured patient 2.70 mm
violated the written number while passing the test; IoU 0.75 vs 0.80; rev tolerance
scaled vs fixed; contract cited undo gates that did not exist). Decision, after
re-measuring every gate (hardening_plan_48.md, Item 1 table):

- All numeric thresholds now live ONLY in a fenced json block inside
  region_quality_contract.md; tools/quality_contract.py parses it and
  tools/regionqualtest.py takes every gate value from it; tools/contractcheck.py
  (plain python, no Blender) fails when the block is missing or incomplete.
  Divergence is now structurally impossible, not merely detected.
- Parity maxdd: the old single 2.5 mm number was undevised and measured-wrong. Replaced
  by a derived two-part gate: plateau (both w>0.9) maxdd ≤ 1.0 mm (measured 0.35–0.75);
  rim maxdd ≤ rim_shift_edges·h·1.5·amount/feather (lateral resampling shift on the
  profile's peak slope; measured 0.99–2.70 vs bounds 4.05–4.46). IoU tightened back to
  the contract's 0.80 (measured 0.856–0.891). Monotonicity tolerance restored to the
  contract's fixed 0.2 mm (passes — the 0.05×amount scaling was unnecessary).
- Oscillation bound clamped to min(analytic, amount): the unclamped analytic bound was
  vacuous (40.5 mm) on painted feather-10 regions.
- New gates: vertex/face count invariance; weight-decile profile monotonicity;
  live-topology-modifier import refusal (refuses + mutates nothing, message checked);
  float32/JSON serialization round-trip over 3 cycles; provenance stamp (git commit,
  date, Blender version) opens every result file.
- Scripted undo could NOT be gated: bpy.ops.ed.undo() polls false in timer context even
  with a full window/screen/area/region override — deferred to Wave 5 (needs a modal
  harness); the contract states this pending status explicitly instead of citing it.

Rider (item 8): region_ops member tests >= 1e-6 → > 0.0 (float32(1e-6) < 1e-6, proven);
now matches region_edit's membership. Full battery green after the change.

## DEC-0043 — 2026-08-15 — #48 Wave 1: whole-body validity (P0 blind spots closed)

The commit transaction now refuses what the footprint-local checks could not see:
- PREDICTIVE WALL CLEARANCE: before any mutation, rays from every core (w>0.5) vertex
  along its faired displacement direction against the body's static (non-footprint)
  faces; a hit within displacement + 3 mm refuses untouched. 3 mm is a GEOMETRIC
  collision floor (documented in the contract), not a clinical thickness rule.
  Ray-based (direction-aware) was chosen over nearest-distance clearance because
  same-sheet faces near the rim sit legitimately within any lateral margin — distance
  queries false-positive there, rays do not. Winding-number inside/outside was rejected
  (open/dirty scans), shrinkwrap clamping was rejected (silently alters the correction,
  violating valid-or-refuse).
- CROSS-SHEET NET: after commit+repair, footprint-vs-static BVH intersections
  (shared-vertex pairs excluded, pre-existing contacts baselined) must be zero, else
  bit-exact restore + refusal. Catches lateral folds into adjacent sheets that no core
  ray predicted.
- FOLD COLLAPSE: adjacent footprint faces whose shared-edge normals turn antiparallel
  (dot < -0.95) without being pre-creased (pre dot > -0.5) count as defects inside
  _repair_folds' loop; unrepaired folds refuse. Closes the flip test's <90°-rotation
  blind window on creased scans (hardendbg adjfold.foldover_creased).

Independence: the test oracle uses a whole-mesh BVH pairing and a dihedral-DEGREE
measurement (>160° new, was <120°) — different constructions from production; a unit
fixture cross-checks predicate vs oracle; the contract_constants gate pins the
production constants to the contract block.

Measured: oppwall_attack (30 mm into 24 mm body) now REFUSES with bit-exact restore
(was: FINISHED with 46 unseen crossings); oppwall_feasible (10 mm, same body) commits
clean — no over-refusal; every prior gated case unchanged (folds=0, new_cross=0);
patient import+commit 0.65 s -> 1.44 s (static BVH + cross-sheet nets), within the
2 s contract gate. Full battery green.

## DEC-0044 — 2026-08-15 — #48 Wave 2: snapshot anchors, mirror semantics, pairing metadata, surface-mm sizes

Implements the orthotist's three decisions (2026-08-15):

1. PAIRED STYLES: a style stores ONE region plus a `clinical` block that is never
   silently discarded — anatomical label, paired flag, counterpart kind/label/
   landmark/amount, counterpart center offset (mm), mirror provenance
   (`mirrored_from`), label_auto_mapped. Import restores the label, reports "part of
   a corrective pair — counterpart not imported"; the library dropdown and panel say
   so too.
2. MIRROR: rebuilt. The mirrored footprint is derived from the source's UNdisplaced
   bake-time snapshot through the importer's continuous-field path (chart u -> -u),
   anchored by projecting the reflected anchor onto the actual opposite surface —
   never sampled from displaced geometry, never nearest-vertex collapsed (was
   241 -> 57 unique verts; now 241 -> 312 coherent, holes 0). Sided landmarks
   auto-map (AXILLA_L <-> AXILLA_R etc.), flagged label_auto_mapped; midline labels
   untouched; `mirrored_from` records provenance. On asymmetric bodies where the
   exact reflection lies off-surface (measured 54 mm at the flank patch —
   tools/mirrordbg.py) the operator warns and anchors to the closest real surface;
   regiontest's invariant is now footprint-coherence-around-anchor (5.2 mm), not
   exact numeric reflection.
3. SIZE SEMANTICS: surface (geodesic) mm are authoritative. Snapshots store
   `max_geodesic_mm` over the effective (w>0.05) footprint from an ON-PAD anchor
   (strong-member vertex nearest the centroid — a horseshoe's raw centroid sits in
   its gap and shifted imports 40 mm); the import trim limit is that intrinsic size
   x 1.15 (chord fallback for legacy entries); imports WARN beyond 12% realized-size
   deviation and never silently resize; region.radius_mm reports surface mm.
   Measured chord-vs-geodesic divergence: +4.9% on R=60 mm, +4.8% on R=95 mm
   cylinders for a ~52 mm effective footprint (gated at 12%).

Also: painted add/update snapshots now use EVALUATED coords (last mixed-state path),
with the region's own preview modifier excluded during update snapshots; the field
core plateau clamp moved 0.99 -> 0.95 so the full amount survives a SECOND resample
(mirror) — measured side effect: import parity IoU improved 0.856 -> 0.977 (scan),
0.861 -> 0.909 (patient), rms down, mirror core 90.1%.

Deferred within scope, honestly: chart fold refusal is Wave 4; the exp-map chart
stays DEFERRED. Battery green (regionqualtest incl. new mirror/pairing/horseshoe/
size gates, regiontest, regionstyletest, regionuitest, selftest).

## DEC-0045 — 2026-08-15 — #49 steps 3-4: transactional refined commit (two-mode)

Production (region_ops):
- The commit is now a TEMP-MESH TRANSACTION: me.copy() carries every mask/
  attribute/selection; refinement + displacement + repair + all validators run on
  the copy; ONE atomic in-place write (bmesh) on full validity; any failure
  discards the copy — the patient mesh is untouched by construction (replaces the
  per-index rollback, which cannot undo topology).
- ADAPTIVE LOCAL REFINEMENT before displacement: per-edge criterion — an edge
  splits only when its predicted post-displacement length exceeds 1.4× the
  sampling its own local slope requires (rows >= 2·atan(g)/0.25 rad across the
  wall arc); already-dense meshes no-op by construction (gated); genuinely sharp
  creases (>72°) never refine (pressing walls physically collide there); new-vertex
  weights re-evaluated via smooth 3D IDW over the surrounding ORIGINAL authored
  weights (parent interpolation provably keeps the staircase; chart-space fields
  disagree with authored weights at creases — both measured); quality passes:
  short-edge collapse (weld new→original), max-min-angle flips (deterministic
  input order), cap rotation, sliver purge, tangential relax of new verts only.
- TWO-MODE SEMANTICS: refined attempt first; if repair cannot converge, fall back
  to the FULLY unrefined commit (pre-#49 bit-behaviour) with a visible WARNING;
  refuse only if that also fails. No partial refinement, no density seams.
- Audit items landed: B4 (stale Corset Base deleted at commit), B6 (refuse while
  Bend/Twist/Stretch live), B7 (verify counters cleared), shape-key refusal,
  provenance (region.refined_added / refined_edge_mm + report note).

Measured: painted 15/10 staircase fixture with refinement engaged: max edge
12.9→4.9-6.1 mm, stretch edges >1.5× 128-240→0, aspect max 45.7→7.2, smooth-
after-commit worsened-preexisting spikes 8→0-1 — the user's staircase/spike
defect is eliminated wherever refinement engages. KNOWN LIMITATION (honest):
on the wrinkled sample scan, steep painted walls currently take the warned
fallback (1-2 seam slivers collapse under fairing-direction divergence and the
repair refuses them); the patient scan, flats, decimated and dense targets
refine or no-op cleanly. Next (recorded in issues.md): in-transaction
post-displacement sliver dissolution to unlock refinement on wrinkled walls.

Evidence layer: BVH-vs-index oracle mode split; refined_declared gate pins the
vertex delta to provenance; w49 gates (smooth-after-commit workflow, refinement
determinism bit-equal, overlap-mask field preservation, dense no-op); regiontest
perf gate aligned to the contract's 3.0 s (a fallback runs the transaction
twice, measured 2.83 s). Full battery green.

## DEC-0046 (2026-08-15) - #49 closed: seam-sliver dissolution, repair escalation, wall-sampling gate, downstream chain green

Context: DEC-0045 left one honest limitation (wrinkled painted walls fell back
warned on 1-2 refinement-seam slivers) and step 5 (downstream validation) open.
User directive: dissolve only the refinement-created slivers, inside the
transaction, without moving originals or altering the authored field; keep
refusal when unsafe; then run refined patient -> trimline -> brace -> QA ->
export and do not close #49 until that chain is green on a refined patient.

Decisions (all measured via tools/refinedbg.py before shipping):
- REPAIR ESCALATION: tangential-only until the defect set stalls unchanged for
  3 iterations; then ONLY the defective faces' own NEW vertices (never ring,
  never originals) relax with the normal component. A new vertex carries no
  authored amount; the clinical promise (originals keep exact authored
  displacement) is untouched by construction.
- SLIVER PREDICATE (refined commits only): a refinement-born triangle
  compressed below 0.12x the sampling target post-displacement (measured
  0.24 mm vs 2.38 mm target) is a defect - its normal is numerically
  meaningless and must not ship. Caught two shipping warts the flip test
  missed (one oracle-inverted 0.25 mm-edge sliver).
- SEAM-SLIVER DISSOLUTION: when repair leaves ONLY refinement-born slivers
  (every defective face touches a new vertex, <=4 faces), re-run the
  bit-deterministic refinement on a fresh working copy with those vertices
  PLUS their one-ring new neighbourhood welded onto surviving neighbours
  (nearest original preferred) BEFORE displacement; full pipeline re-runs.
  Exact-vertex dissolve measured insufficient (the fold migrates to the
  adjacent seam sliver); one-ring converges (paint15: +168 verts, no warning,
  validity/feather/amount/smooth all green, inverted 0, rev 0).
- WALL-SAMPLING GATE replaces the stretch-ratio gates: the ratio is
  scale-invariant in the authored steepness (splitting halves L and dw alike;
  sqrt(1+g^2) = 2.46 intrinsic for a legitimate 15/10 profile), so a ratio
  threshold gates the orthotist's profile, not the mesh. The enforced gate is
  post-commit LENGTH of surviving high-gradient (g>=0.35) original edges vs
  the contract sampling requirement, margin 1.3, sharp >60-degree pre-creases
  exempt. Measured populations: healthy 0 violations (exceed <=1.14x);
  dissolved seams <=4 violations at <=2.07x (bounded by the plan's own
  <=4-face bound); the identical wall committed unrefined (defect class):
  82 violations at 3.12x - 20x count separation. Gate <=4.
- REV ORACLE on index-exact original displacements in every mode: the BVH
  signed-distance reference misreads wrinkled zones by up to 2.1 mm (measured
  w 0.975/1.000 edge, exact d -14.61/-15.00 read as -13.32/-12.93) and must
  not vote on 0.2 mm-tolerance monotonicity. New-vertex profile stays covered
  by osc/decile/core on the BVH oracle. aspect_p95_factor recalibrated to 2.5
  (heavy wrinkle-zone refinement measures 2.03-2.09x pre; splitting wrinkled
  triangles is intrinsically anisotropic).
- STEP 5 DOWNSTREAM (tools/downstreamtest.py, comparative-control design):
  refined A-model patient (+99) -> trimline -> corset (121k faces) -> QA
  (manifold 0/0, selfx 0, min wall 3.41 mm, coverage 1.00) -> export: GREEN.
  No-op chain green. Oppwall refusal leaves a byte-identical scan whose
  downstream failure signature equals the untouched control exactly.
  PRE-EXISTING generator failures surfaced (designtest RED at baseline with
  zero regions: trim-rim non-manifold; the wrinkled sample scan cannot carry
  any liner offset; spine-groove outer-wall overlap) - recorded as #50, NOT
  #49 regressions (generator code untouched since #37/#45/#46). The test
  gates corrections as never-worse-than-control and auto-tightens to
  all-green when #50 is fixed.

Full battery green: regionqualtest (incl. paint15.refined_commit,
refined_declared, w49 gates), regiontest, regionstyletest, regionuitest,
selftest, downstreamtest.
