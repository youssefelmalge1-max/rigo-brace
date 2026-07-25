# Blender API Map (quick reference for rigo_brace)

Add-on registration order (rigo_brace/__init__.py): `core → operators → ui → keymaps`
(keymaps last; they reference operator bl_idnames).

## Operators (all `rigo.` prefix; one module per area in operators/)
- ui_ops: set_tab, step_tab, toggle_ground/landmarks/ortho/measure, **view_axis,
  toggle_quadview, toggle_fullscreen, align_quad**, setup_workspaces.
- history_ops (NEW): **stage_next, stage_back, rollback** (design history).
- io_ops: import_scan, export_brace.
- scan_ops: apply_units, realign_tool, move_tool, recenter_floor, fill_holes,
  erase_toggle.
- mesh_ops: remesh, smooth, thickness.
- landmark_ops: pick_landmark, place_landmark, clear_landmarks.
- deform_ops: deform_start (BEND/TWIST/STRETCH), deform_apply, deform_reset,
  pick_deform_range, scale_girth, import_xray, xray_grab.
- pad_ops: place_pad, add_pad, edit_pad, update_pad, mirror_pads, clear_pads,
  record_pad_shape, set_pad_favourite, delete_pad_entry, apply_pads.
- correction_ops: build/edit/apply/reset correction cage (lattice).
- design_ops: generate_corset, edit/apply/reset_outline, place/cut/clear_slots,
  emboss_text.
- select_ops: paint_select, select_grow/shrink/clear/invert, push_selection,
  thicken/smooth/delete_selection.

## Panels (ui/panels.py, N-panel category "Rigo Brace")
RIGO_PT_workflow (shell: progress/assistance/history) · RIGO_PT_main (5-stage wizard) ·
RIGO_PT_view (quad/ortho/fullscreen + view modes) · RIGO_PT_view_options. Step bar also
appended to VIEW3D_HT_tool_header (compat lookup `_tool_header_type`).

## Core state (core/__init__.py)
`Scene.rigo_brace` = RigoBraceSettings (all mm-denominated UI props). Constants:
LANDMARKS, WORKFLOW_TABS, **BRACE_STAGES** + helpers (brace_stage_index/label/assist),
object/collection names (CORSET_NAME, OUTLINE_CURVE_NAME, DEFORM_*, PAD_*). Pad library:
core/pad_library.py (json, cached enum).

## Custom props (per-object state)
- History: `rigo_patient` (str), `rigo_stage` (int).
- Pads: `rigo_pad_id`, `rigo_kind`, `rigo_depth`, `rigo_twin_of`.
- Deform: `rigo_deform_zmin`, `rigo_deform_zspan`.

## Context override gotcha
View/screen ops need `context.temp_override(area=, region=WINDOW, space_data=)`. The
N-panel lives inside the VIEW_3D area, so `context.area` is usually that area.

## Units convention
1 Blender unit = 1 m; all UI in mm; operators convert `* 0.001`. startup.blend baked to
METRIC/MILLIMETERS so interactive readouts show mm.

## Testing
GUI Blender only (extension system absent under --background). Each tools/*test.py
registers a `bpy.app.timers` callback, writes `<name>_result.txt`, self-quits. Tests run
the INSTALLED copy → run ../install.ps1 first.
