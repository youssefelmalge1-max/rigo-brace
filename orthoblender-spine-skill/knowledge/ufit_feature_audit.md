# uFit Feature Audit

Source: `D:\ufit-blender-master\ufit-blender-master\` · Author: **Ugani Prosthetics** ·
Version 2.2.2 · Blender 3.5 · **License: GPL-3.0** (full GPLv3 + README) →
**GPL-compatible with rigo_brace (GPL-3.0-or-later); reuse allowed with provenance +
notice preservation.** See provenance PROV-0004.

## Phase 1 — Access classification
- Whole project: GPL-3.0, open-source → **safe to learn from, refactor, and reuse**
  (preserve GPL headers/attribution; document provenance per reused unit).
- Caveat: contains **cloud authentication / platform login** (`authenticate.py`,
  `platform.py`, `wetransfertool.py`) tied to Ugani's service — **ignore/do not port**
  (irrelevant + external dependency).

## Phase 2 — Architecture
- Devices as modules: `base`, `transtibial`, `transfemoral`, `free_sculpting`,
  `patches`. Each device defines a **numbered step workflow** `ST_<n>_<name>` driven by
  `scene.ufit_active_step`; per step a thin `OT_*` operator + `UI_*` panel.
- **Thin operator → fat core** pattern: `base/src/operators/base/OT_*.py` delegate to
  `base/src/operators/core/*.py` (the real logic): `sculpt.py` (35 KB, push/pull/
  smooth/cutout/scale/thickness/flare), `alignment.py` (21 KB), `prepare.py` (19 KB),
  `finish.py`, `start.py`.
- Utilities: `utils/general.py` (40 KB), `color_attributes.py` (vertex-color region
  selection), `nodes.py` (shader nodes for the paint overlay), `annotations.py`,
  `user_interface.py`.
- Relies on bundled Blender add-ons (looptools, tissue, print3d_utils, importers).

## Phase 3 — Feature matrix (most relevant to spinal brace work)

### ⭐ Region push/pull/smooth by PAINTED SELECTION — the user's "area carve"
- **Behavior:** object in `VERTEX_PAINT` mode; paint a region with a green brush onto
  a `area_selection` color attribute (white = unselected). Push/Pull moves the painted
  verts along face normals by `ufit_extrude_amount` mm; then grows the region and
  `vertices_smooth` for a feathered boundary. A **circular** variant uses proportional
  editing (NORMAL orient) from the region's center vertex with `proportional_size =
  radius` for a smooth radial dome.
- **Files:** `core/sculpt.py` `push_pull_region`, `push_pull_region_circular`,
  `smooth_region`, `push_pull_smooth_done`; selection via
  `utils/color_attributes.select_vertices_by_color_exclude` +
  `general.move_verts_along_faces_normal`.
- **Clinical purpose:** localized pressure/relief shaping (our pad/area feature).
- **Blender method:** vertex-color attribute + `bmesh`/`transform.translate` with
  proportional edit; grow+smooth for transitions.
- **Reuse for rigo_brace:** strong reference for the **P0 Area-Select → carve/add**.
  Our `select_ops.py` already does the Edit-mode-face equivalent; uFit confirms the
  **grow-then-smooth boundary** and the **circular proportional-edit dome** as proven
  techniques to adopt. Reuse = learn-from + optionally port `push_pull_region_circular`
  math.

### Circumference / dimension measurement (the H/AP/ML/Cir readout)
- `OT_circumference_length.py` (15 KB), `OT_autocalculate_length.py`,
  `core/prepare.py: remeasure_circumferences` — measures girth at section planes and
  re-measures live after each edit.
- Reuse: basis for a **measurements module** (we only show bbox H + Ramanujan girth).

### Variable / custom print thickness over a painted region
- `core/sculpt.py: create_custom_thickness`, `create_printing_thickness`,
  `OT_custom_thickness.py` — paint a region → local wall thickness.
- Reuse: MVP4 reinforcement / variable thickness.

### Trim line / cutout
- `core/sculpt.py: create_cutout_line/plane/path`, `perform_cutout` — draw + project a
  cut line and slice the shell. Reuse: complements our editable outline trim.

### Scale, pull-bottom, flare, milling, connector, alignment, clean-up
- `scale` (mm or %), `pull_bottom`, `flare`, `create_milling_model`, `OT_connector`,
  `alignment.py` (auto-orient), `OT_clean_up`. Reuse: scale-by-mm and clean-up ideas.

## Phase 4 — Gap analysis vs rigo_brace
- uFit is **prosthetics (sockets)**, not spinal, but its **region-paint→deform**,
  **live circumference measurement**, and **variable thickness** map directly onto our
  roadmap (P0 area-carve, measurements, MVP4 reinforcement).
- Architecture lesson: the **thin-operator → fat-core + numbered-step workflow** scales
  to many device types — worth considering as we add foot/AFO later. Our single-panel
  wizard is simpler and fine for spine MVP.
- Do **not** adopt: cloud auth, `.ini` debug harness, importlib reload patching.

## Reuse decision summary
| uFit unit | Action | Target |
|---|---|---|
| `push_pull_region_circular` (proportional dome) | learn-from / optional port | rigo area-carve |
| grow-region-then-smooth boundary | learn-from | rigo area-carve feather |
| circumference remeasure | learn-from / reimplement | measurements module |
| custom thickness over painted region | learn-from | MVP4 reinforcement |
| auth / platform / ini / reload patch | ignore | — |
