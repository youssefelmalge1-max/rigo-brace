# Developer Architecture

See also the add-on's own `../../CLAUDE.md` (build/install/test) and
`knowledge/blender_api_map.md` (operator/panel/state index).

## Two installable pieces
- `rigo_brace/` — the Blender extension (`blender_manifest.toml`). `__init__.py` fans out
  `register()` strictly `core → operators → ui → keymaps` (keymaps reference operator
  bl_idnames, so last).
- `rigo_brace_template/` — application template giving the orthotist a stripped single-
  viewport UI. Its `register()` runs before the extension system is ready, so all setup
  (enable add-on, delete extra workspaces, theme) is deferred onto retrying
  `bpy.app.timers` callbacks. Screen layout + METRIC/MILLIMETERS units are baked into a
  pre-built `startup.blend` (tools/build_startup_gui.py).

## Inside the add-on
- `core/__init__.py` — `RigoBraceSettings` (all mm UI props) at `Scene.rigo_brace`;
  constants LANDMARKS, WORKFLOW_TABS, BRACE_STAGES (+ helpers), object/collection names.
- `core/pad_library.py` — per-PC json pad-shape library (cached dynamic enum).
- `operators/` — one module per area; all `rigo.` idnames. ui_ops (nav + view),
  history_ops (design history), io/scan/mesh/landmark/deform/pad/correction/design/select.
- `ui/panels.py` — RIGO_PT_workflow (shell), RIGO_PT_main (wizard), RIGO_PT_view,
  RIGO_PT_view_options; step bar also on VIEW3D_HT_tool_header.

## Patterns to reuse
- **Live modifier from sliders**: PropertyGroup `update=` callbacks (deform, xray, pad
  prefill).
- **Draggable helper → driven modifier**: SCRIPTED drivers connect the active pair of
  Lower/Middle/Upper deform rings to one modifier interval.
- **Editable outline**: Bezier curve + control points (trim line, pad shapes); sample the
  *evaluated* curve for AUTO handles.
- **Region edit**: paint/select faces → shrink_fatten / proportional → grow+smooth feather.
- **Design history**: object snapshots `NN_<patient>_<stage>` + custom props
  (rigo_patient/rigo_stage) in a per-patient collection (history_ops, ported from WASP).
- **Surface placement**: object-space ray_cast / closest_point_on_mesh.

## Conventions
1 BU = 1 m; UI mm (`*0.001`). Mutating operators carry `{"REGISTER","UNDO"}`. Operators
provide an `execute()` path (headless-testable) alongside any `invoke()` modal. View/screen
ops use `context.temp_override(area, region=WINDOW, space_data)`.

## Testing & provenance
GUI Blender tests in `../../tools/*test.py` → `<name>_result.txt`; install first. Reuse
from uFit/WASP is logged in `knowledge/code_provenance.md` with GPL attribution.

## Build order
See `knowledge/roadmap.md` + the active plan. Shipped: View (P1), Workflow shell +
history (P2). Next: Clean (center + auto-remesh + verify).
