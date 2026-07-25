# Rigo Brace Designer — Full Feature Contract Audit

Date: 2026-07-12  
Last behavior correction: 2026-07-13  
Blender: 5.0.1  
Readiness: technical audit and first repair wave; not clinical approval

## Research conclusions used as guardrails

- LeoShape publicly presents reference-point driven corrections, reusable design
  recipes, pressure/relief editing and manufacturing output. Rodin4D publicly presents
  scan import/cleanup, reusable rectification libraries, history, trim drawing and shell
  thickening. Neither vendor publishes its algorithms or numeric acceptance limits, so
  this project can reproduce the observable workflow but cannot claim an exact internal
  clone. Sources: [LeoShape](https://leopoly.com/leoshape/),
  [Rodin4D product catalogue](https://www.ortopro.no/wp-content/uploads/2020/03/Rodin4D-katalog-kompr.pdf),
  [Qwadra/Rodin orthopaedic CAD](https://qwadra.com/orthopedic-cad-cam-software/).
- A scoliosis brace is a prescribed three-dimensional force system. Pressure sites,
  expansion spaces, sagittal intent, opening and coverage must be explicitly reviewed by
  the orthotist; a surface scan cannot safely invent the prescription. Sources:
  [Rigo classification/design paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC2825498/),
  [SOSORT guidelines](https://scoliosisjournal.biomedcentral.com/articles/10.1186/s13013-017-0145-8).
- Published automated work still fits superior/inferior limits as splines, bounds radial
  corrections, smooths asperities, uses an explicit opening and requires orthotist
  approval. Study-specific dimensions are evidence, not universal defaults:
  [2024 automated brace study](https://www.nature.com/articles/s41598-024-53586-z).
- ISO 22523 covers strength, materials, risk and information for external orthoses. A
  2026 revision is still a draft, so the add-on must expose clinic/material thresholds
  instead of claiming a fixed standard value:
  [ISO 22523:2006](https://www.iso.org/obp/ui/en/#!iso:std:37546:en),
  [ISO/DIS 22523:2026 status](https://webshop.ds.dk/en/standard/M362372/dsf-pren-iso-22523).
- Mesh-quality implementation follows the established isotropic-remeshing sequence:
  split long edges, collapse short edges, improve triangle connectivity, smooth, and
  project/constrain to the reference surface. CGAL documents this sequence and exact
  corefinement Booleans; Open3D documents Taubin smoothing, and Manifold provides a
  robust Boolean alternative. None of those compiled libraries ships inside this
  Blender extension, so the current build implements the localized sequence with native
  BMesh/BVH operations and Blender's Exact Boolean solver:
  [CGAL Polygon Mesh Processing](https://doc.cgal.org/latest/Polygon_mesh_processing/index.html),
  [Open3D TriangleMesh](https://www.open3d.org/docs/latest/python_api/open3d.geometry.TriangleMesh.html),
  [Manifold](https://github.com/elalish/manifold).

## Definition of “working”

Every exposed action must satisfy all applicable contracts:

1. **Availability:** registered and visible in the intended workflow stage.
2. **Context:** refuses the wrong object/mode with a useful message; no traceback.
3. **Effect:** creates a measurable geometry/state change, not only `FINISHED`.
4. **Scope:** changes only the intended object/region/segment.
5. **Units:** millimetre controls measure correctly in evaluated geometry.
6. **State:** Apply/Reset/Undo, selection and helper cleanup behave predictably.
7. **Geometry:** no new boundary, non-manifold, zero-area or intersecting faces unless
   the action intentionally creates an intermediate open surface.
8. **Persistence:** saved styles/history/export artifacts survive the documented cycle.
9. **Clinical guard:** no automatic prescription or hidden fallback; review remains with
   the orthotist.
10. **User proof:** a fresh installed Blender session follows the exact panel path and
    writes an observable PASS/FAIL result.

## Inventory summary

- Current source declares **103** `rigo.*` operator idnames; the installed-copy
  `selftest` registration smoke list passes.
- `ui/panels.py` currently contains **83** operator placements covering **70** unique
  idnames.
- Direct isolated GUI coverage remains incomplete. Priority gaps include correction-cage
  build/edit/apply/reset, landmark mouse pick/clear/visibility, slot place/cut/clear,
  move/rotate/recenter, girth scale, selection invert, ground/measure/ortho toggles and
  painted ventilation selection. Trim-point visibility now has a registered-modal test
  that queues real viewport-window click, drag and Esc events.

Registration is not counted as functional proof. The remaining direct-test gaps are the
next audit tickets, not “assumed working”.

## Feature-by-feature contract matrix

| Area / exposed actions | Observable success criteria | Current evidence | Status / next action |
|---|---|---|---|
| Workflow tabs, Back/Next | One canonical 5-stage state; all controls agree; ends clamp | `workflowtest`, `selftest` | PASS |
| Full Screen, Quad, Ortho, fixed views, align | Rigo sidebar remains visible; exact prior state restores | `viewtest`, `quadtest` | PASS; add isolated toggle tests |
| Import STL / Import OBJ | Correct filter; one active Patient Scan; wrong extension blocked; old-patient trim curves removed and mismatched perimeter refused | `importtest` plus generator guard | PASS in the installed copy, including new-patient trim removal and stale-target refusal |
| Apply Units | Imported mm/cm/m becomes correct real size once; second use guarded | `applyunitstest` and most geometry fixtures | PASS |
| Center, Rotate, Move, Recenter/Floor | Predictable origin/orientation/floor without scale change | partial workflow coverage | Needs dedicated numeric test |
| Paint noise, Grow/Shrink/Clear/Invert/Delete | Accumulating through-surface selection; only selected geometry removed | paint/select/erase tests | PASS except isolated Invert test |
| Box Erase + Delete button | One view selects through whole model; explicit delete; no D key | `erasetest`, `keymaptest` | PASS |
| Fill Holes, Auto/Quad Remesh, Smooth, Check Mesh | Intended topology change; manifold counts reported; no silent damage | clean/quad/scan tests | PASS |
| Landmark Pick/Place/Clear | Correct named point on surface/cursor; duplicates replace safely | placement used by unified fixture | Needs isolated click/clear test |
| Selection push/thicken/smooth/delete | Exact mm, feathered scope, outside untouched | select/scan tests | PASS |
| Pressure/Expansion selection regions | Saved mask, mm magnitude, live normal-following preview, commit/mirror/style round-trip | region and region-style tests | PASS technically; orthotist reviews intent |
| Legacy pad/shape library | Boundary/save/favourite/mirror/apply persistence | pad tests | Technically tested but not panel-exposed; candidate migration/removal |
| Bend/Twist/Stretch + three ring pairs | Outside pair untouched; requested stretch equals measured mm; Apply/Reset | segment/bend/stretch/plane tests + user validation | PASS; UI polish only |
| Inflate/Deflate girth | Requested factor changes transverse dimensions only | older audit only | Needs isolated test |
| Correction Cage | Build/edit/apply/reset without helper leaks | no current direct test | HIGH test gap; overlaps lattice |
| Section Lattice Derotation | Per-section angle follows dial; low radial drift; discard exact | `latticetest` | PASS; “Edit” needs GUI test |
| X-ray import/transform/lock | Image follows model without jump; transforms correct | `xraytest` | PASS |
| Free Sculpt | Blender 5 brush values exact; enter/leave cleanly | `remoldtest` | PASS technically |
| Unified Auto Trim Lines | One cyclic perimeter; mm opening; every edit/evaluated segment remains surface-fitted; hidden back controls cannot be selected | `trimvisibilitytest`, `trimlinetest`, `referencetrimtest` | PASS technically; the registered modal accepted real orthographic viewport events, rejected the overlapping hidden point, dragged the visible point at 1.499955 mm from the body and restored the session on Esc; orthotist checks laterality and coverage |
| TRIM / BRACE state and Update Brace | One visible authority; source/parameter edits or an incomplete source record invalidate generated output; stale finishing/QA/export blocked | `designviewtest`, `thicknesstest` | PASS technically, including incomplete source records and failed-generation transaction restoration |
| Generate | Refuses missing perimeter/live deform; paired closed walls and one explicit rounded rim; exact intersections either repaired within bounds or cancel transactionally | reference/trimline/design/thickness tests | Reference/A 2/4/6 mm requests generate; 2 mm fails the configured sampled-thickness QA; B cancels safely and remains clinically unresolved |
| Rim smoothing / flare / see-through | Outside band fixed; measured flare; state toggles | `trimtest` | PASS |
| Strap slots | Vertical surface-normal capsule preview/cutter; measured fillet; exactly one wall opening per marker; transactional rollback; final shell remains QA-clean | `slottest`, `slotbracetest` | PASS on synthetic 4 mm wall and two sequential cuts on the curved reference brace |
| Ventilation grid | Bridge ≥3 mm; expected genus change; no new defects | `venttest` | PASS |
| Painted ventilation | Selected safe zone only; trim/protected zones excluded | operator registered only | HIGH direct-test gap |
| Emboss text | Geometry must actually change; temporary text removed; silent no-op forbidden | `embosstest` | PASS after exact-boolean fix |
| Manufacturing QA | Clean current shell; one component; mm units; closed/manifold; zero exact intersections/degenerates; sampled wall ≥ chosen threshold | `qatest`, `trimlinetest`, `meshintersectiontest`, `thicknesstest` | PASS technically; 2 mm reference run is correctly rejected by configured minimum |
| Final STL export | Dirty/source-changed shells blocked; QA reruns; only canonical brace exported; file nonempty/reimports at same size | `exporttest`, `thicknesstest` | PASS |

## Duplications and decisions

1. **Trimlines:** the top-only `Edit Outline` panel was a competing workflow and could
   not represent the opening/lower edge. It is now retired from the UI. Old operators
   remain registered for saved-file compatibility. The only clinical path is Unified
   Auto Trim Lines → Edit on Body/Fit → Generate.
2. **Thickness:** standalone “Add Thickness” was removed from Design UI because Generate
   already creates the wall. Applying both could double the wall unpredictably. The old
   operator remains for compatibility/non-brace meshes.
3. **Legacy flat trims:** Trim Top/Bottom controls were removed from the active panel.
   Generate now blocks without the unified perimeter; no silent bbox/flat fallback.
4. **Pressure systems:** the selection-first CorrectionRegion system is the active UI.
   The older pad library remains internally tested but must be migrated into the region
   style format or removed after saved-library compatibility is assessed.
5. **Two cages:** Correction Cage and Section Lattice both remain visible but overlap.
   Recommendation: keep Section Lattice for measured multi-section derotation; retain a
   renamed Free-Form Cage only if a dedicated test and clear clinical use justify it.
6. **Five stages/history:** history now derives from the same canonical five workflow
   stages; the former separate nine-stage state must not return.
7. **Construction thickness versus QA thickness:** corresponding inner/outer vertex
   pairs are generated at the requested spacing. Final-wall QA ray-samples
   opposing surfaces, so its minimum may be lower near shaped boundaries; both values
   are reported and neither is substituted for the other.

## Implemented in this wave

- Added final manufacturing QA with configurable minimum wall threshold.
- Added evaluated-mesh component, boundary/non-manifold, zero-area, normal/volume,
  self-intersection and sampled-thickness checks.
- Export always reruns QA and blocks on failure.
- Replaced the collision-prone post-cut wall offset with corresponding inner/outer
  surfaces built from the complete corrected-torso normal field and one explicit rim.
- Added exact triangle narrow-phase checks plus bounded local outer-direction repair.
  The installed 6 mm fixture repairs 25 collision pairs to zero in seven passes, with a
  maximum 18.287-degree direction change, while retaining 6.000 mm paired construction
  spacing. A 12 mm reference attempt cancels and retains the previous valid brace with no
  candidate objects left behind.
- Centralized failed-generation restoration: both private candidate objects are removed
  and the prior view/outline state is restored for known overlap cancellation and before
  any unexpected error propagates.
- Added `Edit on Body` raycast dragging, `Fit`, live Shrinkwrap, millimetre opening, and
  evaluated-curve surface-distance regression checks.
- Added visibility-aware trim-point picking so a click that is closer in screen space to
  the hidden control still moves only the visible control. The modal regression queues a
  drag and Esc restoration; Ctrl+Z restores the last completed point move, Esc the whole
  session and Enter commits.
- Replaced Edit on Body's fixed 1000-Blender-unit patient-surface ray cap with a
  scan/view-derived origin clamp for orthographic precision and an unbounded BVH travel
  distance. The registered orthographic modal regression passes.
- Added explicit Edit Trimlines/Brace Preview states, source-geometry signatures and a
  dirty-derived-artifact gate. Finishing, QA and export require Update Brace after a
  parameter, corrected-body or perimeter change.
- Replaced direct projection of every boundary-smoothing step with tangential Taubin
  fairing constrained to a one-sided 0-0.2 mm surface band. The trim band is locally
  remeshed, the unfilleted shell is repaired first, and the multi-segment rim is built
  last so generic skinny-triangle cleanup cannot collapse the finished fillet.
- Made strap-slot dimensions unambiguous (**Length** is vertical, **Width** is across),
  extended each cutter through the complete local wall, required exactly one new
  topological opening, and exposed CUT/FAILED status beside the button.
- Consolidated trimline workflow and removed duplicate outline/flat-trim controls.
- Fixed emboss so it cannot report success without changing geometry.
- Moved reusable A fixture setup into one test helper and converted downstream design,
  trim and ventilation tests to the clinical perimeter path.

## Remaining prioritized tickets

1. Direct isolated tests for the 20+ UI actions listed above, beginning with slots,
   correction cage, painted ventilation and landmark clicking.
2. Signed correction-deviation preservation report from corrected mold to generated
   inner wall.
3. B-reference clinical/generator resolution: current generation stops before producing
   a shell because exact outer-wall overlap remains after the bounded repair. This safe
   cancellation is correct containment, not a B-design pass. Review B trim/surface intent
   with the orthotist before changing repair limits, then run four-view/section comparison.
4. Variable-thickness/reinforcement map; remove or migrate the standalone thickness
   compatibility operator afterward.
5. Orthotist visual approval of A/B coverage, opening, iliac/trochanter/axilla clearances.

Automated PASS means the software contract passed. It does not mean the brace is safe to
fabricate or clinically correct for a patient.

## Installed-copy suite result

The focused installed-copy gates pass for the actual visible-only trim modal,
transactional design state, legacy-outline compatibility, new-patient import isolation,
reference/A trimline surface fit, paired shell, stale export blocking, exact intersection
checks, trim finishing, QA, isolated STL export and emboss geometry. In `thicknesstest`,
paired 2/4/6 mm construction distances are exact and an independent bidirectional-ray
sampler reports medians of 1.999/3.999/5.998 mm. Add-on QA sampled minima remain
1.740/3.654/5.386 mm; 2 mm fails the configured QA minimum, while 4 and 6 mm pass. The
6 mm outer wall repairs 25 exact collision pairs to zero in seven passes with a maximum
18.287-degree direction change. The 12 mm reference attempt cancels with the valid 6 mm
shell/base retained. `btrimlinetest` records the blocked 4 mm B overlap separately as
`SAFETY_PASS=True`; `manufacturing_qa_ready=False`, `READINESS_PASS=False` and overall
`PASS=False`. B readiness therefore remains blocked.

The direct installed results are `PASS=True` for `designviewtest`, `outlinetest`,
`importtest`, `trimlinetest`, `referencetrimtest`, `trimtest`, `qatest`, `exporttest`, and
`embosstest`; `designviewtest` includes the injected failed-generation transaction.

The final QA negative fixture sampled full thickness coverage and recorded
“Minimum sampled wall is 2.00 mm; required is 3.00 mm.” The export regression confirms
that QA reran before the canonical brace was written; the emboss regression confirms a
real mesh change and removal of its temporary text object.
