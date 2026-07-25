"""GUI self-test: launch with the rigo_brace template, verify the Phase 2A UI
registered, write the result to selftest_result.txt, then quit.

Run:
  & "$blender" --app-template rigo_brace --python tools\selftest.py
(Must be GUI — the extension system / bl_pkg is absent in --background.)
"""

import ast
import inspect

import bpy

_OUT = r"C:\Projects\Blender Add-on Braces\selftest_result.txt"
_TRIES = {"n": 0}


def _invalid_panel_icons():
    from bl_ext.user_default.rigo_brace.ui import panels

    valid_icons = set(
        bpy.types.UILayout.bl_rna.functions["operator"]
        .parameters["icon"]
        .enum_items.keys()
    )
    tree = ast.parse(inspect.getsource(panels))
    icons = {
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "icon"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }
    return sorted(icons - valid_icons)


def _check():
    _TRIES["n"] += 1
    ops = bpy.ops.rigo
    checks = {
        "panel_main": hasattr(bpy.types, "RIGO_PT_main"),
        "panel_workflow_removed": not hasattr(bpy.types, "RIGO_PT_workflow"),
        "panel_view": hasattr(bpy.types, "RIGO_PT_view"),
        "panel_view_options": hasattr(bpy.types, "RIGO_PT_view_options"),
        "tool_header": hasattr(bpy.types, "VIEW3D_HT_tool_header"),
        "op_set_tab": hasattr(ops, "set_tab"),
        "op_step_tab": hasattr(ops, "step_tab"),
        "op_stage_next": hasattr(ops, "stage_next"),
        "op_stage_back": hasattr(ops, "stage_back"),
        "op_rollback": hasattr(ops, "rollback"),
        "op_toggle_ground": hasattr(ops, "toggle_ground"),
        "op_view_axis": hasattr(ops, "view_axis"),
        "op_toggle_quadview": hasattr(ops, "toggle_quadview"),
        "op_toggle_fullscreen": hasattr(ops, "toggle_fullscreen"),
        "op_align_quad": hasattr(ops, "align_quad"),
        "op_setup_workspaces": hasattr(ops, "setup_workspaces"),
        "op_pick_landmark": hasattr(ops, "pick_landmark"),
        "op_apply_units": hasattr(ops, "apply_units"),
        "op_recenter_floor": hasattr(ops, "recenter_floor"),
        "op_center_model": hasattr(ops, "center_model"),
        "op_verify_clean": hasattr(ops, "verify_clean"),
        "op_quad_remesh": hasattr(ops, "quad_remesh"),
        "op_region_add": hasattr(ops, "region_add"),
        "op_region_add_circle": hasattr(ops, "region_add_circle"),
        "op_region_edit": hasattr(ops, "region_edit"),
        "op_region_update": hasattr(ops, "region_update"),
        "op_region_style_save": hasattr(ops, "region_style_save"),
        "op_region_style_import": hasattr(ops, "region_style_import"),
        "op_region_style_delete": hasattr(ops, "region_style_delete"),
        "op_region_apply": hasattr(ops, "region_apply"),
        "op_region_mirror": hasattr(ops, "region_mirror"),
        "op_region_remove": hasattr(ops, "region_remove"),
        "op_xray_transform": hasattr(ops, "xray_transform"),
        "op_xray_lock": hasattr(ops, "xray_lock"),
        "op_lattice_add": hasattr(ops, "lattice_add"),
        "op_lattice_twist": hasattr(ops, "lattice_twist"),
        "op_lattice_apply": hasattr(ops, "lattice_apply"),
        "op_lattice_discard": hasattr(ops, "lattice_discard"),
        "op_toggle_seethrough": hasattr(ops, "toggle_seethrough"),
        "op_smooth_trim_edge": hasattr(ops, "smooth_trim_edge"),
        "op_flare_edge": hasattr(ops, "flare_edge"),
        "op_vent_paint": hasattr(ops, "vent_paint"),
        "op_vent_grid": hasattr(ops, "vent_grid"),
        "op_lattice_paint": hasattr(ops, "lattice_paint"),
        "op_build_lattice_pattern": hasattr(ops, "build_lattice_pattern"),
        "op_auto_trimline": hasattr(ops, "auto_trimline"),
        "op_edit_trimline": hasattr(ops, "edit_trimline"),
        "op_slide_trimline_on_surface": hasattr(ops, "slide_trimline_on_surface"),
        "op_snap_trimline_to_surface": hasattr(ops, "snap_trimline_to_surface"),
        "op_smooth_trimline_brush": hasattr(ops, "smooth_trimline_brush"),
        "op_refine_trimline": hasattr(ops, "refine_trimline"),
        "op_custom_trim_paint": hasattr(ops, "custom_trim_paint"),
        "op_custom_trim_mask_adjust": hasattr(ops, "custom_trim_mask_adjust"),
        "op_custom_trim_from_paint": hasattr(ops, "custom_trim_from_paint"),
        "op_clear_trimlines": hasattr(ops, "clear_trimlines"),
        "op_fill_holes": hasattr(ops, "fill_holes"),
        "op_erase_toggle": hasattr(ops, "erase_toggle"),
        "op_erase_delete": hasattr(ops, "erase_delete"),
        "op_deform_start": hasattr(ops, "deform_start"),
        "op_deform_segment": hasattr(ops, "deform_segment"),
        "op_deform_apply": hasattr(ops, "deform_apply"),
        "op_pick_deform_range": hasattr(ops, "pick_deform_range"),
        "op_scale_girth": hasattr(ops, "scale_girth"),
        "op_import_xray": hasattr(ops, "import_xray"),
        "op_place_pad": hasattr(ops, "place_pad"),
        "op_draw_boundary": hasattr(ops, "draw_boundary"),
        "op_add_pad": hasattr(ops, "add_pad"),
        "op_edit_pad": hasattr(ops, "edit_pad"),
        "op_record_pad_shape": hasattr(ops, "record_pad_shape"),
        "op_set_pad_favourite": hasattr(ops, "set_pad_favourite"),
        "op_delete_pad_entry": hasattr(ops, "delete_pad_entry"),
        "op_apply_pads": hasattr(ops, "apply_pads"),
        "op_mirror_pads": hasattr(ops, "mirror_pads"),
        "op_generate_corset": hasattr(ops, "generate_corset"),
        "op_generate_curve_corset": hasattr(ops, "generate_curve_corset"),
        "op_design_view": hasattr(ops, "design_view"),
        "op_edit_outline": hasattr(ops, "edit_outline"),
        "op_apply_outline": hasattr(ops, "apply_outline"),
        "op_reset_outline": hasattr(ops, "reset_outline"),
        "op_paint_select": hasattr(ops, "paint_select"),
        "op_select_grow": hasattr(ops, "select_grow"),
        "op_select_shrink": hasattr(ops, "select_shrink"),
        "op_select_clear": hasattr(ops, "select_clear"),
        "op_select_invert": hasattr(ops, "select_invert"),
        "op_push_selection": hasattr(ops, "push_selection"),
        "op_thicken_selection": hasattr(ops, "thicken_selection"),
        "op_smooth_selection": hasattr(ops, "smooth_selection"),
        "op_delete_selection": hasattr(ops, "delete_selection"),
        "op_cut_slots": hasattr(ops, "cut_slots"),
        "op_place_rivet": hasattr(ops, "place_rivet"),
        "op_cut_rivets": hasattr(ops, "cut_rivets"),
        "op_use_quad_remesh_result": hasattr(ops, "use_quad_remesh_result"),
        "op_place_emboss": hasattr(ops, "place_emboss"),
        "op_emboss_text": hasattr(ops, "emboss_text"),
        "op_verify_brace_qa": hasattr(ops, "verify_brace_qa"),
    }
    settings = getattr(bpy.context.scene, "rigo_brace", None)
    checks["single_workflow_state"] = (
        settings is not None
        and hasattr(settings, "brace_stage")
        and not hasattr(settings, "active_tab")
    )
    checks["settings_ui_mode"] = settings is not None and hasattr(settings, "ui_mode")
    checks["settings_pad_kind"] = settings is not None and hasattr(settings, "pad_kind")
    checks["settings_pad_size"] = settings is not None and hasattr(settings, "pad_size")
    checks["settings_quad_target_faces"] = settings is not None and hasattr(settings, "quad_target_faces")
    checks["settings_quad_remesh_engine"] = settings is not None and hasattr(settings, "quad_remesh_engine")
    checks["settings_quad_adaptive_size"] = settings is not None and hasattr(settings, "quad_adaptive_size")
    checks["settings_region_magnitude"] = settings is not None and hasattr(settings, "region_magnitude")
    checks["settings_region_style"] = settings is not None and hasattr(settings, "region_style")
    checks["settings_deform_segment"] = settings is not None and hasattr(settings, "deform_segment")
    checks["settings_stretch_mm"] = settings is not None and hasattr(settings, "stretch_mm")
    checks["settings_qa_min_thickness"] = settings is not None and hasattr(settings, "qa_min_thickness")
    checks["settings_brace_dirty"] = settings is not None and hasattr(settings, "brace_dirty")
    checks["settings_design_view_mode"] = settings is not None and hasattr(settings, "design_view_mode")
    checks["settings_trim_fillet_radius"] = settings is not None and hasattr(settings, "trim_fillet_radius")
    checks["settings_trim_fillet_segments"] = settings is not None and hasattr(settings, "trim_fillet_segments")
    checks["settings_trim_transition_width"] = settings is not None and hasattr(settings, "trim_transition_width")
    checks["settings_trim_brush_radius"] = settings is not None and hasattr(settings, "trim_brush_radius")
    checks["settings_trim_brush_strength"] = settings is not None and hasattr(settings, "trim_brush_strength")
    checks["settings_trim_brush_lock_opening"] = settings is not None and hasattr(settings, "trim_brush_lock_opening")
    checks["settings_trim_source_mode"] = settings is not None and hasattr(settings, "trim_source_mode")
    checks["settings_trim_custom_spacing"] = settings is not None and hasattr(settings, "trim_custom_spacing")
    checks["settings_trim_mask_steps"] = settings is not None and hasattr(settings, "trim_mask_steps")
    checks["settings_trim_mask_smooth"] = settings is not None and hasattr(settings, "trim_mask_smooth")
    checks["settings_slot_edge_radius"] = settings is not None and hasattr(settings, "slot_edge_radius")
    checks["settings_rivet_diameter"] = settings is not None and hasattr(settings, "rivet_diameter")
    checks["settings_lattice_pattern"] = settings is not None and hasattr(settings, "lattice_pattern")
    checks["settings_emboss_mode"] = settings is not None and hasattr(settings, "emboss_mode")
    checks["object_rigo_regions"] = "rigo_regions" in bpy.types.Object.bl_rna.properties
    checks["uilist_regions"] = hasattr(bpy.types, "RIGO_UL_regions")
    invalid_icons = _invalid_panel_icons()
    checks["panel_icon_ids_valid"] = not invalid_icons

    ready = all(checks.values())
    if not ready and _TRIES["n"] < 25:
        return 0.1  # retry

    lines = [f"objects={len(bpy.data.objects)}"]
    for k, v in checks.items():
        lines.append(f"{k}={v}")
    lines.append(f"invalid_panel_icons={invalid_icons}")
    lines.append(f"ALL_PASS={ready}")
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_check, first_interval=0.5)
