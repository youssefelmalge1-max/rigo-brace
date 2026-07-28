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


def _is_registered(registered, name):
    """True only when the operator is really registered on bpy.ops.rigo."""
    return name in registered


def _check():
    _TRIES["n"] += 1
    # `hasattr(bpy.ops.rigo, name)` is NOT a registration test: bpy.ops
    # fabricates a callable for ANY attribute name and only fails when it
    # is called. Measured - hasattr() returns True for a made-up operator
    # name, so the presence assertions below were passing vacuously and
    # would have kept passing if every operator had been deleted. dir()
    # reports what is actually registered.
    ops = bpy.ops.rigo
    registered = set(dir(ops))
    checks = {
        "panel_main": hasattr(bpy.types, "RIGO_PT_main"),
        "panel_workflow_removed": not hasattr(bpy.types, "RIGO_PT_workflow"),
        "panel_view": hasattr(bpy.types, "RIGO_PT_view"),
        "panel_view_options": hasattr(bpy.types, "RIGO_PT_view_options"),
        "tool_header": hasattr(bpy.types, "VIEW3D_HT_tool_header"),
        "op_set_tab": _is_registered(registered, "set_tab"),
        "op_step_tab": _is_registered(registered, "step_tab"),
        "op_stage_next": _is_registered(registered, "stage_next"),
        "op_stage_back": _is_registered(registered, "stage_back"),
        "op_rollback": _is_registered(registered, "rollback"),
        "op_toggle_ground": _is_registered(registered, "toggle_ground"),
        "op_view_axis": _is_registered(registered, "view_axis"),
        "op_toggle_quadview": _is_registered(registered, "toggle_quadview"),
        "op_toggle_fullscreen": _is_registered(registered, "toggle_fullscreen"),
        "op_align_quad": _is_registered(registered, "align_quad"),
        "op_setup_workspaces": _is_registered(registered, "setup_workspaces"),
        "op_pick_landmark": _is_registered(registered, "pick_landmark"),
        "op_apply_units": _is_registered(registered, "apply_units"),
        "op_recenter_floor": _is_registered(registered, "recenter_floor"),
        "op_center_model": _is_registered(registered, "center_model"),
        "op_verify_clean": _is_registered(registered, "verify_clean"),
        "op_quad_remesh": _is_registered(registered, "quad_remesh"),
        "op_region_add": _is_registered(registered, "region_add"),
        "op_region_add_circle": _is_registered(registered, "region_add_circle"),
        "op_region_edit": _is_registered(registered, "region_edit"),
        "op_region_update": _is_registered(registered, "region_update"),
        "op_region_style_save": _is_registered(registered, "region_style_save"),
        "op_region_style_import": _is_registered(registered, "region_style_import"),
        "op_region_style_delete": _is_registered(registered, "region_style_delete"),
        "op_region_apply": _is_registered(registered, "region_apply"),
        "op_region_mirror": _is_registered(registered, "region_mirror"),
        "op_region_remove": _is_registered(registered, "region_remove"),
        "op_xray_transform": _is_registered(registered, "xray_transform"),
        "op_xray_lock": _is_registered(registered, "xray_lock"),
        "op_lattice_add": _is_registered(registered, "lattice_add"),
        "op_lattice_twist": _is_registered(registered, "lattice_twist"),
        "op_lattice_apply": _is_registered(registered, "lattice_apply"),
        "op_lattice_discard": _is_registered(registered, "lattice_discard"),
        "op_toggle_seethrough": _is_registered(registered, "toggle_seethrough"),
        "op_smooth_trim_edge": _is_registered(registered, "smooth_trim_edge"),
        "op_flare_edge": _is_registered(registered, "flare_edge"),
        "op_vent_paint": _is_registered(registered, "vent_paint"),
        "op_vent_grid": _is_registered(registered, "vent_grid"),
        "op_lattice_paint": _is_registered(registered, "lattice_paint"),
        "op_build_lattice_pattern": _is_registered(registered, "build_lattice_pattern"),
        "op_auto_trimline": _is_registered(registered, "auto_trimline"),
        "op_edit_trimline": _is_registered(registered, "edit_trimline"),
        "op_slide_trimline_on_surface": _is_registered(registered, "slide_trimline_on_surface"),
        "op_snap_trimline_to_surface": _is_registered(registered, "snap_trimline_to_surface"),
        "op_smooth_trimline_brush": _is_registered(registered, "smooth_trimline_brush"),
        "op_smooth_trimline": _is_registered(registered, "smooth_trimline"),
        "op_refine_trimline": _is_registered(registered, "refine_trimline"),
        "op_custom_trim_paint": _is_registered(registered, "custom_trim_paint"),
        "op_custom_trim_mask_adjust": _is_registered(registered, "custom_trim_mask_adjust"),
        "op_custom_trim_from_paint": _is_registered(registered, "custom_trim_from_paint"),
        "op_clear_trimlines": _is_registered(registered, "clear_trimlines"),
        "op_fill_holes": _is_registered(registered, "fill_holes"),
        "op_erase_toggle": _is_registered(registered, "erase_toggle"),
        "op_erase_delete": _is_registered(registered, "erase_delete"),
        "op_deform_start": _is_registered(registered, "deform_start"),
        "op_deform_segment": _is_registered(registered, "deform_segment"),
        "op_deform_apply": _is_registered(registered, "deform_apply"),
        "op_pick_deform_range": _is_registered(registered, "pick_deform_range"),
        "op_scale_girth": _is_registered(registered, "scale_girth"),
        "op_import_xray": _is_registered(registered, "import_xray"),
        "op_place_pad": _is_registered(registered, "place_pad"),
        "op_draw_boundary": _is_registered(registered, "draw_boundary"),
        "op_add_pad": _is_registered(registered, "add_pad"),
        "op_edit_pad": _is_registered(registered, "edit_pad"),
        "op_record_pad_shape": _is_registered(registered, "record_pad_shape"),
        "op_set_pad_favourite": _is_registered(registered, "set_pad_favourite"),
        "op_delete_pad_entry": _is_registered(registered, "delete_pad_entry"),
        "op_apply_pads": _is_registered(registered, "apply_pads"),
        "op_mirror_pads": _is_registered(registered, "mirror_pads"),
        "op_generate_curve_corset": _is_registered(registered, "generate_curve_corset"),
        # Retired with the legacy builder: it never read the paint mask
        # and had no connected-component check.
        "legacy_generator_retired": "generate_corset" not in registered,
        "legacy_outline_retired": not any(
            name in registered
            for name in ("edit_outline", "apply_outline", "reset_outline")
        ),
        "op_design_view": _is_registered(registered, "design_view"),
        "op_paint_select": _is_registered(registered, "paint_select"),
        "op_select_grow": _is_registered(registered, "select_grow"),
        "op_select_shrink": _is_registered(registered, "select_shrink"),
        "op_select_clear": _is_registered(registered, "select_clear"),
        "op_select_invert": _is_registered(registered, "select_invert"),
        "op_push_selection": _is_registered(registered, "push_selection"),
        "op_thicken_selection": _is_registered(registered, "thicken_selection"),
        "op_smooth_selection": _is_registered(registered, "smooth_selection"),
        "op_delete_selection": _is_registered(registered, "delete_selection"),
        "op_cut_slots": _is_registered(registered, "cut_slots"),
        "op_place_rivet": _is_registered(registered, "place_rivet"),
        "op_cut_rivets": _is_registered(registered, "cut_rivets"),
        "op_use_quad_remesh_result": _is_registered(registered, "use_quad_remesh_result"),
        "op_place_emboss": _is_registered(registered, "place_emboss"),
        "op_emboss_text": _is_registered(registered, "emboss_text"),
        "op_verify_brace_qa": _is_registered(registered, "verify_brace_qa"),
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
