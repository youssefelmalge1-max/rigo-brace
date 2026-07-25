# WASP-Med Feature Audit

Source: `D:\WASP-Med-master\WASP-Med-master\` · Author: **WASP** (2020) ·
Version 0.0.8 · Blender 2.91 · **License: GPL v2-or-later** (header block; no separate
LICENSE file) → **GPL-compatible with rigo_brace (GPL-3.0-or-later): may combine under
GPL-3.** See provenance PROV-0005. Repo: github.com/wasproject/Blender-WASP-Med.

## Phase 1 — Access classification
- GPL-2-or-later open-source → **safe to learn from, refactor, reuse**; when combined
  with our GPL-3 code the result is GPL-3. Preserve the WASP GPL header + attribution
  on any ported unit. No proprietary/cloud entanglements (cleaner than uFit that way).
- Old API (Blender 2.91): some calls need updating for 5.0 (operator overrides,
  `bpy.ops.transform` orientation args). Treat as **reference**, port carefully.

## Phase 2 — Architecture
- Flat module set, one concern each: `waspmed_scan.py` (31 KB), `waspmed_generate.py`
  (17 KB), `waspmed_crop.py` (16 KB), `waspmed_deform.py` (11 KB), `waspmed_sculpt.py`
  (7 KB), `waspmed_print.py`, `utils.py`. Single `__init__.py` registers all classes;
  `Object.waspmed_prop` + `Scene.waspmed_prop` property groups.
- Step progress via `WASPMED_PT_progress` + per-area panels (Scan/Sculpt/Generate/
  Crop/Deform/Print). Straightforward `bpy.types.Operator` + `Panel` (no fat-core
  indirection) — closest in spirit to rigo_brace's own structure.

## Phase 3 — Feature matrix (most relevant first)

### ⭐ Rotate Sections — progressive lattice derotation (spinal!)
- **Behavior:** on a Lattice, exposes up to 10 per-section rotation sliders (r0..r9).
  `execute` selects each w-layer of lattice points in turn and rotates it by its angle,
  so the model twists progressively along its height.
- **File:** `waspmed_deform.py: OBJECT_OT_wm_rotate_sections` (+ `add_lattice_to_object`,
  `edit_lattice`).
- **Clinical purpose:** **transverse-plane derotation** of the torso along the spine —
  exactly the Rigo correction; more granular than our single-axis TWIST.
- **Blender method:** lattice points grouped by w-layer; `transform.rotate` per layer.
- **Reuse:** strong candidate to upgrade rigo `deform_ops` TWIST / `correction_ops`
  cage into a **multi-section derotation** tool. Learn-from + port the layer-selection
  loop (update 2.91 transform calls for 5.0).

### ⭐ Weight Thickness — variable wall thickness from weight paint
- **Behavior:** weight-paint the shell (blue→red), then `weight_thickness(min, max)`
  builds a wall whose thickness varies with the painted weight via 24 iso-contour cuts
  between iso 0.25–0.75; helper `set_weight_paint`, `weight_add_subtract`,
  `smooth_weight`.
- **File:** `waspmed_generate.py`.
- **Clinical purpose:** reinforcement zones (thicker at pelvic anchor / thoracic
  pressure, thinner at expansion rooms).
- **Reuse:** primary reference for **MVP4 variable thickness/reinforcement**. Different
  approach from uFit (weight-paint + iso-cuts vs vertex-color + solidify) — WASP's is
  truer "gradient thickness".

### Scan prep & measurement
- `waspmed_scan.py`: `wm_setup`, `auto_origin`, `rebuild_mesh` (remesh), `cap_holes`,
  `add_measure_plane` + `measure_circumference`, `check_differences` (before/after
  deviation map), next/back step nav.
- **Reuse:** `check_differences` (deviation/color map of how far the corrected mesh
  moved from the scan) is a **clinically valuable QA view we lack**; `measure_*` feeds
  the measurements module; `cap_holes`/`rebuild_mesh` parallel our fill/remesh.

### Crop by planes
- `waspmed_crop.py`: `define_crop_planes` + `crop_geometry` — plane-based trimming.
  Reuse: alternative to our box-erase for clean top/bottom cuts.

### Sculpt brushes
- `waspmed_sculpt.py`: `set_sculpt/set_draw/set_smooth/set_grab` — thin wrappers that
  switch sculpt brushes. Reuse: minor; our remold already does this.

## Phase 4 — Gap analysis vs rigo_brace
- WASP fills two of our biggest ⛔ gaps with proven, GPL-compatible code:
  **multi-section derotation** (`rotate_sections`) and **variable thickness**
  (`weight_thickness`), plus a **before/after deviation map** (`check_differences`)
  we should add for QA.
- WASP is Blender 2.91 — port, don't paste: update transform/lattice/override calls
  for 5.0, and re-test.

## Reuse decision summary
| WASP unit | Action | Target |
|---|---|---|
| `rotate_sections` (per-layer lattice rotation) | learn-from + port | derotation upgrade (MVP2) |
| `weight_thickness` + weight paint helpers | learn-from + port | variable thickness (MVP4) |
| `check_differences` deviation map | learn-from + reimplement | QA view (MVP5) |
| `measure_circumference` / `add_measure_plane` | learn-from | measurements module |
| `crop_geometry` plane crop | learn-from | scan cleanup option |
| sculpt brush wrappers | ignore (already have) | — |
