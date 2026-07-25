# Requirements v1 — Brace workflow adopted from uFit (+ WASP)

Recorded 2026-06-13 from the user's walkthrough of uFit 2.2.2 (Transtibial) screens.
Goal: rebuild the rigo_brace workflow to mirror uFit's UX, adapted to **spinal
braces**. uFit & WASP are GPL (compatible) → learn-from / port with provenance
(PROV-0004/0005). Each item: what uFit/WASP does · brace adaptation · reuse source ·
existing rigo code · MVP priority.

## The uFit workflow shell (applies across all steps)
A persistent right-side panel with these sections, shown on every step:
- **View** — Full Screen · Quad View · Ortho View checkboxes.
- **View Modes** — Top / Front / Left / Right / Back / Bottom buttons.
- **Checkpoints** — dropdown of completed stages + **Rollback** (revert to a stage).
- **Assistance** — an **image + text hint** per step (beginner guidance).
- **Progress** — % through the workflow.
- **Top header tools** — Annotation (color/label, Placement=Surface, Radius, Factor,
  Stabilize Stroke), Select (Box/Lasso, Radius), transform gizmos.
- Per-step section at the bottom with **Back / Next**.

Brace adaptation: same shell; **Checkpoints = the clinical workflow stages**
(see Req 4). Our current single `RIGO_PT_main` 5-stage wizard
([ui/panels.py](rigo_brace/ui/panels.py)) is replaced/extended by this shell.

---

## Req 1 — Import STL / OBJ (as uFit)
- uFit: import scan step.
- Brace: identical; already implemented.
- Existing: `rigo.import_scan` ([operators/io_ops.py](rigo_brace/operators/io_ops.py)).
- Priority: ✅ have. Action: keep; place as first workflow step.

## Req 2 — Quad view, Ortho view, Full Screen
- uFit: View checkboxes (Full Screen / Quad / Ortho) + View Modes buttons.
- Brace: same — crucial for alignment (Req 6).
- Reuse: uFit `utils/user_interface.py` (`open_n_sidebar`, view helpers); Blender
  `screen.area_quadview`, `view3d.view_axis`, fullscreen toggle.
- Existing: partial — we bake one viewport in `startup.blend`; `rigo.toggle_ortho`
  exists in [operators/ui_ops.py](rigo_brace/operators/ui_ops.py).
- Priority: P1 — new **View panel** + Quad/Fullscreen operators.

## Req 3 — Clean tab (as Ugani)
- uFit: Clean Up step — scan noise/island removal.
- Brace: same.
- Reuse: WASP `rebuild_mesh`/`cap_holes`; uFit clean-up; Blender remesh/decimate.
- Existing: `rigo.fill_holes`, `rigo.remesh`, `rigo.smooth`, `rigo.erase_toggle`
  ([operators/scan_ops.py](rigo_brace/operators/scan_ops.py), mesh_ops.py).
- Priority: ✅ mostly have; reorganize into the Clean step + selection (Req 4).

## Req 4 — View Modes + Checkpoints + Assistance + Progress + Annotation + top tools; select-by-paint that continues with Shift+Right-Click
- uFit: Checkpoints (named stages + rollback); Assistance image+text; Progress %;
  Annotation tool + top toolbar; Clean-up selection = **hold Left-Click to select,
  SHIFT to add, CTRL to remove**.
- Brace adaptations:
  - **Checkpoints = anatomical/workflow stages**; record all **anatomical areas** as
    reference checkpoints (C7, axilla, scapula, thoracic/lumbar apex, iliac crest,
    ASIS/PSIS, trochanter, waistline — we already define these as `LANDMARKS`).
  - **Assistance** panel with a **picture + guidance text per step** for beginners.
  - **Progress** bar across the brace workflow.
  - **Annotation** + all top tools available.
  - **Continue-selecting**: press Select, then **Shift+Right-Click adds** to the
    painted region (and Ctrl removes) — accumulate, don't reset.
- Reuse: uFit Checkpoints (`OT_steps_checkpoints.py`, `core/checkpoints.py`),
  Assistance/Progress (`utils/user_interface.py`), annotation (`utils/annotations.py`),
  color-region select (`utils/color_attributes.py`).
- Existing: `LANDMARKS`, `WORKFLOW_TABS` in [core/__init__.py](rigo_brace/core/__init__.py);
  accumulate-paint already solved in [operators/select_ops.py](rigo_brace/operators/select_ops.py)
  (LM-0002). Landmarks in [operators/landmark_ops.py](rigo_brace/operators/landmark_ops.py).
- Priority: P1 (shell: Checkpoints/Assistance/Progress) — biggest structural change.

## Req 5 — Re-check the cleaned area before closing the mesh
- uFit: **Verify Clean Up** step — highlights potential issues (orange) before commit.
- Brace: same gate before capping/closing the mesh.
- Reuse: uFit verify-clean-up step; WASP `check_differences` (deviation map idea).
- Existing: none (we cap/remesh directly). 
- Priority: P2 — add a verify/highlight step.

## Req 6 — Alignment with Quad View
- uFit: quad orthographic view + rotation rings to face the scan front; great for braces.
- Brace: same — align torso to anatomical axes in quad view.
- Reuse: uFit `alignment.py` (auto-orient) + rotation gizmo; Blender quad view.
- Existing: `rigo.realign_tool`, `rigo.move_tool`, `rigo.recenter_floor`
  ([operators/scan_ops.py](rigo_brace/operators/scan_ops.py)).
- Priority: P1 — pairs with Req 2 quad view.

## Req 7 — Circumference tool at selected SPINE levels (not auto-spaced)
- uFit: add first circumference, then auto-spaced downward by Distance; table shows
  Init / Sculpt / Liner per ring.
- Brace adaptation: instead of even spacing, **measure circumference at chosen
  anatomical levels**: GT (greater trochanter), Waist, below-chest (subcostal),
  nipple (mid-thoracic), armpit (axilla). Keep the Init/Sculpt(/Liner) comparison
  table that **remeasures live** after each edit.
- Reuse: uFit `OT_circumference_length.py`, `OT_autocalculate_length.py`,
  `core/prepare.py: remeasure_circumferences`; WASP `add_measure_plane`/
  `measure_circumference`.
- Existing: only bbox H + Ramanujan girth estimate in panels.py; landmarks give the
  levels.
- Priority: P2 — **measurements module** keyed to landmark levels.

## Req 8 — ⭐ Measurable highlight push/pull sculpt (exploit Blender 5 sculpt)
- uFit: **Guided** sculpt — highlight a region, then **Push/Pull by an Amount in mm**
  (+ Circular Push/Pull, Smooth); plus a **Free** sculpt mode.
- Brace: the core shaping tool — highlight an area, push/pull a **measured mm** amount;
  exploit Blender 5's stronger sculpt for Free mode. This IS the area-carve feature.
- Reuse: uFit `core/sculpt.py` `push_pull_region`, `push_pull_region_circular`,
  `smooth_region` (grow+smooth feather; circular = proportional-edit dome).
- Existing: [operators/select_ops.py](rigo_brace/operators/select_ops.py) already does
  Edit-mode region push/pull/smooth in mm; pad feather/inside logic in
  [operators/pad_ops.py](rigo_brace/operators/pad_ops.py).
- Priority: **P0** — the originally requested feature; closest to done.

## Req 9 — Manual trim lines (MVP1; automatic later) + X-ray + flared width
- uFit: place trim-line points → edit a point with **Left-Click, G, move, Left-Click**
  to stop (we'll use right-click per the user); **X-ray** transparency while editing;
  Free / Straight modes.
- Brace: manual editable trim line is enough for MVP1. Add **X-ray view** and a
  **trim-line width that flares** the cut edge for a smooth finish.
- Reuse: uFit `core/sculpt.py` cutout line/plane/path; our own outline tool is close.
- Existing: ⭐ `rigo.edit_outline`/`apply_outline`/`reset_outline` + `_make_outline_curve`
  ([operators/design_ops.py](rigo_brace/operators/design_ops.py)) — editable Bezier
  trim already implemented.
- Priority: P1 — add X-ray toggle + flared edge to the existing outline tool.

## Req 10 — Keep-part selection → scale → unified thickness → flare %
- uFit: **Part Selection** (keep Part 1/2) → **Scaling** (mm or %) → **Base/Unified
  Thickness** (+ Custom Thickness over a highlighted region) → **Flare %** for safe
  trim edges.
- Brace: after trimming, choose the part to keep (the brace shell), scale, apply
  **unified thickness**, then **flare the trim edge by a percentage** for safety.
- Reuse: uFit `core/sculpt.py` scale (`perc_scaling`/`mm_scaling`), thickness
  (`create_printing_thickness`/`create_custom_thickness`), `flare`; WASP
  `weight_thickness` (variable thickness, later).
- Existing: `rigo.scale_girth` (deform_ops), `rigo.thickness` + corset solidify
  ([operators/design_ops.py](rigo_brace/operators/design_ops.py)).
- Priority: P1 thickness/scale (mostly have) · P2 part-selection + flare-% edge.

---

## Build sequencing (recommended)
1. **P0** — Req 8 measurable highlight push/pull sculpt (area-carve). Smallest, reuses
   most; the original ask.
2. **P1 shell** — Req 2/4/6: View panel (quad/ortho/fullscreen) + Checkpoints +
   Assistance(image) + Progress + alignment-in-quad. The structural backbone.
3. **P1** — Req 9 trim-line X-ray + flared width; Req 10 scale + unified thickness.
4. **P2** — Req 5 verify-clean gate; Req 7 spine-level circumferences; Req 10
   part-selection + flare-% edge.
5. Later — WASP multi-section derotation; WASP/uFit variable thickness; deviation-map QA.

## Open scope question (for the user)
Replace the current 5-stage wizard UI wholesale with the uFit-style shell, or layer the
shell features onto the existing panel incrementally? (Affects all sequencing.)
