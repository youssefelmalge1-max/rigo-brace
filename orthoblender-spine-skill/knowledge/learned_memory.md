# Learned Memory

Lessons captured from development sessions. Newest at bottom.

## Lesson ID: LM-0001
Date: 2026-06-13
Source: scan_ops apply-units bug (user report: "model disappears")
Observation: An mm/cm scan imports ~hundreds of BU tall; scaling ×0.001 shrinks it correctly, but the viewport stayed zoomed for the giant size, so the correct-size model was sub-pixel and looked deleted.
Underlying principle: Object scale changes do not move the camera; large unit conversions need an explicit re-frame.
Clinical implication: Orthotist must trust units are applied; a vanished model erodes confidence.
Blender / geometry implication: After bulk rescale, call view3d.view_selected per VIEW_3D region; guard double-apply (refuse if already body-sized < 3 m).
Reusable feature: `_frame_object`, dimension-based "already scaled" guard.
Template update needed: no.
Test case needed: yes — tools/applyunitstest.py.
Risk: low.
Confidence: high.
Next action: done.

## Lesson ID: LM-0002
Date: 2026-06-13
Source: select_ops paint-select persistence + circle-select mode
Observation: (a) Paint Area deselected everything each press; (b) Blender circle-select defaults to "Set" mode, replacing the selection on every new drag.
Underlying principle: Only wipe the whole-mesh state (post-import all-selected); force the circle tool to ADD so strokes accumulate.
Clinical implication: Painting a pressure region in multiple strokes must accumulate, not reset.
Blender / geometry implication: Detect "all faces selected" before deselect; `tool.operator_properties("view3d.select_circle").mode = "ADD"`.
Reusable feature: accumulate-region paint pattern (basis for the P0 area-select feature).
Template update needed: no.
Test case needed: yes — paintkeeptest.py, painttooltest.py.
Risk: low.
Confidence: high.
Next action: reuse for area-select → contour-line carve.

## Lesson ID: LM-0003
Date: 2026-06-13
Source: deform_ops Bend destroying the torso
Observation: Simple Deform BEND wraps the mesh AROUND deform_axis. With axis Z the bend angle spread across shoulder width (X) → torso rolled up. Empirically (tools/bendexp.py) axis Y tips the top sideways in the coronal plane with the base fixed.
Underlying principle: BEND axis = the bar the mesh wraps around; gradient runs along Z for axis X/Y. For a standing torso, coronal bend = axis Y, sagittal = axis X. No 90° empty-rotation needed (that trick is pre-2.79 folklore).
Clinical implication: Coronal side-bend is the scoliosis correction; must pivot from the pelvis.
Blender / geometry implication: deform_axis = "Y" for BEND, "Z" for TWIST/STRETCH.
Reusable feature: empirical axis table in bendexp.py.
Template update needed: no.
Test case needed: yes — bendtest.py.
Risk: medium (clinical correctness of direction) — exposed via slider, orthotist judges.
Confidence: high (source-code-table confirmed + empirical).
Next action: done; consider Left/Right toggle + sagittal option later.

## Lesson ID: LM-0004
Date: 2026-06-13
Source: deform_ops Stretch tapering the body
Observation: Simple Deform STRETCH along Z also tapers X/Y (girth shrinks) unless locked.
Underlying principle: lock_x/lock_y confine STRETCH to pure lengthening.
Clinical implication: Elongation must not silently reduce girth.
Blender / geometry implication: set mod.lock_x = mod.lock_y = True for STRETCH.
Reusable feature: —.
Template update needed: no.
Test case needed: yes — stretchtest.py (Z-only, base planted).
Risk: low.
Confidence: high.
Next action: done.

## Lesson ID: LM-0005
Date: 2026-06-13
Source: deform range planes (LeoSpinal white/blue lines)
Observation: Numeric From/To fields were not the LeoSpinal feel; user wants visible, draggable planes on the model. Thin curve rings were unclickable; the 2500 mm field cap clamped planes to the feet on unscaled scans.
Underlying principle: Represent each plane as a filled semi-transparent disc (big click target) whose world-Z drives the modifier limits + origin via drivers; freeze ring-driven values before modifier_apply to avoid "Invalid driver" warnings.
Clinical implication: Direct manipulation of correction zone boundaries matches clinical software.
Blender / geometry implication: `_make_plane_disc`, `_drive_range` (SCRIPTED drivers, min/max so drag order is swap-safe), `_show_object_colors`; warn when model > 3 m across (unscaled).
Reusable feature: draggable-handle + driver mechanism — directly reusable for P0 contour lines.
Template update needed: no.
Test case needed: yes — planestest.py.
Risk: low.
Confidence: high.
Next action: reuse driver/handle pattern for area-select contour control points.

## Lesson ID: LM-0006
Date: 2026-06-13
Source: pad shape library (pad_ops.py, pad_library.py)
Observation: Bezier AUTO handle positions are (0,0,0) on the raw datablock — only computed during depsgraph evaluation. Sampling the raw curve bent every segment toward the object origin. Draping rays that graze the silhouette land far down the torso.
Underlying principle: Read the EVALUATED curve (`obj.evaluated_get(depsgraph)`) for handle-accurate boundary sampling; bound drape-ray travel (max_jump) and fall back to closest_point_on_mesh.
Clinical implication: Pads must drape on the surface and apply where drawn.
Blender / geometry implication: evaluated-curve sampling; KDTree distance-to-boundary + smoothstep feather; reject opposite hollow-shell wall via vertex-normal·plane-normal > 0.
Reusable feature: `_drape_point`, `_sample_pad_boundary`, `_inside_2d`, feather + back-wall filter — the apply core for P0 carve/add.
Template update needed: no.
Test case needed: yes — padtest.py, padshapetest.py.
Risk: low–medium (curvature > ~90° wrap unsupported; clinical range OK).
Confidence: high.
Next action: reuse apply core for area-select carve.

## Lesson ID: LM-0007
Date: 2026-06-13
Source: dynamic EnumProperty for the pad library
Observation: Returning a freshly built items list each call corrupts strings (Blender stores enum item strings by reference; they must outlive the call).
Underlying principle: Cache the items list at module level; rebuild only on a version bump; enums are stored by index in .blend → keep ordering append-only.
Clinical implication: Library drop-down must be stable across saves.
Blender / geometry implication: `_ENUM_CACHE` + `_ENUM_CACHE_VERSION` in pad_library.py; no file IO at register().
Reusable feature: the cached-enum pattern for any future library (templates, components).
Template update needed: no.
Test case needed: covered by padshapetest.py (record→reselect).
Risk: low.
Confidence: high.
Next action: apply same pattern to future template/component libraries.

## Lesson ID: LM-0008
Date: 2026-06-13
Source: Audit of uFit (D:\ufit-blender-master, GPL-3.0, Ugani) and WASP-Med (D:\WASP-Med-master, GPL-2+-, WASP) — both GPL-compatible with rigo_brace.
Observation: Both independently implement the orthotics primitives we are building, via proven, reusable methods:
  - uFit: paint a region (vertex-color attribute) → move verts along normals → grow+smooth boundary; a CIRCULAR variant uses proportional editing from the center vertex (radius = distance to furthest vert, NORMAL orient) for a smooth dome. Plus live circumference remeasure + custom thickness over the painted region.
  - WASP: rotate_sections rotates lattice w-layers progressively (multi-section DEROTATION along the spine); weight_thickness builds VARIABLE wall thickness from a weight-paint via 24 iso-contour cuts; check_differences shows a before/after deviation map.
Underlying principle: region-paint→normal-displace with grow+smooth feather is the standard "area sculpt by selection" technique; lattice-per-layer rotation is standard derotation; weight/vertex paint drives gradient thickness.
Clinical implication: derotation should be multi-section, not single-axis; reinforcement = gradient thickness; a deviation map is valuable QA.
Blender / geometry implication: our select_ops (Edit-mode face select + shrink_fatten + smooth) is the equivalent of uFit's region push/pull — we are on the right track; adopt the circular proportional-edit dome and grow-then-smooth feather; port WASP rotate_sections (update 2.91→5.0 transform calls) and weight_thickness for MVP4.
Reusable feature: area-carve (P0), multi-section derotation (MVP2), variable thickness (MVP4), deviation-map QA (MVP5), measurements module.
Template update needed: no.
Test case needed: yes — areatest.py (P0), later derotationtest, thicknesstest.
Risk: license discipline — any PORTED unit needs a provenance entry + preserved GPL header (PROV-0004/0005 are audit-only).
Confidence: high.
Next action: implement P0 area-carve reusing our select_ops + uFit's grow+smooth/circular-dome technique; defer WASP ports to their MVP stages.

## Lesson ID: LM-0009
Date: 2026-06-13
Source: User walkthrough of uFit 2.2.2 screens — explicit feature adoption list (10 items).
Observation: User wants the brace add-on to follow uFit's full workflow UX: persistent shell (View/View-Modes, Checkpoints+Rollback, Assistance image+text, Progress, Annotation + top tools), and steps import → clean(select Shift+RightClick to add) → verify-clean → quad-view align → circumferences(at spine levels) → measurable highlight push/pull sculpt → manual trim line (edit point: RightClick,G,RightClick; X-ray; flared width) → part-selection → scale → unified thickness → flare %.
Underlying principle: a guided, checkpointed, beginner-assisted workflow lowers the skill floor for orthotists; "highlight a region then push/pull by mm" is the central shaping metaphor (matches our select_ops + uFit push_pull_region).
Clinical implication: checkpoints map to anatomical reference stages; circumferences at GT/waist/below-chest/nipple/armpit levels are the clinical girth measures; flared trim edge = patient safety.
Blender / geometry implication: build a workflow shell (panel sections + step state + assistance images) over existing operators; spine circumferences keyed to LANDMARKS; trimline X-ray + flared width extend the existing outline tool.
Reusable feature: the whole Requirements v1 set (knowledge/requirements_v1.md).
Template update needed: requirements_v1.md created; feature_backlog + roadmap + DEC-0008 updated.
Test case needed: per-module tests as each is built.
Risk: scope — large UI restructure; phase it (P0 sculpt first, then shell). License: port uFit/WASP units only with provenance + GPL header.
Confidence: high (explicit user spec).
Next action: confirm UI scope (replace vs layer), then build P0 measurable push/pull sculpt.

## Lesson ID: LM-0010
Date: 2026-06-17
Source: Patch 2 — Workflow shell + design history (history_ops.py), porting WASP wm_next/wm_back.
Observation: WASP's design history = each major step is a frozen object version named NN_<patient>_<stage> in a per-patient collection; Next duplicates the current work into a new version and hides the old, Back/Rollback reveal saved versions. The visible/active version is the editable one. This is the in-outliner history the user prefers over uFit's cloud storage.
Underlying principle: non-destructive stage snapshots via object duplication + visibility, tracked by custom props (rigo_patient, rigo_stage) — simpler and more transparent than modifier stacks or saved .blend states.
Clinical implication: orthotist can roll back to any stage; history is visible/auditable.
Blender / geometry implication: obj.copy()+data.copy(); collection link/unlink; hide_set/select_set; drop forward versions on re-Next to rebuild history; keep scan_object pointer following the active version. Built additively — existing wizard (RIGO_PT_main) untouched, so selftest stays green.
Reusable feature: the stage/version model is the backbone for all later stages (Clean/Shape/Trim/Shell snapshots).
Template update needed: requirements_v1 + roadmap + DEC-0011 + PROV-0006 updated.
Test case needed: done — tools/historytest.py (next/back/rollback/rebuild).
Risk: mesh-copy memory at many stages — mitigated by major-stage granularity; license — WASP port logged PROV-0006, attribution in docstring.
Confidence: high.
Next action: Patch 3 (Clean: center + auto-remesh + verify-clean), snapshotting via this shell.

## Lesson ID: LM-0011
Date: 2026-06-17
Source: Patch 3 Clean stage (clean_ops.py) + the noise-removal pass that preceded it.
Observation: The "Brace Sample.stl" is already watertight (boundary edges = 0) — so a
verify/fill test on the raw sample can't exercise hole-detection; you must poke a hole
(bmesh remove a face) to test it. Auto-Remesh already existed as `rigo.remesh` (voxel) —
the WASP "Auto-Remesh" ask was really about exposing a Detail control, not new code.
Underlying principle: before adding an operator, check if the capability already exists
and just needs better surfacing (avoids the redundancy the user dislikes). Verify-clean =
bmesh manifold/boundary/loose counts + select_non_manifold; stash counts as custom props so
the panel + tests can read them.
Clinical implication: the "verify before closing the mesh" gate catches holes/non-manifold
that would break printing.
Blender / geometry implication: voxel REMESH yields a watertight manifold (boundary 0) —
good as the canonical "auto-remesh"; center via origin_set BOUNDS + location 0 (distinct
from drop-to-floor). Tests that need a defect must create it deterministically.
Reusable feature: verify_clean counts/props feed the future Export QA gate (Patch 8).
Template update needed: roadmap + DEC-0013 + PROV-0007 updated.
Test case needed: done — tools/cleantest.py (center→poke hole→detect→fill→remesh watertight).
Risk: low. Confidence: high.
Next action: Patch 4 — combined Guided(mm)+Free sculpt (the core shaping tool).

## Lesson ID: LM-0012
Date: 2026-07-03
Source: Issue-fix wave (DEC-0015) after the first full 70-operator live MCP audit.
Observation: The audit found "12 issues"; code + live re-verify reduced that to 3 real
ones (remold 5.0 API crash, history ignoring brace_patient, black captures). The rest
were artifacts of HOW the audit measured (see ERR-0009): scripts can't see self.report,
applied modifiers are invisible to live-modifier checks, one count ran after a clear op,
dynamic enums introspect empty. The black captures stopped reproducing once the remold
crash was fixed — an operator raising mid-execute can corrupt UI/GPU state, so fix
crashes before chasing downstream weirdness.
Underlying principle: verify-before-fixing is as important as verify-after-fixing; an
audit finding is a hypothesis, and the cheapest disproof is reading the source.
Blender / geometry implication: Blender 5.0 moved unified_paint_settings to
tool_settings.sculpt (per-mode Paint); ts.sculpt exists only after first Sculpt entry —
enter the mode before touching its settings.
Clinical implication: design history is now keyed to the orthotist's typed patient name
(versions `NN_<patient>_<STAGE>`), matching how records are actually filed.
Reusable feature: remoldtest.py numeric-gate pattern (exact slider==setting equality);
capture-brightness sanity check documented in docs/blender_mcp_setup.md.
Template update needed: issues.md rewritten as the living status board; DEC-0015,
ERR-0008/0009 logged.
Test case needed: done — remoldtest.py PASS, historytest.py (patient + fallback) PASS.
Risk: low. Confidence: high.
Next action: Patch 4 — combined Guided(mm)+Free sculpt on the CorrectionRegion model.

## Lesson ID: LM-0013
Date: 2026-07-03
Source: Patch 4a — CorrectionRegion Guided Sculpt (region_ops.py, DEC-0017).
Observation: Making the correction a DATA OBJECT (weights baked into a vertex group at
Add time) made the mm gate trivially exact: apply is just co += dir * mm * weight, so the
test measured 0.0000 mm error and 10.000 mm max displacement. The feather is topological
(BFS rings from the selection boundary, mm converted via mean selected edge length,
normalized so the core always reaches weight 1.0) — resolution-independent and exact at
any mesh density. Quad-remeshed surface (DEC-0016) applies in 0.01 s.
Underlying principle: bake the falloff once into a mask, keep apply linear — determinism,
undoability and testability all follow from that separation.
Blender / geometry implication: vertex groups are the right persistence for region masks
(survive edits, copy with the object into history versions); KDTree nearest-vertex is a
good-enough mirror map on symmetric anatomy, degrades gracefully on asymmetric.
Clinical implication: every region carries requires_review=True; pressure/expansion
coupling is explicit (opposing_region), matching the Rigo 3-point principle.
Reusable feature: the ring-feather weight baker can serve the future parametric
ventilation (Patch 7) and trim-flare regions.
Template update needed: DEC-0017, roadmap. Test case: tools/regiontest.py PASS.
Risk: low. Confidence: high.
Next action: Patch 4b — circular quick-region, X-ray overlay transforms, fold remold.

## Lesson ID: LM-0014
Date: 2026-07-11
Source: repository-wide workflow and test-evidence audit.
Observation: the visible five-tab tool workflow (`active_tab`) and nine-stage design
history (`brace_stage`) are independent state machines with separate Next/Back
operators. History snapshots only the preferred `scan_object`, so a passing mesh-copy
test does not prove restoration of the multi-object brace design. The repository has
91 operators, while 34 have no direct functional-test reference; some are modal/UI
operations and need an explicit GUI evidence category rather than registration alone.
Underlying principle: one user workflow needs one canonical state model; checkpoint
scope must match the full project aggregate, and test claims must state their evidence
level.
Clinical implication: an apparently successful rollback can omit clinically relevant
trimlines, pads, shell, landmarks, or reference state unless they are owned and restored
as part of the same patient project.
Blender / geometry implication: copying one mesh object is not a scene/project snapshot;
related objects and references need explicit ownership metadata plus save/reopen tests.
Reusable feature: the existing preview-icon loader can support an icon-led UI after the
canonical stages are chosen.
Template update needed: none yet; decision map created at project root.
Test case needed: complete-project checkpoint round trip, including `.blend` reopen.
Risk: high for workflow reliability; no production code changed during this audit.
Confidence: high.
Next action: resolve ticket #1 in `PROJECT_AUDIT_DECISION_MAP.md`.

## Lesson ID: LM-0015
Date: 2026-07-11
Source: DEC-0026 canonical workflow implementation and live Blender verification.
Observation: deriving compatibility stage metadata from the canonical five tool stages
eliminates list drift while allowing the legacy snapshot module to remain hidden during
migration. Blender scripted operator calls raise `RuntimeError` when an operator reports
`ERROR`, even when its implementation returns `CANCELLED`; regression tests must verify
the reported failure without misclassifying that API behavior as a product crash.
Underlying principle: one observable workflow has one state owner; remove unreliable UI
promises before rebuilding their persistence model.
Clinical implication: users cannot mistake a scan-only rollback for restoration of the
complete clinical design.
Blender / geometry implication: no geometry changed; fresh install plus real GUI tests
are required because the app template runs the installed extension copy.
Reusable feature: `workflowtest.py` verifies direct stage selection, Next/Back boundaries,
invalid-stage rejection and absence of duplicate state.
Template update needed: none.
Test case needed: done — workflowtest PASS, selftest ALL_PASS, legacy historytest PASS.
Risk: low. Confidence: high.
Next action: decision-map ticket #2, icon-led interface prototype.

## Lesson ID: LM-0016
Date: 2026-07-11
Source: pressure/expansion feature research, code audit, user screenshot, and current
pad-library JSON.
Observation: all clinical-named built-ins are identical circles; the user's saved
`ILIAC_CREST_PRESSURE_L` can even carry `kind=EXPANSION` because favourites may change
the effect independently of the label. Curve handles are not persisted, Size does not
resize a placed outline, and repeated Apply compounds the mesh deformation.
Underlying principle: a clinical label must not imply validated geometry; reusable
templates preserve exact authored shape, while patient placement remains separate data.
Clinical implication: Rigo contact and expansion regions are curve-pattern-specific in
level, boundary, orientation and counterforce relationship; orthotist review is required.
Blender / geometry implication: editable curves need points plus handles, and preview
must rebuild from an immutable baseline before an explicit commit.
Reusable feature: existing raycast/drape, curve editing and JSON library code can be
migrated rather than discarded.
Template update needed: pressure/expansion feature spec created in docs.
Test case needed: schema migration, curve fidelity, idempotent preview, commit/undo and
save/reopen.
Risk: high if clinical-named circle presets remain. Confidence: high.
Next action: obtain approval decisions in the feature spec, then implement sequence 1.

## Lesson ID: LM-0017
Date: 2026-07-11
Source: DEC-0027 pressure-library schema-v2 migration.
Observation: a migration can preserve the orthotist's exact v1 JSON while removing false
clinical authority: back up first, retain actual values, attach provenance/fidelity flags,
and introduce neutral primitives under new stable ids. Existing geometry tests needed one
behavioral correction because a valid closed rounded rectangle uses eight points, not the
old circle's arbitrary twelve.
Underlying principle: migrations preserve data and disclose uncertainty; tests assert
geometric behavior rather than the previous implementation's point count.
Clinical implication: old named circles are accessible but cannot be mistaken for
validated iliac/trochanteric designs.
Blender / geometry implication: v1 AUTO-handle shapes remain reproducible at their old
fidelity, while v2 reserves exact handles for the approved authoring step.
Reusable feature: isolated real-filesystem migration fixture with backup-hash and repeat
load gates.
Template update needed: pressure feature spec and decision map updated.
Test case needed: done — padlibrarytest plus full pad regressions.
Risk: low after backup. Confidence: high.
Next action: implement click-to-draw closed Boundary and exact point/handle persistence.

## Lesson ID: LM-0018
Date: 2026-07-11
Source: user rejection of the Pressure/Expansion handoff and live visual reproduction.
Observation: migration tests and legacy one-time deformation tests were green, but the
approved end-user workflow did not exist. The visual test still produced a generic oval;
there was no Draw Boundary, exact handle save, deterministic preview, or explicit commit.
Reporting the infrastructure step without a user-check guide made the result sound more
complete than it was. The visual script also exposed a timer callback contract warning,
which was fixed and rerun cleanly.
Underlying principle: test evidence must match the user's workflow claim, not a lower
implementation layer.
Clinical implication: do not invite orthotist validation until the full intended sequence
is operable; label partial infrastructure `NOT READY`.
Blender / geometry implication: every feature requires a fresh-install UI sequence plus
visual inspection in addition to numeric/unit tests.
Reusable feature: mandatory user verification handoff added to qa_test_protocol.md.
Template update needed: Pressure spec and decision map now state NOT READY.
Test case needed: future boundary-authoring end-to-end test and user guide.
Risk: communication/validation risk corrected. Confidence: high.
Next action: implement and visually test Draw Closed Boundary before the next handoff.

## Lesson ID: LM-0019
Date: 2026-07-11
Source: Pressure Boundary implementation, failed integration rerun, and corrected rerun.
Observation: adding a viewport-only `poll()` blocked the scripted execution fallback and
was caught only when the full suite was rerun after the guard pass. Moving the context
check into `invoke()` preserved interactive safety while allowing deterministic execute
tests. Exact evaluated handles can round-trip through normalized schema-v2 geometry with
error below 7e-08.
Underlying principle: interactive and scripted Blender operator paths share finalization
but have different context contracts; both need independent gates.
Clinical implication: the orthotist can now author and reuse boundaries, but must not use
legacy Apply as if deterministic preview were complete.
Blender / geometry implication: save evaluated AUTO handles, respawn them as FREE handles,
and drape them with their control points to preserve editable curvature.
Reusable feature: mandatory user-check guide linked to a concrete test result.
Template update needed: user_check_pressure_boundary.md created.
Test case needed: done for author/save/regenerate; Preview/Cancel/Commit remains.
Risk: medium until manual click workflow is confirmed. Confidence: high in persistence.
Next action: user check, then implement deterministic Preview/Cancel/Commit.

## Lesson ID: LM-0020
Date: 2026-07-12
Source: committed CorrectionRegion style save/import implementation.
Observation: portable selection styles cannot store vertex indices. Surface-local
millimetre samples plus weights, an orientation frame and sampling tolerance reproduce
the correction on a target with different topology while retaining Edit Selection.
Underlying principle: persist geometric intent in a topology-independent local frame.
Clinical implication: a clinic can reuse its authored form, but location and amount are
reviewed on every patient.
Blender / geometry implication: nearest 2D sample transfer is bounded by normal-distance
and adapts its radius to target edge spacing; local-normal preview remains non-destructive.
Reusable feature: per-PC atomic JSON library and cached dynamic enum pattern.
Template update needed: pressure feature specification and user guide updated.
Test case needed: done — regionstyletest, including pre-commit rejection, disk reload,
different topology, edit/update, exact 8.000 mm preview/commit and deletion.
Risk: large highly curved templates can distort. Confidence: high for local regions.
Next action: manual orthotist UI check; later add interactive scale/rotation.

## Lesson ID: LM-0021
Date: 2026-07-12
Source: LeoSpinal transcript research and three-ring deformation tests.
Observation: three-loop control means selecting one adjacent interval, not applying two
independent deformations. Simple Deform limits alone still carry geometry above the
interval. When the user means world-fixed outside zones, Twist/Stretch also require a
smooth live vertex mask; Bend can retain the approved rigid continuation.
Underlying principle: modifier limits define where deformation accumulates, while a
vertex mask defines which vertices may move at all.
Clinical implication: the orthotist can modify lower or upper torso segments without
distorting the other segment's shape.
Blender / geometry implication: localized Twist/Stretch combine ring-driven limits with
a 5% smooth mask rebuilt by a guarded depsgraph handler. Stretch gain is derived from the
actual height/weight profile, so 40 mm input evaluates to 40.00 mm peak movement.
Reusable feature: selectable pair among three driver-controlled section handles.
Template update needed: deformation research and user guide created.
Test case needed: done — segmentdeformtest plus planestest/bendtest/stretchtest.
Risk: mask rebuilding on extremely dense meshes needs later performance profiling.
Confidence: high for LeoSpinal-documented behavior; not enough public data to claim exact
Rodin4D algorithm parity.
Next action: technical work closed by user validation. Defer icons, names, and ring
appearance to the interface-polish ticket; preserve all geometry regression gates.

## Lesson ID: LM-0022
Date: 2026-07-12
Source: user-reported export, Full Screen and Box Erase failures plus installed-copy tests.
Observation: three operators returned `FINISHED` while their user-visible contracts were
still wrong: export targeted selection, fullscreen did not visibly change a one-area
layout, and box selection stopped at the visible surface.
Underlying principle: a functional gate must assert the artifact or state named by the
user, not merely successful operator dispatch.
Clinical implication: final brace export is separated from scan import and cannot
silently include patient-scan/helper geometry; cleanup cuts now represent the complete
view-direction volume chosen by the orthotist.
Blender / geometry implication: STL export must isolate `Rigo Corset`; an application
focused view should control individual regions so add-on UI remains usable; through-depth
Edit selection requires X-ray and explicit mode-scoped delete/finish controls.
Reusable feature: artifact re-import/dimension gate, exact region-visibility gate, and
six-face select-and-delete fixture.
Template update needed: Step 1 text is import-only; Step 5 ends with Final Export.
Test case needed: done — exporttest, erasetest, strengthened viewtest plus workflow,
design and registration regressions.
Risk: the orthotist must visually verify the chosen box before clicking Delete.
Confidence: high.
Next action: user acceptance check using the supplied click guide.

## Lesson ID: LM-0023
Date: 2026-07-12
Source: deep generator/trimline research, source audit and A-fixture baseline.
Observation: the current generator's spikes are deterministic consequences of deleting
whole triangles by face center and smoothing afterward. Auto trims also bypass the opening.
A correct trim is one continuous perimeter, inserted into the surface before explicit
inner/outer wall and rim construction. The A baseline differs from the clinic reference
by 14.098 mm RMS and has a worst normalized triangle aspect of 21.79.
Underlying principle: preserve clinical intent as geometric constraints; do not try to
recover missing topology through smoothing.
Clinical implication: surface landmarks establish anatomy and coordinates but cannot
replace Rigo classification, radiographic curve data or an explicit force prescription.
Blender / geometry implication: use exact contour insertion, local regularization,
corresponding wall loops and a controlled rim strip; validate correction deviation after
every finishing operation.
Reusable feature: reference-pair baseline with numeric mesh metrics and rendered compare.
Template update needed: generator research/specification and decision map created.
Test case needed: next - unified A perimeter prototype and exact-cut comparison.
Risk: high until the production generator is replaced; current Generate remains not
clinically ready.
Confidence: high in failure cause and target architecture; clinical template details need
orthotist confirmation.
Next action: resolve Decision Map ticket #2, then prototype ticket #3.

## Lesson ID: LM-0024
Date: 2026-07-12
Source: unified-perimeter implementation and three installed A iterations.
Observation: exact intersection alone removed visible saw teeth but initially created
extreme sliver triangles (aspect p95 >1900). Local remove-doubles, sub-0.3 mm degenerate
collapse, triangulation/beautification and targeted collapse of short edges on >20-aspect
faces reduced p95 to 1.45 while preserving a manifold shell. A generic waist-gap metric
does not equal opening width when the clinical inferior trim rises above waist.
Underlying principle: visual smoothness, topology and element quality require independent
gates; an anatomically shaped trim cannot be reduced to one angular measurement.
Clinical implication: opening/coverage must be evaluated against approved anatomy and
prescription, not a generic waist slice.
Blender / geometry implication: evaluate the Bézier+Shrinkwrap result, split crossed
triangles, then regularize only sub-tolerance fragments before Solidify/rim bevel.
Reusable feature: simple cylindrical perimeter clipper with one-component/manifold and
triangle-quality regression gates.
Template update needed: decision map tickets 3-7 updated and user check created.
Test case needed: done for A technical geometry; B visual, thickness, self-intersection and
signed-deviation preservation remain.
Risk: technical output is ready for orthotist visual review, not clinical fabrication.
Confidence: high in spike/root-topology fix; clinical equivalence unvalidated.
Next action: orthotist A user check, then B fixture and manufacturing QA gates.

## Lesson ID: LM-0025
Date: 2026-07-12
Source: full button-contract audit and installed A manufacturing-QA regression.
Observation: watertight/manifold and good triangle aspect did not detect three genuine
rim intersections. All were created by a global angle bevel; changing its width did not
remove them. Restricting bevel geometry to edges between the rim sidewall and shell walls
removed all intersections while rounding 2,623 intended edges. Emboss also returned
FINISHED while changing no geometry.
Underlying principle: every geometry operator needs an observable postcondition specific
to its purpose; generic topology and return status are insufficient.
Clinical implication: a technically smooth-looking shell may still contain fabrication
defects, and no automated geometric pass approves treatment intent.
Blender / geometry implication: evaluate the final dependency-graph mesh, test triangle
overlap and sampled opposing-wall distance, and scope bevel/boolean tools explicitly.
Reusable feature: blocking manufacturing QA plus geometry-change contract for booleans.
Template update needed: single perimeter before Generate; QA immediately before export.
Test case needed: B fixture and signed correction-deviation preservation.
Risk: sampled thickness can miss a very small local defect; report coverage and retain
physical/manufacturing review.
Confidence: high for detected defects and A technical fix.
Next action: direct tests for slots, correction cage, painted ventilation and landmarks.

## Lesson ID: LM-0026
Date: 2026-07-12
Source: new B-type installed geometry fixture and isolated open-surface probe.
Observation: the B open perimeter-clipped surface has zero self-intersections, but 4 mm
Solidify creates 60 pairs and collapses local wall thickness below 1 mm. Disabling even
offset reduces the count to 24 but worsens minimum thickness; 15 fairing passes also
worsen thickness. Both experiments were rejected.
Underlying principle: a collision-prone offset cannot be repaired by weakening its
thickness contract or globally smoothing prescribed geometry.
Clinical implication: B remains blocked from export and needs orthotist-reviewed trim/
surface intent before any local geometry repair is accepted.
Blender / geometry implication: next prototype must construct/repair the outer wall
independently while preserving the corrected inner wall and minimum thickness.
Reusable feature: stage-isolation probe distinguishing clean trim from failed offset.
Template update needed: none until B geometry/clinical review.
Test case needed: at this lesson's date, `btrimlinetest.py` was the explicit failing
gate. Superseded by LM-0028/DEC-0035: it now reports safe cancellation under
`SAFETY_PASS`, while `READINESS_PASS` and overall `PASS` intentionally remain false
until B generation and manufacturing QA succeed.
Risk: high for B fabrication; safely contained by export QA.
Confidence: high in failure stage.
Next action: collision-aware outer-wall prototype plus signed inner-wall deviation gate.

## Lesson ID: LM-0027
Date: 2026-07-13
Source: SpinalTech base4 internal reference audit, surface-edit regression and paired-wall
iteration on the supplied A model.
Observation: projecting only Bezier controls was insufficient evidence; sampled raw
interpolation deviated up to 12 mm, while Blender's evaluated Shrinkwrap curve stayed
exactly 1.50 mm from the body. Generate therefore must read evaluated geometry. Solidify
created six boundary-normal intersections; thickness clamp removed them but collapsed
the local wall to 0.03 mm. Barycentrically interpolated full-torso normals produced a
closed paired wall with zero intersections and 3.582 mm sampled minimum thickness.
Underlying principle: retain the reference surface field before a topological cut; never
repair an offset collision by silently weakening thickness.
Clinical implication: a commercial reference can define observable silhouette guardrails,
but cannot be copied as a patient design or treated as a force prescription.
Blender / geometry implication: raycast modal editing plus live Shrinkwrap is required for
surface-bound control; paired walls and an explicit rim are more deterministic than a
post-cut Solidify at concave boundaries.
Reusable feature: millimetre opening conversion, full-curve distance gate, source-normal
attribute, paired-shell builder and rim-aware QA sampling.
Template update needed: Rigo-Cheneau Reference compact profile added; A/B retained.
Test case needed: signed correction-deviation preservation and B-specific diagnosis remain.
Risk: technical pass does not validate laterality, coverage or clinical correction intent.
Confidence: high for surface attachment and A/reference manufacturing geometry.
Next action: orthotist visual approval, then signed correction preservation before B work.

## Lesson ID: LM-0028
Date: 2026-07-13
Source: back-side trim selection report, stale-thickness report, and installed
`trimvisibilitytest`, `designviewtest`, `meshintersectiontest`, `thicknesstest` and
`btrimlinetest` regressions, with installed import, outline, trim, reference, QA, export
and emboss confirmation.
Observation: a screen-distance-only trim picker could choose an occluded back control at
the same pixel as a front control. Separately, changing thickness left the prior shell
visible, which made the control appear ineffective and allowed finishing actions to
target stale geometry. Orthographic drag rays also used a fixed 1000-Blender-unit range,
which could end before reaching the body when the view origin was placed at the far clip.
The registered modal now rejects an overlapping hidden control, drags the visible point,
keeps it 1.499955 mm from the body, and restores the session on Esc. Its view-ray origin
is clamped from the scan and current view for precision, then raycasts over the BVH's
unbounded travel range. At 6 mm the
paired outer wall initially contained 25 exact
triangle collision pairs; local direction repair removed them while every constructed
inner/outer pair stayed 6.000 mm apart; repair took seven passes and changed a direction
by at most 18.287 degrees. Independent bidirectional-ray medians for 2/4/6 mm requests
were 1.999/3.999/5.998 mm, while the add-on QA minima were 1.740/3.654/5.386 mm. A
12 mm reference attempt could not be repaired and cancelled with the valid 6 mm
shell/base retained. The 4 mm B fixture is also safely blocked, but its
`READINESS_PASS` and overall `PASS` remain false.
Underlying principle: picking must include visibility, generated artifacts need explicit
source/parameter freshness, and a construction correspondence is not the same metric as
an opposing-surface sample. Geometry repair must preserve the clinical
inner surface and fail transactionally when its safety envelope is exhausted.
Clinical implication: an orthotist edits only the surface being viewed and cannot
unknowingly finish or export an obsolete shell. Automated collision containment and a
passing cancellation test do not approve trim coverage, B-type intent or fabrication.
Blender / geometry implication: reverse-ray occlusion filters the point candidate list;
TRIM and BRACE are explicit visibility/selection states; geometry signatures detect
native source edits; a scan/view-derived origin clamp plus unbounded BVH travel avoids
orthographic far-clip precision and truncation failures; exact triangle narrow-phase
results drive bounded outer-direction relaxation while paired spacing remains requested
thickness.
Reusable feature: visibility-aware modal picking with Ctrl+Z/Esc recovery; dirty-derived
artifact state; transactional candidate replacement; exact-intersection repair audit.
Template update needed: expose Edit Trimlines, Brace Preview and Update Brace state;
already integrated.
Test case needed: retain the registered-modal queued-window-event regression and add an
orthotist four-view review before calling B clinically ready.
Risk: exact technical geometry gates do not establish clinical prescription; independently
sampled thickness remains an approximation rather than a formal global minimum proof.
Confidence: high for the measured technical behavior on current fixtures; unresolved for
B clinical readiness.
Next action: signed inner-surface deviation report and orthotist review of B trim/surface
intent.

## Lesson ID: LM-0029
Date: 2026-07-25
Source: user report "shell does not create from the brace selection" + painted-trim
seam investigation, cross-model adversarial review, and installed-copy regressions.
Observation: the brace region is decided in a cylindrical (theta, z) plane whose seam
sits at theta = 0 — the patient's FRONT. Every consumer stored `angle % tau`, so a
painted region crossing the front was torn into two ends of the parameter domain and
the odd-even containment test was garbage. Measured on the A fixture: the perimeter
polygon agreed with the painted mask on **0.33 %** of vertices before the fix and
**99.47 %** after. The bug was invisible for four months because the Rigo *template*
puts its opening ON the seam, so every existing painted-trim test happened to paint a
region that never crossed it (0/1512 misclassified for template vs 792/1512 = 52 % for
a front-covering region). Two independent reproductions (mine and the reviewer's,
66.7 % and 46 % on different fixtures) agree.
Underlying principle: a periodic coordinate needs an explicit branch policy; `% tau`
is not one. And a fixture that only exercises the symmetric/aligned case cannot
falsify a symmetry-dependent bug — the template's opening sitting on the seam made
the test suite structurally blind.
Clinical implication: a custom-painted brace could silently keep the complement of
what the orthotist painted, or fragment into detached ribbons that passed every
manufacturing gate.
Blender / geometry implication: unwrap the densely sampled boundary (|d theta| > pi
between adjacent samples is provably a seam jump — the angle a chord subtends about
an interior axis is <= pi, verified over 400 000 random chords, max 3.141585), then
test every 2*pi replica of the query that falls in the polygon's span. Triangles must
be unwrapped relative to their own first vertex before clipping. A winding != 0 loop
encircles the axis and bounds no region in the unwrapped plane — reject it explicitly.
Reusable feature: `_unwrap_uv_polygon`, `_inside_unwrapped_polygon`,
`_clip_triangle_cylindrical` in design_ops; `_connected_component_count` +
the `components != 1` gate in `_validate_finished_rim`.
Template update needed: no.
Test case needed: done — `tools/customtrimseamtest.py` paints a FRONT-COVERING band
(opening at the back) and gates on before/after IoU, one mask loop, a closed manifold
single-component shell, and the shell landing on the painted side. It asserts the
fixture really crosses the seam, so it cannot silently degenerate into the old
blind case.
Risk: low for the fix; the reviewer's deeper findings (non-injective projection over
arms/axilla, legacy generator ignoring the paint mask) remain OPEN.
Confidence: high — before/after measured on real clinical geometry, five suites green.
Next action: decide on the mesh-native flood-fill cut (removes the parameterization
entirely) and the rim-density ceiling; both need approval.

## Lesson ID: LM-0030
Date: 2026-07-25
Source: parametric trimline smoothing (user: "control boundary smooth with no
iteration ... clean and parametric") and its adversarial review.
Observation: the old control was `trim_mask_smooth` = number of neighbour-averaging
passes over the vertex mask. Its transfer function is `0.35 + 0.65*cos(k*h)` per pass
where h is the MESH EDGE LENGTH, so "8 passes" means a 12 mm feature cut on a 1 mm
mesh and a 49 mm cut on a 4 mm mesh — and the pipeline remeshes between those states.
The control's clinical meaning moved by 4x with a setting changed two stages earlier.
Replaced by one Gaussian convolution along arc length on a fixed 1 mm resampling,
parameterised in millimetres (`trim_smooth_mm`). Measured: bit-identical across runs,
a 6 mm painted wobble falls to 0.83 mm at 8 mm smoothing, and a deliberate 60 mm-wide
25 mm-deep clinical relief keeps 96.8 % of its depth.
Underlying principle: a clinical control must be a physical quantity, not an
iteration count — determinism and resolution-independence follow from parameterising
by arc length rather than by topology.
Clinical implication: the same millimetre value now gives the same trimline on any
scan density, and the deviation from the painted line is reported rather than hidden.
Blender / geometry implication: the DELIVERED curve is what matters. Measuring the
deviation on the smoother's internal dense loop under-reported it (3.35 mm reported
vs up to 7.0 mm actually delivered, per the reviewer's measurement) because
`_resample_closed` then decimates to `_MAX_CUSTOM_CONTROLS`. Now measured after
smoothing + decimation + surface refit, against the painted line carried onto the
same offset surface.
KNOWN LIMIT: raising `_MAX_CUSTOM_CONTROLS` from 84 to 168 or 240 makes the perimeter
faithful but then `_validate_finished_rim` reports 5-8 local rim overlaps — the fillet
profile self-intersects where a denser boundary turns tightly. The ceiling belongs to
the RIM BUILDER, not the trimline. Reverted to 84 and documented in situ.
Reusable feature: `_smooth_closed_parametric`, `_control_spacing_m`,
`_delivered_deviation_m`.
Test case needed: done — smoothing determinism/monotonicity gated inside
`customtrimseamtest`.
Risk: medium — below ~24 mm the request is limited by control spacing, not the filter.
Confidence: high for the filter; the density ceiling is unresolved.
Next action: rework the rim fillet so control density can rise, then add a
`trim_min_radius_mm` curvature clamp (a wavelength cutoff does NOT bound turn radius:
a 15 mm / 5 mm sinusoid still has R_min = 1.14 mm).

## Lesson ID: LM-0031
Date: 2026-07-25
Source: rim-artifact directive (serrated/pinched/spiky rim) and its fix by uniform
arc-length boundary resampling in `curve_build_ops._resample_cut_boundary`.
Observation: the Exact intersect scatters cut-boundary vertices wherever cutter quads
cross surface edges — measured spacing varied 51x (0.10-5.10 mm). Because the rim
ceiling is 0.35 x local spacing, the fillet amplitude swung 8.6x vertex to vertex
(1455 adjacent jumps >25 %), which IS the serration; two attempts to smooth the radius
field post hoc both measurably made it worse. Resampling the boundary itself
(desliver -> split -> anchor-pinned collapse -> tangential relax with fold revert ->
crossing repair -> ear removal) delivered spacing ratio 3.6, radius ratio 1.8, 2 jumps,
0 frame reversals, 0 self-intersections, aspect p99 7.95 -> 3.40.
Underlying principle: when a downstream quantity is defined per-vertex from local
mesh density, no amount of downstream filtering can beat fixing the density itself.
Blender API gotchas paid for in blood this session:
- `bmesh.ops.subdivide_edges` WITHOUT `use_single_edge=True` does not split the
  adjacent face — it silently turns it into an n-gon carrying collinear midpoints,
  and `calc_loop_triangles` later emits zero-area triangles from them.
- A quad/n-gon whose corners are consecutive boundary vertices triangulates along an
  invisible DIAGONAL that shortcuts the trimline kink; no edge-based repair can see
  it. Force the diagonal (`connect_verts` through the kink) or fan from an interior
  corner.
- `BVHTree.find_nearest` during boundary relaxation can snap to the wrong sheet of a
  nearly-self-touching surface; cap the accepted correction (~0.15 mm) and keep the
  chord point otherwise.
- Repair collapses must never weld an interior vertex INTO a boundary vertex (seals
  the adjacent boundary edge) nor two non-ring-adjacent boundary vertices (pinches
  the loop into a figure-8); both were measured as valence corruption.
Clinical implication: the rim is now uniformly rounded at the requested radius
(mean 0.296 of 0.300 mm) with measured trimline fidelity p95 0.026 mm / max 2.73 mm
(the max sits at a hairpin the trimline itself cannot physically follow). Fidelity
must be measured against the trimline POLYLINE - nearest-SAMPLE distance charged
along-curve sliding as error and over-reported p95 36x (0.948 vs 0.026 mm).
Target spacing is capped at 1.2 mm: the 2.5 mm target implied by the default
1.0 mm radius could not articulate the 1.8 mm hairpin nub (4 wall-vs-rim
overlaps), so delivered radius is spacing-limited to ~0.42 mm and reported.
When splitting ear faces, connect the kink to an INTERIOR corner - connecting to a
boundary corner re-creates the chord being removed (measured livelock).
Known limits, all with correct refusals rather than bad braces: vector-handle
(zero-radius) trimline corners fold the Exact cutter or the 4 mm outer-wall offset;
a 30 mm rounded notch still folds the cutter; export remains blocked by the
`thickness_excluded_fraction` 20 % guard (measured 29.7 %, down from 40.5 %) —
guard recalibration is the user's open decision.
Reusable feature: `_resample_cut_boundary` and its phase functions; `rimqualitydbg`
(8-item audit), `rimstagedbg` (phase attribution), `rimresampletest` (regression).
Test case needed: done — `rimresampletest` gates spacing, radius uniformity,
reversal spikes, apex bound, aspect, fidelity, and thin-wall QA still failing.
Risk: low for the reference path (validator gates everything); medium for hostile
hand-drawn trimlines (fidelity gate 1.5 mm).
Confidence: high — every claim above is a measurement from this session.
Next action: user decision on the 20 % exclusion guard; optionally harden the Exact
cutter against deep-notch trimlines.

## Lesson ID: LM-0032
Date: 2026-07-26
Source: the trimline shading-seam investigation (issues.md #30) and six failed
profile-level fixes for it.
Observation: the visible seam is a real 75-degree crease where the rim strip meets
the wall faces (measured, not assumed: rimseamdbg dihedral audit; the external
review's density-transition theory measured 0.9-1.2 degrees on the rings it blamed).
Every attempt to remove the crease by cutting the wall back inside the profile
builder failed differently: translation cut-back folds shallow wall fans (568),
room estimates cannot be made reliable (10 -> 12 -> 15), fan-edge slides zigzag the
ring (58), and a 20-degree tangency margin still grazes facets, because fillet
radius, facet size and fan depth all live at the same 0.3-1 mm scale.
Underlying principle: when a construction requires threading new geometry between
faceted surfaces with no separation of scales, per-vertex heuristics reshape the
failure set instead of shrinking it; after two failed variants, stop and reach for
the engine's native tool (bmesh.ops.bevel with clamp_overlap) or re-scope.
Clinical implication: the shipped rim is unchanged and green; the seam is cosmetic
in shading and does not affect trimline position, wall thickness or QA.
Reusable feature: rimseamdbg.py (junction/ring dihedral + normal-jump + grading
audit); report-only junction line in rimresampletest.
Test case needed: junction-dihedral gate to be enabled when the bevel rework lands.
Risk: low - everything reverted; two revert cycles verified green.
Confidence: high on the diagnosis; the bevel fix is scoped but unbuilt.
Next action: user decision on the bevel-based junction rounding rework.

## Lesson ID: LM-0033
Date: 2026-07-26
Source: replacing the rim-exclusion QA guard, and measuring/rejecting a bevel fix for
the trimline seam (issues.md #28, #30).
Observation (guard): a safety metric defined as "excluded vertices / all vertices"
silently measured MESH DENSITY, because the excluded set was generated rim geometry
whose vertex count is a modelling choice. Rounding the rim more made the brace look
LESS safe (29.7 -> 47.1 %) while its wall stayed at 3.41 mm. Redefining it over the
structural wall only - rim provenance removed from numerator AND denominator, and a
wall vertex excluded only when every triangle carrying it touches rim - made it
0.01 % and invariant to segment count (0.00pp across 4 -> 12 segments) while still
firing at 41.5 % on a genuinely shadowed wall.
Underlying principle: a ratio is only a safety measure if BOTH sides describe the
thing being protected. If generated geometry can enter either side, the metric tracks
the generator's settings rather than the patient's brace.
Observation (bevel): bmesh.ops.bevel fixed the 75-degree junction crease with zero
self-intersections - the first construction all session to survive the exact validator,
because it only REMOVES material - but produced sliver triangles at every setting
(aspect p99 3.4 -> 48.7/98.9/151.4 for 1/2/3 segments, and 47064:1 max on a hostile
trimline). Mechanism: clamp_overlap achieves its safety by shrinking the offset toward
zero in tight spots, and a zero-width offset IS a sliver.
Underlying principle: "safe" and "well-shaped" are different guarantees. A tool that
buys safety by degenerating geometry has not solved the problem, it has moved it into
a metric you were not watching - so measure the new failure mode before accepting.
Clinical implication: export is now unblocked by the guard fix (the real blocker); the
seam is cosmetic and remains open.
Blender API note: `vertex_groups.add()` cannot SHRINK a group - rebuilding a sparse
tag needs remove + new, otherwise a test silently re-runs the dense case (this bug was
in my own first fixture and would have faked a passing legacy check).
Test case needed: done - tools/qaexclusiontest.py gates all five guard requirements.
Risk: low - guard verified on five fixtures; bevel reverted.
Confidence: high, all figures measured this session.
Next action: seam needs a graded transition band around the trimline BEFORE any
fillet rework - the rim is 10x smaller than the wall facets, so a tangent fillet has
nowhere to live at current density.

## Lesson ID: LM-0034
Date: 2026-07-26
Source: fixing the rim-to-shell seam after ten failed local repairs (issues.md #31).
Observation: the crease was the cross-section CURVE, not the architecture. `_rim_profile`
placed points at linear fractions across the wall with a sin(pi*f) outward bulge;
substituting f = u/t that is a sine arch w(u) = r*sin(pi*u/t), whose slope where it
meets the wall is pi*r/t, so it left a crease of atan(t / (pi*r)) at EVERY radius.
Predicted 74.7 degrees for t = 4.0 mm and r = 0.349 mm against 75.2/75.1 measured.
Because pi*r/t is finite for any finite radius, a sine arch can never be tangent.
Underlying principle: when a defect resists ten different local repairs, stop repairing
and derive the closed form. One page of algebra explained every previous failure at
once - density grading moved the seam 0.03 degrees, bevels slivered, cut-back arcs
self-intersected - because all of them were treating the symptom of a wrong curve.
A model that PREDICTS the measured number to 0.5 degrees is worth more than any number
of plausible mechanisms.
Second insight, equally load-bearing: the junction dihedral of the replacement is
exactly 45 degrees / (chords per arc). Sampling the cap uniformly by arc length spends
the chord budget on the straight closing run (3.3 mm against each arc's 0.55 mm),
leaves one chord per arc, and lands at 45 degrees. Chords must be ALLOCATED to the
curved parts.
Clinical implication: seam normal jump 37.48 -> 7.58 degrees with identical vertex and
face counts, identical trimline fidelity, identical delivered radius - a pure shape
change, so nothing downstream could regress.
Reusable feature: `_cap_offsets`, `_cap_chord_budget`, `tools/rimseamdbg.py`.
Risk: low. Confidence: high - analytic and measured agree.
Next action: none for the seam; it is closed.

## Lesson ID: LM-0035
Date: 2026-07-26
Source: the silhouette scalloping audit and its projection fix (issues.md #34).
Observation: `bvh.find_nearest` projection snapped the clinical trimline onto mold
facets, stamping a ~3.7 mm triangulation into a curve later sampled at ~1 mm. Measured
over identical sample counts, projection alone multiplied turn angle 2.7x (2.32 ->
6.19 degrees) and produced 28.8 % sign alternation. Every downstream stage tracked its
input faithfully; none created or removed the waviness.
Underlying principle: to attribute a defect to a pipeline stage, find the comparison
where only ONE thing changes. Stages that resample change point density, which moves
turn-angle statistics on its own; stages 1 and 2 shared spacing exactly, and that was
the only clean measurement in the pipeline.
Blender/geometry lesson: never re-snap a faired curve exactly onto a faceted surface.
`design_ops._constrain_to_source_band` had already documented this on the legacy path
and the curve path reintroduced it - check whether the codebase has already solved a
problem before designing a fix.
HARD-WON: a per-point displacement cap must never BIND. Tightening it from 0.4 to
0.15 mm, intended to bound the correction, took the reference brace from clean to 7 rim
overlaps: clipping each point's shift while neighbours are clipped by different amounts
destroys the smoothness the Gaussian just created. Correction strength belongs to a
continuous parameter (sigma); caps are safety stops.
ALSO: the setting that measures best in isolation is not necessarily shippable. Sigma
1.5 won every smoothness metric and broke the hostile hairpin by one rim overlap; 1.0
shipped.
DIAGNOSTIC TRAP, hit twice: a result that is INVARIANT across the swept variable is
almost always a broken fixture, not a real negative. Both times (reading a regenerated
brace through a stale pointer; crowding trimline points without re-deriving their
handles) it produced an identical refusal at every setting and read convincingly like
"this knob does nothing".
Reusable feature: `_debur_projected_curve`, `tools/rimwavedbg.py` (six-stage audit).
Risk: low - battery 12/12, fidelity improved. Confidence: high.
Next action: residual 3.90 vs 2.32 degrees is upstream - clinical Bezier continuity and
mold fairness only. Do not add downstream smoothing without a new stage audit.

## Lesson ID: LM-0036
Date: 2026-07-27
Source: the upstream template-trimline audit (user directive: fairness, duplication,
projection and smooth-editing) - tools/trimgenaudit.py + rimwavedbg rerun at shipped
settings; measurement only, no code changed. Full report:
TRIMLINE_TEMPLATE_AUDIT_2026-07-27.md.
Observation: the "doubled trimline" is not duplicate or stale geometry - lifecycle is
clean (name-keyed replacement, zero .001/Candidate leftovers, deterministic rebuilds).
It is the BRACE-view preview `Rigo Build Trim Perimeter`: a 1.2 mm-radius bevel tube
shrinkwrapped 0.2 mm above the inner wall, whose centerline sits 0.015-0.41 mm from
the shell - 1008/1008 samples closer than the tube radius, so the whole tube pierces
the shell and its emerging half reads as a second edge plus intermittent marks.
Separately: the displayed (shrinkwrap-evaluated) perimeter is NOT the curve Generate
builds from (raw Bezier, then projected): gap p50 0.48 / p95 2.39 / max 11.77 mm.
The clinical Bezier itself is FAIR (max 0.29 mm off its own 3 mm-smoothed self, 1.5 %
sign flips, zero >10-degree turns) - but G2 breaks at controls: junction curvature
jumps are ~10x the within-segment baseline (p95 54.5 vs 5.62 1/m), worst exactly at
the opening corners and top-front transition; handle reach is 0.25-0.75 of the
Catmull-Rom third-of-chord and control spacing spreads 5.4x (24.5-132.3 mm).
Editor: drag falloff is +/-2 CONTROLS, not millimetres - an 8 mm drag moved geometry
2.0 mm beyond 150 mm of arc; any point drag re-derives ALL handles, wiping a
user-rotated handle a quarter-perimeter away (20.0 -> 0.0 degrees); Add Curve Detail
radially re-fits every control and jumped the curve p95 3.7 / max 14.8 mm. Fit on an
untouched curve is a no-op (0.1 um) and drags do not create kinks (handle
re-derivation keeps G1) - the response is smooth but non-local and destructive of
handle intent.
Underlying principle: measure display, geometry and editing as separate contracts.
A pipeline can be geometrically faithful (shell fidelity p95 0.029 mm) while the
line the clinician SEES is neither the line being cut nor pierced-tube-free, and
while the EDITOR is smooth per-stroke yet non-local across strokes. Also: a G1
guarantee says nothing about curvature continuity - the 10x junction jump is the
"segments, not one curve" perception.
Clinical implication: the generated template is an anatomical draft guide; the
downstream cut/rim path is already manufacturing-grade. Verdict recorded as a split
classification, with a four-part limited prototype (P1 display truth, P2 stations +
centripetal tangent reach, P3 mm-falloff drag + local handle refresh, P4 refine
fits new midpoints only) awaiting user approval - all in trimline_ops.py plus one
display constant; rim/projection/QA untouched.
Reusable feature: tools/trimgenaudit.py (junction-continuity, handle-reach,
drag-locality, refine-fidelity, lifecycle and tube-penetration measurements).
Test case needed: trimgentest.py with the numeric gates in the report (junction
ratio <=3x, displayed-vs-raw p95 <=1 mm, drag locality, handle preservation,
refine <=1 mm, zero tube penetration).
Risk: none yet (audit only). Confidence: high - every claim measured this session.
Next action: user decision on P1-P4; adversarial cross-review when the codex CLI
quota returns 2026-08-01.

## Lesson ID: LM-0037
Date: 2026-07-27
Source: the upstream trimline wave P1-P4, the surface-adherence audit and its
rejected band-constraint prototype (commits 3f1c561, 2c3fe7d, 55dabb6, fd1a95f,
50e88ae, a29ccbb).
Observation: four separate user-visible defects had four unrelated causes, and every
one of them was misdiagnosed at least once before measurement settled it.
 - the "doubled trimline" was never duplicate geometry: it was the BRACE-view preview,
   a 1.2 mm tube whose centreline sat 0.015-0.41 mm from the shell, so 1008/1008 samples
   were inside their own tube radius.
 - the "connected segments" feel was C1-vs-C2. Junction curvature jumps measured 9.70x
   the within-segment variation. NO local tangent rule can fix this - Bessel/third-of-
   chord measured 9.91x - because the curvature entering a station is fixed by its left
   segment and the curvature leaving it by its right, and nothing local couples them.
   The closed non-uniform C2 solve gives 1.01.
 - "displayed is not what is built" was largely my own measurement error: I compared the
   display against the RAW Bezier rather than the projected cut path. The clinically
   meaningful tangential deviation was already 0.094 p95 / 0.570 max mm before any fix.
 - "Add Curve Detail moves the line 7.66 mm" was not the subdivision, which was already
   exact De Casteljau. It was a radial refit running afterwards over EVERY control.
 - "the trimline disappears into the mold" was the display Shrinkwrap's ON_SURFACE mode
   offsetting to the side the source point came from; every displayed sample measured
   exactly -1.500 or +1.500 mm.
Underlying principle: a user-visible symptom names a LOCATION, never a cause. Five
symptoms here, five different stages, and in four of them the first plausible mechanism
was wrong. Measure the specific pair that isolates one variable before writing a fix -
and when a result is INVARIANT across a swept variable, that is the tell (it caught the
protected-zone residual at -2.400/-2.410/-2.400 mm across three fixtures).
Blender/geometry lessons paid for this session:
 - `wrap_mode = ON_SURFACE` respects the ORIGINATING side. For anything that must stay
   visible above skin, ABOVE_SURFACE is the only safe choice. This bit twice, on two
   different curves, months apart.
 - a curve whose handles are a solved GLOBAL property must have every mutator use the
   same solve. Two handle models in one curve produced a phantom 19.2 mm "drag
   propagation" (larger than the 8 mm drag) and, separately, a rim overlap that
   cancelled the build after an ordinary brush stroke.
 - detecting "handles no longer match their points" by re-solving and comparing works
   only while every solve is global; fingerprinting the control POSITIONS the handles
   were last solved for survives banded solves and hand-set tangents too.
 - displacing a smooth correction along raw FACE normals re-injects triangulation noise
   (turn max 20.32 deg); interpolated vertex normals give 5.46 deg. And a Gaussian
   averages a peak DOWN, so a smoothed violation field under-corrects the deepest dip -
   dilate before smoothing.
Clinical implication: the generated trimline is now one curvature-continuous curve whose
cut lands where it is drawn (0.146 p95 / 0.685 max mm on the body), edits are local in
millimetres and bit-exactly undoable, adding detail cannot move the prescription, and the
editable line no longer vanishes inside the patient. The manufactured brace was never at
risk from the display defects - the cut rim measured 0% inside the body throughout.
Reusable feature: `tools/trimgentest.py` (35-gate battery, per-patch enforcement levels
so a revert relaxes only its own gates), `trimshot.py`, `trimadheredbg.py`,
`trimbanddbg.py`, `trimhostiledbg.py`.
Test case needed: done - trimgentest at P4 enforcement plus the full battery.
Risk: low for what shipped; the offset-mold blocker (#37) is unchanged and now has a
fourth independent piece of evidence against it.
Confidence: high - every figure above is a measurement from this session.
Next action: the offset-mold self-intersection (#37) is the shared constraint behind P2's
rejected variants, the 84-control ceiling, the projection-sigma ceiling and now the
rejected band constraint. Nothing upstream of it can improve further until it is fixed.
