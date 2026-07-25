# Error Log

Bugs encountered and fixed. Full rationale in `learned_memory.md` (LM-xxxx).

## Error ID: ERR-0001  (→ LM-0001)
Date: 2026-06-13
Where: scan_ops.RIGO_OT_apply_units
Error message: none (silent)
Symptoms: model "disappears" after Apply Units (mm/cm); "m" did nothing.
Likely cause: ×0.001 rescale not followed by view re-frame; no feedback for no-op.
Fix applied: re-frame all VIEW_3D after rescale; double-apply guard (refuse if < 3 m); explicit messages.
Regression test: tools/applyunitstest.py.
Prevention rule: any bulk rescale must re-frame + report final size.
Files affected: rigo_brace/operators/scan_ops.py.

## Error ID: ERR-0002  (→ LM-0002)
Date: 2026-06-13
Where: select_ops paint-select
Symptoms: each Paint Area press wiped prior selection; new circle drags replaced selection.
Likely cause: unconditional deselect; circle-select default "Set" mode.
Fix applied: only deselect when whole mesh selected; force tool mode ADD.
Regression test: paintkeeptest.py, painttooltest.py.
Prevention rule: accumulate-region tools must set ADD and preserve partial selections.
Files affected: rigo_brace/operators/select_ops.py.

## Error ID: ERR-0003  (→ LM-0003)
Date: 2026-06-13
Where: deform_ops Bend
Symptoms: torso rolled/collapsed instead of side-bending.
Likely cause: Simple Deform BEND wrapped around axis Z (spread across shoulder width).
Fix applied: deform_axis = "Y" for BEND (Z for TWIST/STRETCH).
Regression test: bendtest.py (+ bendexp.py probe).
Prevention rule: verify Simple Deform axis empirically per use.
Files affected: rigo_brace/operators/deform_ops.py.

## Error ID: ERR-0004  (→ LM-0004)
Date: 2026-06-13
Where: deform_ops Stretch
Symptoms: girth shrank while lengthening.
Fix applied: lock_x = lock_y = True for STRETCH.
Regression test: stretchtest.py.
Files affected: rigo_brace/operators/deform_ops.py.

## Error ID: ERR-0005  (→ LM-0005)
Date: 2026-06-13
Where: deform range planes / modifier_apply
Symptoms: planes clamped to feet on unscaled scans; "Invalid driver" warnings after apply; thin rings unclickable.
Fix applied: lift field cap + unscaled warning; freeze driver values before apply; filled discs.
Regression test: planestest.py.
Files affected: rigo_brace/operators/deform_ops.py, core/__init__.py.

## Error ID: ERR-0006  (→ LM-0006)
Date: 2026-06-13
Where: pad_ops apply / boundary sampling
Symptoms: pad applied nothing (displacement 0); drape points landed far down the body.
Likely cause: raw Bezier AUTO handles = (0,0,0) (need evaluated curve); silhouette-grazing rays.
Fix applied: sample evaluated curve; bound drape travel + closest-point fallback.
Regression test: padtest.py, padshapetest.py.
Prevention rule: read evaluated_get(depsgraph) for curve handles; bound raycast drape.
Files affected: rigo_brace/operators/pad_ops.py.

## Error ID: ERR-0007  (→ LM-0007)
Date: 2026-06-13
Where: pad_library dynamic EnumProperty
Symptoms: risk of corrupted/garbled enum labels.
Fix applied: module-level cached items list, rebuilt only on version bump; append-only order.
Regression test: padshapetest.py (record→reselect round-trip).
Prevention rule: dynamic enum items must come from a long-lived cached list.
Files affected: rigo_brace/core/pad_library.py.

## Error ID: ERR-0008  (→ LM-0012)
Date: 2026-07-03
Where: remold_ops.py (both operators)
Symptoms: AttributeError: 'ToolSettings' object has no attribute 'unified_paint_settings' — the whole Remold feature dead on Blender 5.0.
Likely cause: Blender 5.0 moved unified paint settings from ToolSettings onto the per-mode Paint struct (tool_settings.sculpt.unified_paint_settings), which exists only after Sculpt mode has been entered once.
Fix applied: enter Sculpt mode FIRST, then set via version-tolerant `_unified_paint_settings()` (getattr fallback for <=4.x); apply_sliders warns instead of crashing outside sculpt.
Regression test: tools/remoldtest.py (numeric gates: unified size/strength equal panel sliders exactly).
Prevention rule: on every Blender major-version API touchpoint, verify the attribute path empirically (live MCP probe / headless) before shipping — never assume 4.x paths survive.
Files affected: rigo_brace/operators/remold_ops.py.

## Error ID: ERR-0009  (→ LM-0012)
Date: 2026-07-03
Where: the 70-operator audit itself (issues.md v1)
Symptoms: 5 of 12 findings were false — "corset has no shell", "place_landmark no-op", "silent cancels", "pad enum empty", "object accumulation".
Likely cause (audit-method pitfalls):
  1. Scripted bpy.ops calls cannot see self.report() UI messages → "silent" is unprovable from a script.
  2. "Has a live modifier" heuristics are blind to APPLIED (baked) modifiers → inspected the wrong object (hidden Corset Base cache instead of Rigo Corset).
  3. Counting effects AFTER a clear op in the same batch (place_landmark → clear_landmarks → count = 0).
  4. bl_rna.enum_items is empty for dynamic callback enums by design.
  5. The audit's own re-imports/abandoned modal sessions created the "accumulation".
Fix applied: re-verified every finding against source + a fresh live session before fixing (DEC-0015); issues.md rewritten with statuses + evidence.
Prevention rule: an audit finding is a HYPOTHESIS until confirmed in code or a clean isolated session; assert on named objects (CORSET_NAME) not name-substring heuristics; order effect-checks before cleanup ops.
Files affected: issues.md (rewritten).

## Error ID: ERR-0010  (→ ERR-0009 family)
Date: 2026-07-06
Where: tools/regiontest.py circle phase (test bug, not add-on bug)
Symptoms: all circle weights read 0.000 in the test while the operator produced correct
weights (proven live: seed 1.0, falloff 0.984/0.972...).
Likely cause: a bpy RNA vertex reference (`seed_v = mesh.vertices[i]`) captured BEFORE an
operator that modifies mesh runtime data (vertex-group writes) goes STALE — .index/.co
read garbage afterwards, so dict lookups keyed on it silently miss.
Fix applied: hold only the plain int index across operator calls; re-fetch
mesh.vertices fresh after every operator before reading.
Prevention rule: never keep bpy RNA element references (verts/edges/faces) across a
bpy.ops call in tests or tools — store indices/values, re-resolve after.
Files affected: tools/regiontest.py.

## Error ID: ERR-0011  (→ LM-0014)
Date: 2026-07-06
Where: lattice_ops.py lattice_add (Patch 5, caught by latticetest before shipping)
Symptoms: section twist gradient crushed (dials 0..30° produced 11.4..18.6°); rotating
only the bottom section moved NOTHING.
Likely cause: assumed lattice rest space spans 1.0 per axis; empirically points sit at
spacing 1.0 CENTRED, so rest span = (points_n - 1) units (3 pts -> ±1, 5 pts -> ±2).
Setting obj.scale = target_size made the cage 2x too wide and 4x too tall — the scan sat
in the middle cells only, blending only the middle dials.
Fix applied: scale = target_size / (points_n - 1) per axis; also KEY_LINEAR
interpolation so section planes hit their dial values exactly (B-spline does not pass
through control values).
Regression test: latticetest.py gates (bottom ~0°, top ~dial, monotonic, radial drift
< 1 mm proving no shear).
Prevention rule: never assume a Blender data-space convention — probe rest coordinates
(p.co) empirically before sizing/transforming; WASP dodged this via obj.dimensions.
Files affected: rigo_brace/operators/lattice_ops.py.

## Error ID: ERR-0012
Date: 2026-07-11
Where: `pad_ops.py`, Draw New Boundary modal, Enter / `_create_drawn_boundary`
Symptoms: Enter raised `AttributeError: 'NoneType' object has no attribute 'select_set'`.
Likely cause: immediately after deleting the modal preview curve, iteration over
`context.view_layer.objects` exposed a transient null RNA entry in Blender 5.0.
Fix applied: use Blender's `bpy.ops.object.select_all(action="DESELECT")`, which safely
handles dependency-graph selection changes, before selecting the new boundary.
Regression test: installed-copy `boundarytest.py` executes the same boundary-creation
path and passes; the transient interactive timing still requires the user Enter check.
Prevention rule: after modal object deletion, use Blender's selection operator instead
of directly iterating view-layer RNA objects during the same event.
Files affected: `rigo_brace/operators/pad_ops.py`.

## Error ID: ERR-0013
Date: 2026-07-12
Where: initial `tools/regionstyletest.py` process startup
Symptoms: Blender stayed open and no result file was written before the timer registered.
Likely cause: the test imported `rigo_brace.core` as a top-level package, but installed
Blender extensions live under `bl_ext.user_default.rigo_brace`; the import failed before
the test's exception capture and quit callback existed.
Fix applied: import the installed module through its full extension namespace.
Regression test: regionstyletest now starts, writes all phases, cleans its QA style and
quits; PASS=True.
Prevention rule: GUI tests that need add-on internals must import the installed extension
namespace, and imports needed only by the test should occur inside the captured lifecycle
where practical.
Files affected: `tools/regionstyletest.py`.

## Error ID: ERR-0014
Date: 2026-07-12
Where: localized Twist/Stretch between three deform rings
Symptoms: although modifier limits bounded deformation accumulation, the body above the
upper ring still translated/rotated as a rigid block, so the user correctly observed a
whole-body effect.
Likely cause: Blender Simple Deform `limits` carry geometry beyond the upper limit; limits
do not mean those vertices are excluded.
Fix applied: Twist/Stretch now use a live `Rigo Active Deform Segment` vertex group. A
guarded depsgraph handler rebuilds its smooth height weights whenever a ring moves. The
mask is zero outside both active rings. Stretch is entered in millimetres and calibrated
against the active weight profile.
Regression test: `segmentdeformtest.py` proves 0.0000 mm outside movement for both active
segments and exact requested/measured 40.00/40.00 mm Stretch. Existing stretch, plane,
bend and registration regressions remain green.
Prevention rule: test absolute outside-zone coordinates when the requirement says
"untouched"; pairwise-distance rigidity is not equivalent.
Files affected: core/__init__.py, operators/deform_ops.py, ui/panels.py,
tools/segmentdeformtest.py, tools/stretchtest.py, tools/planestest.py.

## Error ID: ERR-0015
Date: 2026-07-12
Where: `io_ops.py`, final STL export and workflow placement
Symptoms: the Step 1 folder field displayed invalid `//`; export depended on whichever
object was active/selected and could include the scan or helpers.
Likely cause: export was designed as a directory action on the active selection instead
of a final-artifact save operation.
Fix applied: use Blender's STL save browser, require the named `Rigo Corset`, isolate it
during export, verify a non-empty file, restore selection/mode/visibility, and place the
button last in Step 5.
Regression test: `tools/exporttest.py` exports with a far-away selected decoy, reimports
the STL, and proves exact dimensions and selection restoration.
Prevention rule: manufacturing export must target the canonical final object and verify
the written artifact, never trust active selection.
Files affected: `operators/io_ops.py`, `ui/panels.py`, `core/__init__.py`.

## Error ID: ERR-0016
Date: 2026-07-12
Where: `ui_ops.py`, Full Screen / focused view
Symptoms: maximizing produced no visible change in the one-area template; hiding all
panels also removed the Rigo Brace controls the user needs while working.
Likely cause: Blender's stock full-area operator cannot provide the required combination
of a clean viewport and persistent add-on sidebar in this application layout.
Fix applied: use an add-on-safe focused view: hide the native header/left toolbar while
forcing the Rigo sidebar and top stage bar visible; a second click restores exact prior
visibility states.
Regression test: `tools/viewtest.py` requires native header hidden, both Rigo control
surfaces visible, and exact state restoration.
Prevention rule: viewport tests must assert visible/application state, not only operator
return status; screen-changing operators must use `window.screen`.
Files affected: `operators/ui_ops.py`, `tools/viewtest.py`.

## Error ID: ERR-0017
Date: 2026-07-12
Where: `scan_ops.py`, Box Erase
Symptoms: a box drawn in Back view selected only the visible surface, requiring repeated
selection from other views.
Likely cause: Edit-mode solid selection was occlusion-limited.
Fix applied: Box Erase temporarily enables X-ray selection for every 3D view and shows
explicit `Delete Box Selection` / `Finish Box Erase` buttons while active, then restores
the prior X-ray state. A briefly proposed plain-D shortcut was removed by user request.
Regression test: `tools/erasetest.py` selects all six cube faces from one Back-view box
and deletes all six through the button operator; `tools/keymaptest.py` verifies no D map.
Prevention rule: a tool described as a volumetric/big cut must explicitly enable and test
through-model selection.
Files affected: `operators/scan_ops.py`, `keymaps.py`, `ui/panels.py`,
`tools/erasetest.py`, `tools/keymaptest.py`.

## Error ID: ERR-0018
Date: 2026-07-12
Where: Step 1 patient-scan import UI
Symptoms: one combined Import Scan button technically accepted STL/OBJ but did not make
the required input choice clear before the landmark-driven workflow.
Likely cause: file-format capability existed only as a combined browser filter.
Fix applied: provide separate `Import STL` and `Import OBJ` buttons; each browser is
restricted to its selected format and the imported mesh becomes the active Patient Scan.
Regression test: `tools/importtest.py` creates, imports and validates real STL and OBJ
fixtures and rejects a mismatched extension.
Prevention rule: clinically important workflow choices must be explicit in the panel,
not hidden inside a generic file browser.
Files affected: `operators/io_ops.py`, `ui/panels.py`, `tools/importtest.py`.

## Error ID: ERR-0019
Date: 2026-07-12
Where: `design_ops.py` / `trimline_ops.py`, brace generation and trim rims
Symptoms: generated brace had wrong/disconnected-looking trim geometry, severe saw-tooth
spikes and no reliable continuous opening perimeter.
Likely cause: two independent cyclic trim curves; whole-face deletion by face center;
auto-trim path returned before opening; strong global Smooth shrinkage; Solidify baked the
damaged boundary before finishing.
Fix applied: generate one cyclic 42-point perimeter containing upper/lower/opening edges,
Shrinkwrap it to the corrected mold, clip triangles at exact parameter-space edge
intersections, collapse/beautify slivers, use gentle volume-preserving fairing, even
Solidify and a three-segment angle-limited rounded rim.
Regression test: `trimlinetest.py` gates one cyclic constrained curve, one shell component,
zero boundary/non-manifold edges, aspect p95 <3 and max <100. `trimtest.py`, design,
export, workflow and selftest remain green. `generatoraudit.py` renders the A comparison.
Prevention rule: a clinical trim is a continuous geometric constraint inserted before
wall construction; smoothing must never substitute for missing contour topology.
Files affected: `operators/trimline_ops.py`, `operators/design_ops.py`, `core/__init__.py`,
`ui/panels.py`, generator/trim tests and research documentation.

## Error ID: ERR-0020
Date: 2026-07-12
Where: `design_ops.py`, automatic rounded trim rim.
Symptoms: A shell passed manifold/aspect gates but manufacturing QA found three
self-intersecting triangle pairs.
Likely cause: global angle-limited Bevel also rounded incompatible opening/corner edges.
Fix applied: identify weight-1 trim vertices and bevel only edges with exactly one
sidewall face and one shell-wall face; retire the legacy generation path from the UI.
Regression test: `trimlinetest.py` requires rounded rim edges >0 and zero intersections.
Prevention rule: bevel clinical rims by semantic topology, not global angle alone.
Files affected: `operators/design_ops.py`, `tools/trimlinetest.py`.

## Error ID: ERR-0021
Date: 2026-07-12
Where: `design_ops.py`, Emboss Text.
Symptoms: operator reported success while vertex/face counts did not change.
Likely cause: Boolean completion was treated as proof even when the cutter missed or the
solver produced an unchanged mesh.
Fix applied: use the Exact solver for converted font islands and require an observable
geometry change; otherwise cancel with an error.
Regression test: `tools/embosstest.py` checks real geometry change and helper cleanup.
Prevention rule: boolean tools must verify their intended geometric postcondition.
Files affected: `operators/design_ops.py`, `tools/embosstest.py`.

## Error ID: ERR-0022
Date: 2026-07-13
Where: `core/__init__.py`, dynamic trim-profile enum registration
Error message: `default can only be an integer when items is a function`
Symptoms: the first install failed before the add-on registered.
Likely cause: Blender 5 does not allow a string default on callback-provided enum items.
Fix applied: remove the illegal property default and sort `trimline_RIGO_CHENEAU.json`
first in the stable dynamic item list.
Regression test: installed `selftest.py` reports `ALL_PASS=True`; the reference fixture
selects `RIGO_CHENEAU` successfully.
Prevention rule: verify Blender RNA restrictions in the installed application, not only
Python compilation.
Files affected: `core/__init__.py`, `core/trim_templates.py`.

## Error ID: ERR-0023
Date: 2026-07-13
Where: trimline editing and shell wall construction
Symptoms: free-moved trim controls floated off the torso; the initial reference-profile
shell had two final intersections. Thickness clamp hid the overlap but produced a 0.03 mm
wall.
Likely cause: generic 3D movement had no mouse-to-surface contract, and Solidify used
normals recalculated after the clinical perimeter removed adjacent faces.
Fix applied: `Edit on Body` raycasts every drag, `Fit` projects existing points, live
Shrinkwrap holds the evaluated curve, and Generate builds paired walls from full-torso
barycentrically interpolated normals. QA samples the wall away from the explicit tapered
rim and limits the exclusion fraction.
Regression test: `referencetrimtest.py` deliberately floats a point 60 mm, refits it,
checks raw/evaluated distance 1.50 mm, 25 mm opening, 2,294 rounded edges, zero
intersections and 3.582 mm minimum wall. A, trim finishing, QA and export tests pass.
Prevention rule: test full evaluated geometry, not only controls; never accept an
intersection fix without rechecking minimum wall.
Files affected: trimline/design/trim/QA operators, core/UI, reference fixture and tests.

## Error ID: ERR-0024
Date: 2026-07-13
Where: rejected structured-grid shell experiment during commercial-reference comparison
Symptoms: a regular 121 x 81 radial grid improved boundary topology visually but the
paired outer wall produced 20 self-intersection pairs and only 2.663 mm sampled local
wall; smoothing its direction field worsened the wall to 2.177 mm.
Likely cause: resampling the patient-contact surface changed the correspondence between
the corrected inner wall and the retained full-torso normal field; smoothing directions
made neighbouring outer-wall trajectories cross in high-curvature axillary regions.
Fix applied: rejected and removed the experiment; restored the exact triangle clip plus
full-torso-normal paired wall, which retains zero intersections and 3.582 mm sampled
minimum wall on the reference path.
Regression test: `referencetrimtest.py` must run in a normal hidden Blender session, not
`--background`; its result timestamp must advance and `PASS=True`.
Prevention rule: do not replace a passing patient-contact surface merely to improve the
rim silhouette. Prototype local rim retopology separately and keep wall/thickness gates.
Files affected: `operators/design_ops.py`, `tools/referencetrimtest.py`.

## Error ID: ERR-0025
Date: 2026-07-13
Where: `trimline_ops.py`, Auto Trim Lines drape on a user scan
Error message: `Could not drape the template onto this scan`
Symptoms: the Rigo-Cheneau template appeared in the selector but no perimeter was made.
Likely cause: the BVH is in object space while the ray maximum was measured in world
space; scans retaining object scale could therefore truncate valid rays. At high sloped
shoulders an exact horizontal ray can also legitimately miss the local surface.
Fix applied: convert the full ray segment into object space, transform normals with the
inverse-transpose matrix, and use a nearest-surface fallback only when a radial ray
misses. The generated perimeter records the fallback count and warns for visual review.
Regression test: `trimdrapetest.py` uses a non-uniformly scaled/rotated scan, raises both
acromion landmarks to force four fallbacks, produces 42 points, and measures 1.589 mm
maximum raw distance (`PASS=True`). The identity-transform reference remains exactly
1.500 mm and its shell/QA test passes.
Prevention rule: never mix world distances with an object-space BVH; transformed scans
need a dedicated regression case.
Files affected: `operators/trimline_ops.py`, `tools/trimdrapetest.py`, user guide.

## Error ID: ERR-0026
Date: 2026-07-13
Where: `trimline_ops.py`, unified-perimeter `Edit on Body`
Symptoms: a click intended for a visible front trim control could select an occluded
back-side control projected to nearly the same screen position, deforming the wrong side
of the perimeter.
Likely cause: the picker ranked controls only by two-dimensional pixel distance and the
curve was displayed in front of the body, so neither presentation nor selection enforced
surface visibility.
Fix applied: candidate controls now pass a corrected-body reverse-ray occlusion test;
the curve is not forced in front while editing. The modal stores the viewport window
coordinates, Ctrl+Z restores the last completed point move, Esc restores the full invoke
snapshot, and Enter commits. The legacy `Edit Trimline` entry routes to the guarded
surface editor.
Regression test: `trimvisibilitytest.py` retains transformed-scan kernel checks, invokes
the registered modal operator, queues viewport-window click/drag/release events at a
screen position that favours the hidden control by proximity, verifies only the visible
control moves, then queues Esc and checks full-snapshot and in-front-state restoration.
Prevention rule: screen proximity is only a candidate filter; every surface-control pick
must also prove line-of-sight against the evaluated patient surface and provide session
recovery.
Files affected: `operators/trimline_ops.py`, `tools/trimvisibilitytest.py`, user guide.

## Error ID: ERR-0027
Date: 2026-07-13
Where: generated-brace parameter changes, source edits and Design-stage visibility
Symptoms: changing Thickness appeared to do nothing because the previously generated
shell remained visible. A stale shell could also remain selected for finishing, QA or
export after the corrected body or perimeter changed.
Likely cause: settings and source geometry had no derived-artifact freshness state, and
the scan, perimeter and shell could be shown together without an authoritative editing
or preview mode.
Fix applied: `mark_brace_dirty` invalidates prior QA; `geometry_signature` fingerprints
the corrected body and perimeter used at generation; `design_view_mode` makes TRIM and
BRACE visibility/selection mutually explicit. Parameter or source changes switch to
TRIM and block finishing, QA and export until Update Brace regenerates a clean shell.
`brace_has_source_record` requires both source signatures. Importing a new patient scan
removes the prior trim curves, and Generate verifies that the perimeter's Shrinkwrap
target is the current scan. The panel and finishing operators share
`brace_ready_for_finishing`; a legacy shell without a recorded built thickness displays
that value as unknown instead of 0 mm.
Regression test: `designviewtest.py` verifies both visibility states, finishing gates,
trim refit dirtiness, Update Brace cleanup and native corrected-body signature changes.
`thicknesstest.py` verifies a 4-to-6 mm change blocks QA/export and writes no STL before
the update (`PASS=True`).
Prevention rule: generated clinical geometry is a derived artifact; persist the source
signatures and requested parameters, expose stale state, and refuse downstream actions
until regeneration succeeds.
Files affected: `core/__init__.py`, `core/signatures.py`, design/trimline/QA/IO operators
and source-mutation operators, `ui/panels.py`, `tools/designviewtest.py`,
`tools/thicknesstest.py`.

## Error ID: ERR-0028
Date: 2026-07-13
Where: `design_ops.py`, paired outer-wall construction at larger offsets and the B fixture
Symptoms: paired normal offsets could cross in concave regions. A 6 mm reference run
started with 25 exact outer-wall collision pairs; a 12 mm reference request and the
4 mm B fixture remained intersecting beyond the accepted repair envelope.
Likely cause: neighbouring patient-surface normals can diverge or cross after a larger
offset even when each vertex retains a direct inner/outer correspondence. A BVH overlap
alone is broad-phase evidence and cannot distinguish every true triangle intersection.
Fix applied: `mesh_intersections.py` performs exact non-coplanar and coplanar triangle
narrow-phase checks after BVH candidate generation. Only directions belonging to
intersecting outer triangles are blended toward adjacent directions, normalized to retain
requested pair length, and limited to 12 passes and 25 degrees from their originals. If
collisions remain, candidate generation cancels transactionally and retains any previous
valid brace/base. `_restore_failed_generation` also removes both private candidates and
restores the prior view/outline state for unexpected exceptions before they propagate.
Regression test: `meshintersectiontest.py` covers coplanar, non-coplanar and separated
faces; ordinary shared-vertex/shared-edge neighbours; a crossing through a shared vertex;
overlap beyond a shared edge; and duplicate faces. `thicknesstest.py` records exact
2/4/6 mm pair ranges,
independent bidirectional-ray medians 1.999/3.999/5.998 mm, add-on QA minima
1.740/3.654/5.386 mm, and a 6 mm repair from 25 to zero pairs in seven passes with a
maximum 18.287-degree direction change. Its 12 mm attempt cancels with the 6 mm
shell/base retained and no candidates.
`btrimlinetest.py` separates containment from readiness: a controlled block is counted
under `SAFETY_PASS`, while `manufacturing_qa_ready`, `READINESS_PASS` and overall `PASS`
remain false until a generated B shell passes manufacturing QA.
`designviewtest.py` injects an unexpected failure after candidate-base creation and checks
that both candidates disappear, the prior brace/base remain canonical, and view/outline
state is restored.
Prevention rule: never treat paired vertex spacing as proof of a collision-free or
minimum-thickness final wall. Use exact triangle checks, bound any outer-only repair,
leave the inner clinical surface unchanged, and replace the canonical shell only after
all generation gates succeed. Every failure path must remove both candidate names and
restore the previous working state.
Files affected: `operators/design_ops.py`, `operators/mesh_intersections.py`,
`operators/qa_ops.py`, `tools/meshintersectiontest.py`, `tools/thicknesstest.py`,
`tools/btrimlinetest.py`.

## Error ID: ERR-0029
Date: 2026-07-13
Where: `trimline_ops.py`, Edit-on-Body drag in orthographic view
Symptoms: the visible trim control could be selected, but dragging did not move it in an
orthographic viewport whose ray origin was farther than 1000 Blender units from the body.
Likely cause: the patient-surface BVH raycast used a hard-coded 1000-Blender-unit maximum.
Blender can place an orthographic ray origin at the viewport far clip, beyond that fixed
range.
Fix applied: clamp the orthographic origin to twice the furthest scan-corner distance
from the current view location (with a 1.0 Blender-unit floor), as recommended by the
Blender view utility's clamp contract, then omit the maximum-distance argument so
`BVHTree.ray_cast` uses its unbounded travel range. Visibility filtering and the 1.5 mm
surface offset are unchanged.
Regression test: `trimvisibilitytest.py` invokes the registered modal in orthographic
view, queues real viewport click/drag/Esc events, rejects the overlapping hidden control,
moves the visible control to 1.499955 mm from the body, restores the full snapshot and
reports `PASS=True`.
Prevention rule: do not impose a model-space distance cap on a view ray whose origin is
controlled by orthographic clip settings. Clamp the origin from the actual view and scan
for floating-point precision, and do not truncate the subsequent BVH travel distance.
Files affected: `operators/trimline_ops.py`, `tools/trimvisibilitytest.py`, verification
and audit documentation.
