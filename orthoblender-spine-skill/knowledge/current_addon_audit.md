# Current Add-on Audit — `rigo_brace`

_Audit date: 2026-06-13; full contract refresh 2026-07-12; trim/state/thickness
correction 2026-07-13. Scope: the only add-on in this repo. No uFit/WASP source is
present (those remain feature-audit-only targets if code is provided later)._

## 1. Repository structure
```
Blender Add-on Braces/
  rigo_brace/                 # the extension (GPL-3.0, user-owned)
    blender_manifest.toml
    __init__.py               # register order: core → operators → ui → keymaps
    core/__init__.py          # RigoBraceSettings, LANDMARKS, WORKFLOW_TABS, consts
    core/pad_library.py       # persistent pad shape library (JSON, per-PC)
    core/signatures.py        # source-record completeness + evaluated geometry hashes
    operators/                # io, scan, mesh, landmark, remold, deform, pad,
                              #   correction, trimline, design, exact intersections,
                              #   QA, select, ui
    ui/panels.py              # RIGO_PT_main 5-stage wizard + tool-header step bar
    ui/icons.py
    keymaps.py                # Alt+<key> for paint-select tools
  rigo_brace_template/        # Blender application template (clean single-viewport)
  tools/                      # GUI + headless test scripts (see CLAUDE.md)
  build.py · install.ps1      # zip build / local dev install + startup.blend bake
  Leospinal tutorial.md       # reference transcript (NOT code)
  knowledge/ · SKILL.md       # this knowledge system
```

## 2. Add-ons detected & license
| Item | Type | License | Status |
|---|---|---|---|
| `rigo_brace` | Blender extension | SPDX:GPL-3.0-or-later (manifest) | **User-owned → authorized for modification** |
| `rigo_brace_template` | App template | (ships with add-on) | User-owned |
| `Leospinal tutorial.md` | Text transcript | Reference only | Feature-level learning only; not code |
| uFit / WASP | — | — | **Not present in repo** |

File classification: all `rigo_brace/**` and `tools/**` are **safe to modify**
(user-owned). No third-party add-on code is present, so nothing is "do not copy".

## 3. Architecture map
- **Registration** (`__init__.py`): fans out `register()` in strict order
  core→operators→ui→keymaps (keymaps reference operator bl_idnames, must be last).
- **Settings** (`core/__init__.py`): one `RigoBraceSettings` PropertyGroup mounted at
  `Scene.rigo_brace` — every UI tunable, all mm. Constants: `LANDMARKS`,
  `WORKFLOW_TABS` (5 stages), object/collection names (`CORSET_NAME`,
  `OUTLINE_CURVE_NAME`, `DEFORM_*`, `PAD_*`).
- **Derived-state provenance** (`core/signatures.py`): complete scan/perimeter source
  record and evaluated-geometry signatures used by finishing, QA and export freshness
  gates.
- **Library** (`core/pad_library.py`): JSON pad-shape library in the user config dir,
  module-cached enum items.
- **Operators** (`rigo.` prefix): one module per pipeline area.
- **Exact intersections** (`operators/mesh_intersections.py`): BVH broad phase followed
  by coplanar/non-coplanar triangle checks, including overlap beyond shared topology.
- **UI** (`ui/panels.py`): `RIGO_PT_main` draws a 5-stage wizard via `_STAGE_DRAW`;
  same step bar appended to `VIEW3D_HT_tool_header`. `_draw_select_box` shared by
  Scan/Mesh/Design stages.
- **Template** (`rigo_brace_template/__init__.py`): defers all setup to retrying
  `bpy.app.timers` (extension system not ready at template register). Screen layout +
  METRIC/MILLIMETERS units baked into `startup.blend` by `tools/build_startup_gui.py`.

## 4. Feature matrix (observed, current build)
Legend: ✅ working & tested · ⚠ working with caveat · ⛔ missing.

| Feature | Module | Geometry op | Status | Notes / test |
|---|---|---|---|---|
| Import scan / export brace | io_ops | wm.stl/obj | ✅ | A new patient import removes the prior patient-specific trim curves, marks any shell stale and returns to TRIM; Generate also rejects a perimeter whose Shrinkwrap target is not the current scan |
| Apply scan units (mm/cm/m) | scan_ops | object scale + apply | ✅ | fixed "model disappears" (re-frame view, double-apply guard); `applyunitstest` |
| Realign / move / recenter-floor | scan_ops | tool_set, origin_set | ✅ | — |
| Fill holes / box-erase / remesh / smooth | scan_ops, mesh_ops | bmesh, modifiers | ✅ | `scancleantest` |
| Paint-select area (Edit-mode native) | select_ops | circle-select ADD, face sel | ✅ | fixed persistence + ADD mode; `selecttest`, `paintkeeptest`, `painttooltest` |
| Push out/in · thicken · smooth · delete (region) | select_ops | shrink_fatten, solidify, etc. | ✅ | interactive + bmesh fallback |
| Landmarks (pick on scan / place / clear) | landmark_ops | raycast empties | ✅ | 18 anatomical points |
| Bend (coronal) | deform_ops | Simple Deform BEND axis Y | ✅ **complete** | user-validated; three draggable rings; `segmentdeformtest`, `bendtest` |
| Twist (derotate) | deform_ops | Simple Deform TWIST axis Z + live mask | ✅ **complete** | user-validated; outside active rings fixed |
| Stretch (elongate) | deform_ops | Simple Deform STRETCH Z + live mask | ✅ **complete** | user-validated; millimetres; requested/measured 40.00/40.00 mm |
| Deform segment rings | deform_ops, core | 3 draggable discs + pair drivers | ✅ **complete** | Lower/Middle/Upper; UI appearance polish deferred |
| Scale girth (inflate/deflate) | deform_ops | object scale X/Y | ✅ | — |
| X-ray overlay import/opacity/reposition | deform_ops | empty image | ✅ | — |
| Free-form lattice cage | correction_ops | Lattice modifier | ⚠ | present; not re-verified this session |
| Remold by hand (sculpt) | remold_ops | sculpt brush | ⚠ | present; sculpt path, not the selection workflow user wants |
| **Pressure/Relief shape library** | pad_ops, pad_library | draped Bezier outline + normal displace w/ feather | ✅ | NEW: place/edit/record/favourite/mirror/apply; `padtest`, `padshapetest` |
| **Selection correction style library** | region_ops, region_library | surface-local weighted mask + live normal preview | ✅ | committed save/JSON reload/different-topology import; `regionstyletest` |
| Generate corset shell | design_ops, mesh_intersections | exact perimeter clip + paired inner/outer walls + explicit rim | ✅/⚠ | A/reference requests at 2/4/6 mm generate technically; 2 mm fails the configured sampled-minimum QA; B remains safely blocked before replacement |
| Unified perimeter trimline editing | trimline_ops | surface raycast + visible-only point pick + Shrinkwrap | ✅ | Back-side points are rejected; Ctrl+Z restores the last move, Esc the session, Enter commits; `trimvisibilitytest`, `trimlinetest`, `referencetrimtest` |
| Legacy top trim line (outline) | design_ops | Bezier curve → variable-height cut | ⚠ | Hidden from the clinical UI; `outlinetest` retained for saved-file compatibility |
| Design state / stale-brace guard | core, design_ops, qa_ops, io_ops | explicit TRIM/BRACE view + complete source signatures | ✅ | `brace_ready_for_finishing` is the canonical UI/operator gate; parameter, corrected-body or perimeter changes mark the shell out of date; a missing scan or trim signature is also stale; finishing/QA/export remain blocked until Update Brace; legacy shells show built thickness as unknown, not 0 mm; `designviewtest`, `thicknesstest` |
| Strap slots / emboss | design_ops | boolean cutters / text | ✅ | — |
| **Area-select → editable contour lines → carve** | — | — | ⛔ | **the current request (Rodin/LeoSpinal "Area" tool)** |
| Reinforcement / variable thickness | — | — | ⛔ | roadmap MVP4 |
| Lattice / ventilation library | — | — | ⛔ | roadmap MVP4 |
| Components library (straps/buckles/rings) | — | — | ⛔ | roadmap |
| Patient project / versioning | — | — | ⛔ | roadmap MVP1 |
| Export/manufacturing QA (manifold/thickness/units) | qa_ops, io_ops | evaluated mesh gates + canonical STL | ✅ | `qatest`, `exporttest`; reruns before export |

2026-07-13 correction: manufacturing QA is implemented in `qa_ops.py` and blocks
export on units, component, boundary/non-manifold, zero-area, inverted-volume,
self-intersection or configurable sampled-minimum-thickness failure. The clinical
trim workflow is consolidated to one unified perimeter; duplicate top-only outline and
standalone-thickness controls are hidden. Full matrix: `ADDON_FEATURE_AUDIT_2026-07-12.md`.

The editor now ray-tests candidate controls against the corrected body from the active
view, so an occluded back-side point cannot be selected through the scan. Ctrl+Z restores
the last committed point move, Esc restores the complete edit-session snapshot, and
Enter commits. `trimvisibilitytest.py` retains the transformed-scan visibility kernel,
then invokes the registered modal operator, queues viewport-window press/move/release
events at a click deliberately closer to the hidden control, verifies only the visible
control moves, and queues Esc to restore the full snapshot and prior in-front state. The
modal runs in orthographic view and measures the moved point 1.499955 mm from the body.
Its view-ray origin is clamped to a scan/view-derived distance for precision and the BVH
travel distance is unbounded, replacing the former fixed 1000-Blender-unit limit without
leaving the origin at the 100 km far clip.

The default `Rigo-Cheneau Reference` trim is an independent parametric profile informed
by internal visual study of the supplied commercial reference, not copied vertices. Its
opening is in millimetres. `Edit on Body` raycasts each drag and live Shrinkwrap holds
the evaluated curve 1.500 mm from the corrected body; `Fit` repairs older/floating
points. Generate builds paired walls from the uncut corrected-surface normal field,
then bridges and rounds one explicit rim. If exact triangle tests find outer-wall
overlap, only the involved outer direction vectors are relaxed within the configured
repair limits; the inner patient-contact surface and requested inner-to-outer pair
distance remain unchanged. In the installed reference fixture, 2/4/6 mm requests
produce exact paired distances of 2.000/4.000/6.000 mm. An independent bidirectional-ray
sampler reports medians of 1.999/3.999/5.998 mm, while the add-on QA sampler reports
minima of 1.740/3.654/5.386 mm. The 2 mm shell therefore fails the configured QA minimum.
The 6 mm case repairs 25 exact outer-wall collision pairs to zero in seven passes with a
maximum 18.287-degree direction change. A 12 mm reference attempt cancels safely with
the valid 6 mm shell/base retained. The 4 mm B fixture also cancels safely; this is
`SAFETY_PASS=True`, not readiness (`READINESS_PASS=False`, overall `PASS=False`). All
generator exceptions remove private candidates and restore the prior view/outline state
before a known overlap is reported or an unexpected error propagates. B clinical
readiness remains unresolved.

## 5. Gap analysis
- **Works:** the reference/A Phase-0→2 technical path (import→scan prep→landmarks→
  deform→pads→corset) is regression-tested via `tools/`; dirty-state gates prevent a
  stale shell from entering finishing, QA or export.
- **Works but caveats:** free-form cage & hand-remold present but not re-verified;
  pad-record stores control-point positions only (AUTO handles on respawn).
- **Missing (highest user value first):** orthotist validation and a clinically accepted
  B-specific trim/surface strategy; signed corrected-surface deviation reporting;
  Rodin-style **area-select → editable contour lines → apply add/carve**; variable
  thickness/reinforcement; patient project workspace; components library; 3MF/report
  output. Manufacturing QA and ventilation are implemented. The B safety-cancellation
  regression is a guardrail, not evidence that a B brace is ready.

## 6. Reusable code candidates (for the area-select feature)
- `select_ops.py` — Edit-mode native paint-select already gives **mesh-based region
  selection** (the "select by mesh, not button" the user wants) + X-ray-off front-
  face painting + grow/shrink/invert.
- `deform_ops.py` `_make_plane_disc` / `_drive_range` / driver pattern — the
  **draggable handle + live driver** mechanism for movable control lines.
- `design_ops.py` `_make_outline_curve`, `_outline_profile`, `RIGO_OT_edit_outline`
  — **editable Bezier contour with control points** + read-back to a profile.
- `pad_ops.py` `_drape_point`, `_sample_pad_boundary`, `_inside_2d`, smoothstep
  feather, KDTree distance — **apply displacement inside a closed outline** (directly
  reusable for "carve the selected area").
These four already contain ~90% of the machinery; the missing piece is generating
**editable section/contour curves from a painted selection** and pulling them.

## 7. Unsafe / unclear code
None. No third-party code present; everything is user-owned GPL.

## 8. Refactor observations (non-urgent)
- `select_ops.py` still imports unused `SELECTION_VGROUP`; `core` has dead
  `select_symmetry`. Cleanup-only (logged in backlog), not blocking.
- Several stale result/probe files at root (`wstest_result.txt`, `hdr_result.txt`,
  `probe_result.txt`) from earlier experiments — harmless.
