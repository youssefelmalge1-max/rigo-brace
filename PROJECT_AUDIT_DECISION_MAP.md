# Rigo Brace Add-on — Systematic Audit Decision Map

Purpose: establish one coherent workflow, verify every user-facing feature in Blender,
repair failures one module at a time, and leave repeatable regression evidence.

Status: ticket #1 resolved. At the user's direction, ticket #9 is the current frontier;
ticket #2 remains open.

## #1: One Canonical Workflow and History Model

Blocked by: none
Type: Discuss

### Question

How should the five tool tabs and nine disconnected `brace_stage` checkpoints become
one functional workflow, and what must one history checkpoint restore?

### Answer

Resolved 2026-07-11: the five implemented tool stages (`FILE`, `SCAN`, `LANDMARKS`,
`MESH`, `DESIGN`) are canonical. Panel icons, panel Next/Back, viewport header and
workspace synchronization all use `Scene.rigo_brace.brace_stage`; `active_tab` and the
duplicate `RIGO_PT_workflow` panel were removed. The incomplete single-mesh history
operators remain hidden and explicitly legacy until ticket #3 replaces them, then the
module is deleted. Proof: [workflowtest_result.txt](workflowtest_result.txt) PASS,
[selftest_result.txt](selftest_result.txt) ALL_PASS, legacy history regression PASS,
source/install hashes equal, and Blender UI screenshot inspected.

## #2: Icon-Led Interface Prototype

Blocked by: #1
Type: Prototype

### Question

What compact icon-led layout makes the canonical workflow fast and understandable to
an orthotist while retaining labels/tooltips for unambiguous clinical actions?

### Answer

Open. Reuse the existing `bpy.utils.previews` loader and bundled PNG mechanism. Compare
at least two small UI layouts using real workflow/tool groups; choose one before
rewriting the full panel.

## #3: Patient Project and Complete Checkpoint Prototype

Blocked by: #1
Type: Prototype

### Question

Can a checkpoint reliably save, reopen, and restore the scan, corrections, landmarks,
pads, corset/base, trim curves, slots, helpers, X-ray state, and stage metadata without
cross-patient collisions?

### Answer

Open. Define explicit project ownership metadata and test save/reopen restoration in a
real `.blend`; single-mesh duplication is not sufficient evidence.

## #4: Test Harness and Evidence Standard

Blocked by: #1
Type: Discuss

### Question

What evidence is required to classify a tool as Registered, Script-Tested,
GUI-Tested, Workflow-Tested, or Blocked?

### Answer

Open. Include a clean install step, source/install hash check, numeric geometry gates
where applicable, visible report/error checks, save/reopen checks, and a result date.

## #5: File, Units, Orientation, and Clean Audit

Blocked by: #4
Type: Prototype

### Question

Do import, unit conversion, project initialization, alignment, cleanup, verification,
remesh, and undo work in their intended order on representative torso scans?

### Answer

Open.

## #6: Landmarks, Measurements, and X-ray Audit

Blocked by: #5
Type: Prototype

### Question

Are landmarks, anatomical levels, measurements, X-ray placement/locking, persistence,
and checkpoint restoration connected and clinically understandable?

### Answer

Open.

## #7: Guided Shaping and Free Sculpt Audit

Blocked by: #5, #6
Type: Prototype

### Question

Do selection, pressure/expansion regions, push/pull, smoothing, remold, and correction
cages produce measurable, undoable, persistent changes without damaging unrelated
geometry?

### Answer

Open.

## #8: Deformation and Lattice Audit

Blocked by: #5, #6
Type: Prototype

### Question

Do bend, twist, stretch, range planes, girth scaling, correction cage, and section
lattice behave predictably together and restore correctly from checkpoints?

### Answer

Three-ring segment slice resolved 2026-07-12. The local LeoSpinal tutorial explicitly
describes two/three-loop Stretch and a deformation limited between two curves; Bend and
Twist use positioned bounding planes/curves. The old two-ring UI was replaced by filled,
draggable Lower/Middle/Upper rings with selectable Lower–Middle, Middle–Upper and full
intervals. Localized Twist/Stretch now use a live ring-height mask so both outside zones
remain fixed; Bend retains its approved rigid continuation. Installed proof:
`segmentdeformtest`, `planestest`, `bendtest` and `stretchtest` all PASS; localized
outside movement 0.0000 mm, requested/measured Stretch 40.00/40.00 mm, and Bend
rigid-distance error 0.0000 mm. Visual ring capture inspected. Research and user check:
[leospinal_three_ring_research.md](orthoblender-spine-skill/docs/leospinal_three_ring_research.md),
[user_check_three_ring_deform.md](orthoblender-spine-skill/docs/user_check_three_ring_deform.md).
User validation completed 2026-07-12: **Bend, Twist, and Stretch are technically
complete**. Their geometry is now a frozen regression baseline. Icons, names, labels,
and ring/disc appearance are deferred UI polish and must not change deformation math.
Ticket #8 remains open only for lattice, correction-cage, and checkpoint interaction
auditing.

## #9: Pads and Clinical Correction Library Audit

Blocked by: #1
Type: Prototype

### Question

Do pad placement, editing, recording, favourites, mirroring, application, persistence,
and visibility work as one understandable pressure/relief workflow?

### Answer

Research approved 2026-07-11. The named built-ins were clinically misleading identical
circles; Size does not update placed shapes and repeated Apply compounds deformation.
Proposed
replacement: author a closed boundary → edit points/handles → save exact template →
generate/drape on patient → edit boundary → deterministic preview → explicit commit.
Specification and gates: [pressure_expansion_feature_spec.md](orthoblender-spine-skill/docs/pressure_expansion_feature_spec.md).

Implementation step 1 complete: schema v2 creates a byte-identical v1 backup, preserves
custom entries, moves clinical-named circles into `UNVERIFIED_LEGACY`, marks missing
handle fidelity, and adds only Blank Oval / Blank Rounded Rectangle primitives. Proof:
padlibrarytest PASS, padtest/padshapetest/padfavtest PASS, selftest ALL_PASS.

Implementation step 2 ready for user check: Draw New Boundary creates a closed surface
outline; Edit Boundary exposes points/handles; Save Boundary persists evaluated Bézier
points plus exact left/right handles; Generate Saved restores them. `boundarytest` PASS
with max normalized round-trip delta `6.77e-08`; selftest ALL_PASS; visual edit capture
inspected. User guide: [user_check_pressure_boundary.md](orthoblender-spine-skill/docs/user_check_pressure_boundary.md).
The curve-first conclusion above is superseded by the manual check below.

Manual user check superseded curve-first authoring. The primary panel is now
**Pressure / Expansion (Selection)**: painted faces create a smooth weighted region;
the live Displace preview follows each local surface normal; Edit Selection restores
the mask; Update Preview is non-cumulative; Commit is one-time. The legacy curve tools
remain registered for file compatibility but are hidden from the panel. Installed-copy
proof: `regiontest PASS=True` (10.000 mm preview, 7.000 mm update/commit, outside movement
zero, base unchanged before commit, topology unchanged) and `selftest ALL_PASS=True`.
User check pending: [user_check_pressure_selection.md](orthoblender-spine-skill/docs/user_check_pressure_selection.md).
Committed-mask Save/Import resolved 2026-07-12. `Save Committed Style` writes a global
surface-local weighted template; `Import at Cursor` reprojects it onto another scan as an
editable live region. `regionstyletest PASS=True`: pre-commit save rejected; committed
8.000 mm saved and JSON-reloaded; different-topology target imported/committed exactly
8.000 mm; cleanup passed. Guide:
[user_check_region_styles.md](orthoblender-spine-skill/docs/user_check_region_styles.md).
Ticket #9 remains open only for self-intersection rejection, overlap rules and clinical
orthotist validation.

## #10: Trimline and Shell Audit

Blocked by: #7, #8, #9
Type: Prototype

### Question

Do automatic/manual trimlines, shell generation, smoothing, outline editing, thickness,
flare, slots, and emboss remain geometrically valid through edit and checkpoint cycles?

### Answer

Open.

## #11: Ventilation and Manufacturing QA Audit

Blocked by: #10
Type: Prototype

### Question

Do ventilation and finishing preserve bridge width, wall thickness, manifold geometry,
safe edges, and intended correction zones?

### Answer

Open.

## #12: Export and End-to-End Release Gate

Blocked by: #3, #4, #11
Type: Prototype

### Question

Can a fresh installation complete one patient case from import through reopened history
to a correctly named, print-ready export with a recorded QA result?

### Answer

Open. Rebuild the distributable ZIP only after this gate passes.
