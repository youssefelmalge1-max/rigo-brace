# Feature Backlog

Status: ✅ done · ⚠ caveat · ⛔ missing. Priority: P0 (next) … P3 (later).

## Works (✅) — keep regression tests green
- Import and final-phase isolated STL export (artifact/reimport tested), scan units
  (+ disappear-fix), realign/recenter, clean/remesh/smooth
- Explicit STL/OBJ patient-scan import before the landmark workflow
- New-patient isolation: importing a different scan removes patient-specific trim curves,
  marks any existing brace stale and returns to Edit Trimlines. Generate also refuses a
  perimeter whose Shrinkwrap target is not the current scan (`importtest`).
- Add-on-safe focused Full Screen (Rigo controls remain visible) and through-model Box
  Erase with explicit Delete/Finish buttons
- Unified surface-bound perimeter + exact triangle-edge cut + paired inner/outer walls
  from full-body normals. The A fixture and the new Rigo-Cheneau reference profile pass
  manufacturing QA; orthotist visual/clinical validation remains.
- Visible-only unified-trim picker: occluded back-side controls cannot be selected through
  the corrected body. Ctrl+Z restores the last move, Esc restores the edit session, and
  Enter commits. The actual registered modal passed queued orthographic viewport events,
  retained a 1.499955 mm surface distance after the drag, and restored the session on Esc.
  Its view origin uses a scan/view-derived precision clamp followed by an unbounded BVH
  travel distance instead of the former fixed 1000-Blender-unit limit
  (`trimvisibilitytest`).
- Explicit **Edit Trimlines** and **Brace Preview** states. Thickness/offset/fairing,
  corrected-body, and perimeter changes mark the existing shell out of date; finishing,
  QA and export remain blocked until **Update Brace**. A shell missing either recorded
  source signature is out of date rather than grandfathered (`designviewtest`,
  `thicknesstest`).
- Collision-aware paired-wall generation: exact triangle intersection checks drive local
  outer-direction repair without changing the patient-contact inner surface or requested
  inner-to-outer pair distance. The current reference fixture generates 2/4/6 mm paired
  walls; independent bidirectional-ray medians are 1.999/3.999/5.998 mm and add-on QA
  minima are 1.740/3.654/5.386 mm. The 6 mm fixture repairs 25 outer-wall collision
  pairs to zero in seven passes with a maximum 18.287-degree direction change. Every
  generator exception cleans both private candidates and restores the prior view/outline
  state before return or propagation (`designviewtest` injected-failure phase).
- Paint-select region + push/thicken/smooth/delete (Edit-mode native)
- Landmarks (18 points)
- Bend / Twist / Stretch ✅ technically complete and user-validated: three draggable
  rings, localized Twist/Stretch, measurable Stretch (mm), Apply/Reset
- Scale girth, X-ray overlay
- Pressure/Relief **shape library** (place/edit/record/favourite/mirror/apply)
- Committed selection-region style library (save globally, import at cursor, edit/commit)
- Corset generate, editable trim line, strap slots, emboss

## Works but caveats (⚠)
- Free-form lattice cage (`correction_ops`) — present, not re-verified this session
- Hand remold sculpt (`remold_ops`) — sculpt-based, not the selection workflow
- Pad record stores control-point positions only (AUTO handles on respawn) — schema
  reserves optional `handles` for later fidelity
- A requested pair distance is a construction measurement, not the final QA minimum.
  Rim shaping and opposing-surface QA sampling can report a lower value; the
  2 mm reference run builds exact 2.000 mm pairs but correctly fails the configured QA
  threshold at a 1.740 mm sampled minimum.
- The 12 mm reference attempt and the B fixture stop before replacing the valid shell
  when exact outer-wall collisions remain. This safety behavior passes regression tests;
  it does not make B clinically ready.

## Agreed feature set (2026-06-13)
The brace workflow will mirror uFit's UX (adapted to spine). Full spec with reuse
mapping: **knowledge/requirements_v1.md** (Req 1–10). Summary below folds into it.

## Missing (⛔) — prioritized
- **P0 - Brace generator validation follow-up.** The default reference-oriented profile,
  millimetre opening, surface-slide editing, exact cut, paired wall, rim-aware thickness,
  visible-only trim-point picking, explicit TRIM/BRACE state, exact intersection gate,
  local outer-direction repair and stale-shell export gates are integrated. Signed
  correction-deviation preservation, a clinically accepted B strategy and orthotist
  clinical acceptance remain. `btrimlinetest` reports safe cancellation separately as
  `SAFETY_PASS`; its readiness and overall `PASS` remain false until generation and
  manufacturing QA succeed. Follow
  `BRACE_GENERATOR_DECISION_MAP.md` and `knowledge/brace_generator_research.md`.
- **P0 — Area-select → editable contour lines → carve/add (Rodin/LeoSpinal "Area").**
  Select a region ON THE MESH (not a button), see it as movable contour lines with
  multiple control points, drag them, then apply add (build-out) or carve (push-in).
  This is the active user request. Reuse: `select_ops` (selection), `design_ops`
  outline-curve + edit pattern, `deform_ops` draggable-handle+driver, `pad_ops`
  inside-outline displacement + feather.
- P1 — Manufacturing/export QA follow-up: persistent human-readable report, sharp-edge
  metric and naming/version evidence. Units, manifold, intersections, sampled minimum
  thickness and export blocking are done.
- P1 — Variable thickness / reinforcement zones (module 9 / MVP4).
- P2 — Lattice & ventilation library with safe-zone rules (module 10 / MVP4).
- P2 — Patient project workspace + version tracking (module 1 / MVP1).
- P3 — Components library: straps/buckles/rings/windows/labels (module 11).
- P3 — Clinically classified presets wired to landmarks remain missing; neutral
  orthotist-authored correction styles are implemented without automatic prescription.

## Cleanup (low priority, non-blocking)
- Deformation UI polish only: icons, names/labels, and visual ring shape. Preserve the
  validated deformation operators, masks, drivers, units, and test thresholds.
- Remove unused `SELECTION_VGROUP` import in `select_ops.py`; remove dead
  `select_symmetry` property in `core/__init__.py`.
- Delete stale root result files (`wstest_result.txt`, `hdr_result.txt`,
  `probe_result.txt`).
