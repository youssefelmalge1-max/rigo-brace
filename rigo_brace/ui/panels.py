"""The Rigo Brace side panel — one canonical guided workflow.

One side panel (press N, "Rigo Brace" tab) shows the five workflow stages as a
tab row and draws only the tools for the current stage. The panel, viewport
tool-header and optional workspaces all use ``brace_stage``.
"""

import bpy
from bpy.types import Panel

from ..core import (
    CORSET_NAME,
    LANDMARK_PREFIX,
    LANDMARKS,
    WORKFLOW_TABS,
    brace_ready_for_finishing,
)
from ..core.signatures import brace_has_source_record
from . import icons


_CATEGORY = "Rigo Brace"


def _count_landmarks():
    return sum(1 for o in bpy.data.objects if o.name.startswith(LANDMARK_PREFIX))


def _tab_icon_args(tab_id, builtin):
    """Return kwargs for a UI element: custom badge if available, else built-in."""
    custom = icons.icon_id(tab_id)
    if custom:
        return {"icon_value": custom}
    return {"icon": builtin}


def _draw_step_bar(layout, settings, show_text):
    """Big numbered step buttons. Icon-only in the narrow side panel,
    icon + name across the wide top toolbar."""
    row = layout.row(align=True)
    row.scale_y = 1.5
    for ident, name, _description, builtin in WORKFLOW_TABS:
        sub = row.row(align=True)
        sub.scale_x = 1.0
        text = name if show_text else ""
        op = sub.operator(
            "rigo.set_tab",
            text=text,
            depress=(settings.brace_stage == ident),
            **_tab_icon_args(ident, builtin),
        )
        op.tab = ident


class _RigoPanelBase:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY


# --------------------------------------------------------------------------- #
# Per-stage drawing helpers
# --------------------------------------------------------------------------- #
def _draw_file(layout, context):
    settings = context.scene.rigo_brace
    box = layout.box()
    box.label(text="Import Patient Scan", icon="IMPORT")
    row = box.row(align=True)
    row.operator("rigo.import_scan", text="Import STL", icon="IMPORT").file_format = "STL"
    row.operator("rigo.import_scan", text="Import OBJ", icon="IMPORT").file_format = "OBJ"
    scan = settings.scan_object
    if scan is not None:
        box.label(text=f"Loaded: {scan.name}", icon="MESH_DATA")
    box.label(text="Then place your clinical landmarks in Step 3.", icon="INFO")


def _draw_clean_select(layout, context):
    """Cleanup-only selection: paint a region of noise and delete it.
    The shaping suite (push/pull/thicken/smooth) lives in the Mesh/Shape stage."""
    settings = context.scene.rigo_brace
    obj = context.active_object
    painting = obj is not None and obj.mode == "EDIT"

    box = layout.box()
    box.label(text="Select & Remove Noise", icon="BRUSH_DATA")
    box.operator(
        "rigo.paint_select",
        text="Painting… (drag on model)" if painting else "Paint Area  (Alt+P)",
        icon="BRUSHES_ALL",
        depress=painting,
    )
    if painting:
        info = box.box()
        info.scale_y = 0.85
        info.label(text="Drag = select   •   Ctrl+drag = deselect", icon="INFO")
    row = box.row(align=True)
    row.prop(settings, "select_grow_steps")
    row.operator("rigo.select_grow", text="Grow")
    row.operator("rigo.select_shrink", text="Shrink")
    row = box.row(align=True)
    row.operator("rigo.select_clear", text="Clear", icon="X")
    row.operator("rigo.select_invert", text="Invert", icon="ARROW_LEFTRIGHT")
    box.operator("rigo.delete_selection", text="Delete Selected (remove noise)", icon="TRASH")


def _draw_scan(layout, context):
    settings = context.scene.rigo_brace
    box = layout.box()
    box.label(text="Scale", icon="EMPTY_ARROWS")
    box.prop(settings, "scan_units", text="Units")
    box.operator("rigo.apply_units", text="Apply Units")
    box.label(text="Align is in the View panel (Align in Quad View).", icon="INFO")

    # Cleanup selection only — shaping moved to the Mesh stage.
    _draw_clean_select(layout, context)

    box = layout.box()
    box.label(text="Clean Up", icon="MOD_REMESH")
    box.operator("rigo.center_model", text="Center Model", icon="OBJECT_ORIGIN")
    active = context.active_object
    erase_active = (
        active is not None
        and active.type == "MESH"
        and active.mode == "EDIT"
        and "_rigo_erase_previous_xray" in active
    )
    if erase_active:
        box.operator("rigo.erase_delete", text="Delete Box Selection", icon="TRASH")
        box.operator("rigo.erase_toggle", text="Finish Box Erase", icon="CHECKMARK")
    else:
        box.operator(
            "rigo.erase_toggle", text="Box Erase (through model)", icon="SELECT_SET"
        )
    box.operator("rigo.fill_holes", text="Fill Holes")
    col = box.column(align=True)
    col.prop(settings, "remesh_voxel", text="Detail (mm)")
    col.operator("rigo.remesh", text="Auto-Remesh")
    col = box.column(align=True)
    col.prop(settings, "quad_remesh_engine", text="Engine")
    col.prop(settings, "quad_target_faces", text="Quad Faces")
    if settings.quad_remesh_engine == "EXOSIDE":
        col.prop(settings, "quad_adaptive_size", text="Curvature")
        if hasattr(bpy.types, "QREMESHER_OT_remesh"):
            col.operator("rigo.quad_remesh", text="Run Exoside Quad Remesher")
            active = context.active_object
            if active is not None and active.type == "MESH" and active != settings.scan_object:
                col.operator(
                    "rigo.use_quad_remesh_result",
                    text="Use Result as Patient Scan",
                    icon="CHECKMARK",
                )
            col.label(text="First run may open Exoside licensing.", icon="INFO")
        else:
            col.label(text="Exoside bridge is not enabled", icon="ERROR")
    else:
        col.operator("rigo.quad_remesh", text="Run Blender QuadriFlow")
    col = box.column(align=True)
    col.prop(settings, "smooth_iterations")
    col.prop(settings, "smooth_factor")
    col.operator("rigo.smooth", text="Smooth (whole mesh)")

    # Verify-clean gate: highlight problems before closing the mesh.
    vbox = layout.box()
    vbox.label(text="Verify Clean-up", icon="ZOOM_SELECTED")
    vbox.operator("rigo.verify_clean", text="Check the Mesh")
    scan = settings.scan_object or context.active_object
    if scan is not None and scan.get("rigo_boundary") is not None:
        if scan.get("rigo_verify_ok"):
            vbox.label(text="Looks clean — no holes or bad edges", icon="CHECKMARK")
        else:
            vbox.label(
                text=f"Holes: {scan.get('rigo_boundary')}  ·  "
                f"Non-manifold: {scan.get('rigo_nonmanifold')}  ·  "
                f"Loose: {scan.get('rigo_loose')}",
                icon="ERROR",
            )


def _draw_landmarks(layout, context):
    settings = context.scene.rigo_brace
    box = layout.box()
    box.label(text="Guided picking", icon="RESTRICT_SELECT_OFF")
    box.operator("rigo.pick_landmark", text="Pick on Scan", icon="EYEDROPPER")
    box.label(text="Click each point on the body in turn.")

    box = layout.box()
    box.label(text="Manual", icon="EMPTY_DATA")
    box.label(text="Shift+Right-Click to set the cursor,")
    box.label(text="then place the point below.")
    box.prop(settings, "active_landmark", text="")
    box.operator("rigo.place_landmark", text="Place at Cursor")

    layout.label(text=f"Placed: {_count_landmarks()} / {len(LANDMARKS)}")
    layout.operator("rigo.clear_landmarks", text="Clear All", icon="TRASH")


def _bbox_mm(obj):
    """World-space bounding box size in millimetres (height, width, depth)."""
    import mathutils

    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return (
        (max(zs) - min(zs)) * 1000.0,
        (max(xs) - min(xs)) * 1000.0,
        (max(ys) - min(ys)) * 1000.0,
    )


def _draw_select_box(layout, context):
    """Shared paint-select region tools (Edit-Mode native brush)."""
    settings = context.scene.rigo_brace
    obj = context.active_object
    painting = obj is not None and obj.mode == "EDIT"

    box = layout.box()
    box.label(text="Select Area", icon="BRUSH_DATA")

    # -- Step 1: paint the region ---------------------------------------- #
    box.label(text="1. Paint the area")
    box.operator(
        "rigo.paint_select",
        text="Painting… (drag on model)" if painting else "Paint Area  (Alt+P)",
        icon="BRUSHES_ALL",
        depress=painting,
    )
    if painting:
        info = box.box()
        info.scale_y = 0.85
        info.label(text="Drag = select faces   •   Ctrl+drag = deselect", icon="INFO")
        info.label(text="Scroll wheel = brush size")
    row = box.row(align=True)
    row.prop(settings, "select_grow_steps")
    row.operator("rigo.select_grow", text="Grow")
    row.operator("rigo.select_shrink", text="Shrink")
    row = box.row(align=True)
    row.operator("rigo.select_clear", text="Clear", icon="X")
    row.operator("rigo.select_invert", text="Invert", icon="ARROW_LEFTRIGHT")

    # -- Step 2: apply an action ----------------------------------------- #
    box.separator()
    box.label(text="2. Make it take effect:")
    col = box.column(align=True)
    col.prop(settings, "select_depth")
    col.label(text="Click → then drag to push. Left-click confirms.", icon="INFO")
    row = col.row(align=True)
    row.operator("rigo.push_selection", text="Push Out →", icon="TRIA_UP").direction = "OUT"
    row.operator("rigo.push_selection", text="← Push In", icon="TRIA_DOWN").direction = "IN"
    col.separator()
    col.prop(settings, "select_thickness")
    col.operator("rigo.thicken_selection", text="Thicken Area", icon="MOD_SOLIDIFY")
    col.separator()
    col.prop(settings, "select_smooth_factor")
    col.prop(settings, "select_smooth_iters")
    col.operator("rigo.smooth_selection", text="Smooth Area", icon="MOD_SMOOTH")
    col.separator()
    col.operator("rigo.delete_selection", text="Delete Area", icon="TRASH")
    box.label(text="Tip: paint stays until you Clear it.", icon="INFO")
    box.label(text="Shortcuts in Preferences ▸ Keymap", icon="EVENT_OS")


def _draw_guided_box(layout, context):
    """Selection-first, measurable pressure/expansion regions."""
    settings = context.scene.rigo_brace
    obj = settings.scan_object or context.active_object
    if obj is None or obj.type != "MESH":
        return
    box = layout.box()
    box.label(text="Pressure / Expansion (Selection)", icon="BRUSH_DATA")
    box.label(text="1. Paint faces above  2. Create live region", icon="INFO")
    row = box.row(align=True)
    row.prop(settings, "region_kind", expand=True)
    col = box.column(align=True)
    col.prop(settings, "region_magnitude")
    col.prop(settings, "region_feather")
    col.prop(settings, "region_falloff", text="Falloff")
    box.operator("rigo.region_add", text="Create Live Region", icon="ADD")
    col = box.column(align=True)
    col.prop(settings, "region_radius")
    col.operator("rigo.region_add_circle", text="Ready Circular Region", icon="MESH_CIRCLE")
    box.separator()
    box.label(text="Reusable Correction Styles", icon="ASSET_MANAGER")
    box.prop(settings, "region_style", text="")
    row = box.row(align=True)
    row.operator("rigo.region_style_import", text="Import at Cursor", icon="IMPORT")
    row.operator("rigo.region_style_delete", text="", icon="TRASH")

    if obj.rigo_regions:
        box.template_list(
            "RIGO_UL_regions", "", obj, "rigo_regions",
            obj, "rigo_region_index", rows=2,
        )
        idx = obj.rigo_region_index
        if 0 <= idx < len(obj.rigo_regions):
            region = obj.rigo_regions[idx]
            col = box.column(align=True)
            col.prop(region, "kind", text="")
            col.prop(region, "magnitude_mm")
            col.prop(region, "anatomical_label", text="")
        row = box.row(align=True)
        row.operator("rigo.region_edit", text="Edit Selection", icon="EDITMODE_HLT")
        row.operator("rigo.region_update", text="Update Preview", icon="FILE_REFRESH")
        row = box.row(align=True)
        row.operator("rigo.region_apply", text="Commit", icon="CHECKMARK")
        row.operator("rigo.region_mirror", text="Mirror", icon="MOD_MIRROR")
        row.operator("rigo.region_remove", text="", icon="TRASH")
        box.operator(
            "rigo.region_style_save", text="Save Committed Style…", icon="FILE_TICK"
        )
        box.label(text="Preview follows local body-surface normals.", icon="INFO")


def _draw_mesh(layout, context):
    settings = context.scene.rigo_brace

    # Paint-select region tools come first — everything below can target them.
    _draw_select_box(layout, context)

    # Guided measurable corrections built on the painted region.
    _draw_guided_box(layout, context)

    # Live size readout (LeoSpinal shows height / perimeter as you deform).
    scan = settings.scan_object or context.active_object
    if scan is not None and scan.type == "MESH":
        h, w, d = _bbox_mm(scan)
        girth = 3.14159 * (1.5 * (w + d) / 2 - (w * d) ** 0.5)  # Ramanujan approx
        info = layout.box()
        info.label(text=f"Height: {h:.0f} mm", icon="EMPTY_SINGLE_ARROW")
        info.label(text=f"Perimeter ~ {girth:.0f} mm", icon="MESH_CIRCLE")

    box = layout.box()
    box.label(text="Three Segment Rings", icon="ARROW_LEFTRIGHT")
    box.label(text="Start a tool, then choose the active ring pair.", icon="INFO")
    row = box.row(align=True)
    lower = row.operator(
        "rigo.deform_segment",
        text="Lower ↔ Middle",
        depress=settings.deform_segment == "LOWER",
    )
    lower.segment = "LOWER"
    upper = row.operator(
        "rigo.deform_segment",
        text="Middle ↔ Upper",
        depress=settings.deform_segment == "UPPER",
    )
    upper.segment = "UPPER"
    box.operator(
        "rigo.deform_segment",
        text="Full: Lower ↔ Upper",
        depress=settings.deform_segment == "FULL",
    ).segment = "FULL"
    box.label(text="Drag any ring: select it, press G then Z.", icon="ORIENTATION_GLOBAL")
    box.label(text=f"Active: {settings.deform_segment.replace('_', ' ').title()}")

    # Derotation / deform tools FIRST (clinical order), then remold by hand.
    box = layout.box()
    box.label(text="Bend", icon="MOD_SIMPLEDEFORM")
    box.operator("rigo.deform_start", text="Start Bend").method = "BEND"
    box.prop(settings, "bend_angle", slider=True)

    box = layout.box()
    box.label(text="Twist (derotate)", icon="MOD_SCREW")
    box.operator("rigo.deform_start", text="Start Twist").method = "TWIST"
    box.prop(settings, "twist_angle", slider=True)

    box = layout.box()
    box.label(text="Stretch", icon="MOD_LENGTH")
    box.operator("rigo.deform_start", text="Start Stretch").method = "STRETCH"
    box.prop(settings, "stretch_mm")

    row = layout.row(align=True)
    row.operator("rigo.deform_apply", text="Apply", icon="CHECKMARK")
    row.operator("rigo.deform_reset", text="Reset", icon="TRASH")

    box = layout.box()
    box.label(text="Scale (inflate / deflate)", icon="MOD_MESHDEFORM")
    box.prop(settings, "scale_amount", slider=True)
    box.operator("rigo.scale_girth", text="Apply Inflate / Deflate")

    box = layout.box()
    box.label(text="Free-form Cage", icon="MOD_LATTICE")
    has_cage = settings.correction_lattice is not None
    col = box.column(align=True)
    col.enabled = not has_cage
    col.prop(settings, "correction_div_width")
    col.prop(settings, "correction_div_depth")
    col.prop(settings, "correction_div_height")
    box.operator("rigo.build_correction_cage", text="Build Cage")
    row = box.row(align=True)
    row.enabled = has_cage
    row.operator("rigo.edit_correction_cage", text="Edit Cage")
    row = box.row(align=True)
    row.enabled = has_cage
    row.operator("rigo.apply_correction", text="Apply")
    row.operator("rigo.reset_correction", text="", icon="TRASH")

    # Lattice cage derotation (WASP port, PROV-0008): pelvis anchored,
    # each higher section rotates further to untwist the trunk.
    box = layout.box()
    box.label(text="Lattice Derotation", icon="MOD_LATTICE")
    has_cage = bpy.data.objects.get("Rigo Lattice") is not None
    if not has_cage:
        box.prop(settings, "lattice_sections")
        box.operator("rigo.lattice_add", icon="MOD_LATTICE")
    else:
        box.prop(settings, "lattice_twist", slider=True)
        box.operator("rigo.lattice_twist", icon="FORCE_MAGNETIC")
        in_lat_edit = context.mode == "EDIT_LATTICE"
        box.operator(
            "rigo.lattice_edit",
            text="Finish Editing" if in_lat_edit else "Edit Cage Points",
            icon="LATTICE_DATA",
            depress=in_lat_edit,
        )
        row = box.row(align=True)
        row.operator("rigo.lattice_apply", text="Apply", icon="CHECKMARK")
        row.operator("rigo.lattice_discard", text="Discard", icon="X")

    box = layout.box()
    box.label(text="X-ray Overlay", icon="IMAGE_DATA")
    box.operator("rigo.import_xray", text="Import X-ray")
    box.prop(settings, "xray_opacity", slider=True)
    row = box.row(align=True)
    row.operator("rigo.xray_transform", text="Move").mode = "MOVE"
    row.operator("rigo.xray_transform", text="Rotate").mode = "ROTATE"
    row.operator("rigo.xray_transform", text="Scale").mode = "SCALE"
    xray = bpy.data.objects.get("Rigo X-ray")
    locked = xray is not None and xray.parent is not None
    box.operator(
        "rigo.xray_lock",
        text="Unlock From Model" if locked else "Lock To Model",
        icon="LOCKED" if locked else "UNLOCKED",
        depress=locked,
    )

    # Free sculpt: freehand brushes for what the measured regions can't do.
    # Freehand edits are NOT CorrectionRegions — they carry no mm record.
    box = layout.box()
    box.label(text="Free Sculpt (brushes)", icon="SCULPTMODE_HLT")
    col = box.column(align=True)
    col.prop(settings, "remold_brush_size")
    col.prop(settings, "remold_brush_strength")
    col.operator("rigo.remold_apply_sliders", text="Update Brush")
    obj = context.active_object
    in_sculpt = obj is not None and obj.mode == "SCULPT"
    box.operator(
        "rigo.remold_toggle",
        text="Leave Free Sculpt" if in_sculpt else "Start Free Sculpt",
        depress=in_sculpt,
    )


def _draw_final_export(layout, settings, brace, dirty):
    """Draw guarded final output controls in one discoverable location."""
    box = layout.box()
    box.label(text="Final Export (after finishing)", icon="EXPORT")
    if brace is None:
        box.label(text="Generate the brace above before exporting.", icon="INFO")
    elif dirty:
        box.label(text="Update the out-of-date brace before QA/export.", icon="ERROR")
    else:
        box.label(text="Runs manufacturing QA before saving STL.", icon="INFO")
    box.prop(settings, "qa_min_thickness")
    qa_row = box.row()
    qa_row.enabled = brace is not None and not dirty
    qa_row.operator(
        "rigo.verify_brace_qa", text="Verify Manufacturing QA", icon="CHECKMARK"
    )
    if brace is not None and not dirty and "rigo_qa_pass" in brace:
        passed = bool(brace.get("rigo_qa_pass", False))
        box.label(
            text="QA PASS" if passed else "QA required / failed - export checks again",
            icon="CHECKMARK" if passed else "ERROR",
        )
        if "rigo_qa_min_thickness_mm" in brace:
            box.label(text=f"Sampled minimum: {brace['rigo_qa_min_thickness_mm']:.2f} mm")
        if not passed:
            report = str(brace.get("rigo_qa_report", ""))
            box.label(text=report[:80], icon="INFO")
    export_row = box.row()
    export_row.enabled = brace is not None and not dirty
    export_row.scale_y = 1.25
    export_row.operator("rigo.export_brace", text="Save Brace STL...", icon="EXPORT")


def _draw_design(layout, context):
    settings = context.scene.rigo_brace
    brace = bpy.data.objects.get(CORSET_NAME)
    dirty = bool(
        brace is not None
        and (
            settings.brace_dirty
            or brace.get("rigo_brace_dirty", False)
            or not brace_has_source_record(brace)
        )
    )
    finishing_ready = brace_ready_for_finishing(context)

    box = layout.box()
    box.label(text="Trimline Source", icon="CURVE_DATA")
    box.prop(settings, "trim_source_mode", expand=True)
    if settings.trim_source_mode == "TEMPLATE":
        box.prop(settings, "trim_type", text="Type")
        box.prop(settings, "opening_width")
        box.operator(
            "rigo.auto_trimline",
            text="Generate Template Trimline",
            icon="CURVE_BEZCIRCLE",
        )
    else:
        box.label(text="Green = brace area  |  White = excluded", icon="INFO")
        box.operator(
            "rigo.custom_trim_paint",
            text="Paint Brace Area",
            icon="VPAINT_HLT",
        )
        row = box.row(align=True)
        grow = row.operator("rigo.custom_trim_mask_adjust", text="Grow")
        grow.action = "GROW"
        shrink = row.operator("rigo.custom_trim_mask_adjust", text="Shrink")
        shrink.action = "SHRINK"
        smooth = row.operator(
            "rigo.custom_trim_mask_adjust",
            text="Smooth Mask",
            icon="MOD_SMOOTH",
        )
        smooth.action = "SMOOTH"
        row = box.row(align=True)
        invert = row.operator("rigo.custom_trim_mask_adjust", text="Invert")
        invert.action = "INVERT"
        clear = row.operator(
            "rigo.custom_trim_mask_adjust",
            text="Clear Paint",
            icon="TRASH",
        )
        clear.action = "CLEAR"
        row = box.row(align=True)
        row.prop(settings, "trim_mask_steps")
        row.prop(settings, "trim_mask_smooth")
        box.separator()
        box.prop(settings, "trim_smooth_mm")
        box.prop(settings, "trim_min_radius_mm")
        box.prop(settings, "trim_custom_spacing")
        box.label(
            text="Smoothing removes wobble; radius limits sharp corners",
            icon="INFO",
        )
        box.operator(
            "rigo.custom_trim_from_paint",
            text="Create Trimline from Paint",
            icon="CURVE_BEZCIRCLE",
        )
    perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
    if perimeter is not None:
        row = box.row(align=True)
        row.operator(
            "rigo.slide_trimline_on_surface",
            text="Edit 3-Point Tangents",
            icon="CURVE_BEZCURVE",
        )
        box.prop(settings, "trim_edit_radius")
        box.prop(settings, "trim_edit_lock_features")
        box.prop(settings, "trim_brush_radius")
        box.prop(settings, "trim_brush_strength")
        box.prop(settings, "trim_brush_lock_opening")
        row = box.row(align=True)
        row.operator(
            "rigo.smooth_trimline_brush",
            text="Smooth Trimline Brush",
            icon="MOD_SMOOTH",
        )
        refine_row = row.row(align=True)
        refine_row.enabled = (
            len(perimeter.data.splines[0].bezier_points) < 168
        )
        refine_row.operator(
            "rigo.refine_trimline",
            text="Add Curve Detail",
            icon="MOD_SUBSURF",
        )
        row.operator("rigo.clear_trimlines", text="", icon="TRASH")
        box.label(
            text="Brush locally; Edit shows linked 3-point tangents",
            icon="INFO",
        )
        box.label(text="Enter commits; Esc restores the original line", icon="INFO")
        if brace is not None:
            row = box.row(align=True)
            trim_view = row.operator(
                "rigo.design_view",
                text="Edit Trimlines",
                icon="CURVE_BEZCURVE",
                depress=settings.design_view_mode == "TRIM",
            )
            trim_view.mode = "TRIM"
            brace_view = row.operator(
                "rigo.design_view",
                text="Brace Preview",
                icon="MESH_DATA",
                depress=settings.design_view_mode == "BRACE",
            )
            brace_view.mode = "BRACE"
            overlay_row = box.row()
            overlay_row.enabled = settings.design_view_mode == "BRACE"
            overlay_row.prop(
                settings, "show_trim_overlay", icon="CURVE_DATA", toggle=True
            )
    elif settings.trim_source_mode == "TEMPLATE":
        box.label(text="Needs landmarks (pelvis/waist/shoulder)", icon="INFO")

    box = layout.box()
    box.label(text="Select Design", icon="MESH_CYLINDER")
    box.prop(settings, "design_style", expand=True)
    col = box.column(align=True)
    col.prop(settings, "corset_thickness")
    col.prop(settings, "corset_offset")
    col.prop(settings, "corset_smooth")
    row = col.row(align=True)
    row.prop(settings, "trim_fillet_radius")
    row.prop(settings, "trim_fillet_segments", text="Segments")
    col.prop(settings, "trim_transition_width")
    row = box.row(align=True)
    row.prop(settings, "reinforcement", toggle=True)
    row.prop(settings, "symmetrical", toggle=True)
    # One generator. The retired legacy builder never read the paint mask, so
    # it could keep the complement of what the orthotist painted, and it had no
    # connected-component check, which is how a brace in detached pieces reached
    # a user. `rigo.generate_corset` is gone; this is the only build path.
    generate_row = box.row()
    generate_row.enabled = perimeter is not None
    if brace is None:
        generate_text = "Generate Brace"
        generate_icon = "CHECKMARK"
    elif dirty:
        generate_text = "Update Brace"
        generate_icon = "FILE_REFRESH"
    else:
        generate_text = "Rebuild Brace"
        generate_icon = "FILE_REFRESH"
    generate_row.operator(
        "rigo.generate_curve_corset", text=generate_text, icon=generate_icon
    )
    if brace is not None:
        built_thickness = brace.get("rigo_requested_thickness_mm")
        if dirty:
            built_offset = brace.get("rigo_requested_offset_mm")
            built_fairing = brace.get("rigo_requested_fairing")
            box.label(text="BRACE OUT OF DATE", icon="ERROR")
            if built_thickness is None:
                box.label(
                    text=(
                        "Built thickness unknown  |  "
                        f"requested {settings.corset_thickness:.2f} mm"
                    )
                )
            else:
                box.label(
                    text=(
                        f"Built {float(built_thickness):.2f} mm  |  "
                        f"requested {settings.corset_thickness:.2f} mm"
                    )
                )
            if built_offset is not None and built_fairing is not None:
                box.label(
                    text=(
                        f"Offset {float(built_offset):.1f}->{settings.corset_offset:.1f} mm  |  "
                        f"fairing {int(built_fairing)}->{settings.corset_smooth}"
                    )
                )
            default_reason = (
                "Build source record missing"
                if not brace_has_source_record(brace)
                else "Design changed"
            )
            reason = str(brace.get("rigo_brace_dirty_reason", default_reason))
            box.label(text=reason[:72], icon="INFO")
            box.label(
                text="Update rebuilds the shell; reapply edge/slot finishing.",
                icon="INFO",
            )
        else:
            pair_min = float(brace.get("rigo_pair_min_thickness_mm", 0.0))
            pair_max = float(brace.get("rigo_pair_max_thickness_mm", 0.0))
            box.label(
                text=f"Built wall: {float(built_thickness):.2f} mm",
                icon="CHECKMARK",
            )
            if pair_min > 0.0:
                box.label(
                    text=f"Paired shell before rim: {pair_min:.2f}-{pair_max:.2f} mm"
                )
            quad_ratio = brace.get("rigo_brace_quad_ratio")
            if quad_ratio is not None:
                box.label(
                    text=f"Quad topology: {float(quad_ratio) * 100.0:.1f}%",
                    icon="MESH_GRID",
                )
            fillet_effective = float(
                brace.get("rigo_trim_fillet_radius_mm", 0.0)
            )
            fillet_mean = float(
                brace.get("rigo_trim_fillet_mean_radius_mm", 0.0)
            )
            if fillet_effective > 0.0:
                box.label(
                    text=(
                        f"Trim round-over: up to {fillet_effective:.2f} mm, "
                        f"mean {fillet_mean:.2f} mm"
                    ),
                    icon="MOD_BEVEL",
                )
            repair_iterations = int(
                brace.get("rigo_outer_collision_iterations", 0)
            )
            if repair_iterations:
                repair_angle = float(
                    brace.get("rigo_outer_collision_max_angle_deg", 0.0)
                )
                box.label(
                    text=(
                        f"Outer-wall safety repair: {repair_iterations} passes, "
                        f"max {repair_angle:.1f} deg"
                    ),
                    icon="MOD_SMOOTH",
                )
    box.prop(settings, "corset_opacity", slider=True)
    box.label(text="Shape the body in Mesh Edit before generating.", icon="INFO")

    # Design is the final workflow phase. Keep its guarded export visible near
    # the generated-brace status instead of burying it below optional tools.
    _draw_final_export(layout, settings, brace, dirty)

    # Trim-edge finishing (Patch 6): see-through check, relax the cut edge,
    # bend it away from the skin (safe edge).
    box = layout.box()
    box.enabled = finishing_ready
    box.label(text="Trim Edge Finishing", icon="MOD_SMOOTH")
    xray_on = any(
        space.shading.show_xray
        for area in context.screen.areas
        for space in area.spaces
        if space.type == "VIEW_3D"
    )
    box.operator(
        "rigo.toggle_seethrough",
        text="See-Through (check the line)",
        icon="XRAY",
        depress=xray_on,
    )
    box.prop(settings, "edge_band")
    col = box.column(align=True)
    col.prop(settings, "trim_smooth_iters")
    col.operator("rigo.smooth_trim_edge", icon="MOD_SMOOTH")
    col = box.column(align=True)
    col.prop(settings, "edge_flare")
    col.operator("rigo.flare_edge", icon="MOD_SIMPLEDEFORM")

    box = layout.box()
    box.enabled = finishing_ready
    box.label(text="Strap Slots", icon="MOD_BOOLEAN")
    col = box.column(align=True)
    col.prop(settings, "slot_width")
    col.prop(settings, "slot_height")
    col.prop(settings, "slot_edge_radius")
    row = box.row(align=True)
    row.operator("rigo.place_slot", text="Place on Corset", icon="EYEDROPPER")
    row.operator("rigo.clear_slots", text="", icon="TRASH")
    box.operator("rigo.cut_slots", text="Cut Slots")
    if brace is not None and "rigo_slot_status" in brace:
        slot_status = str(brace["rigo_slot_status"])
        box.label(
            text=slot_status[:72],
            icon="ERROR" if slot_status.startswith("FAILED:") else "CHECKMARK",
        )

    box = layout.box()
    box.enabled = finishing_ready
    box.label(text="Rivet Holes", icon="MESH_CIRCLE")
    col = box.column(align=True)
    col.prop(settings, "rivet_diameter")
    col.prop(settings, "rivet_edge_radius")
    row = box.row(align=True)
    row.operator("rigo.place_rivet", text="Place Contour", icon="EYEDROPPER")
    row.operator("rigo.clear_rivets", text="", icon="TRASH")
    box.label(text="Move/scale selected circles before cutting", icon="INFO")
    box.operator("rigo.cut_rivets", text="Cut Rivet Holes", icon="MOD_BOOLEAN")
    if brace is not None and "rigo_rivet_status" in brace:
        rivet_status = str(brace["rigo_rivet_status"])
        box.label(
            text=rivet_status[:72],
            icon="ERROR" if rivet_status.startswith("FAILED:") else "CHECKMARK",
        )

    box = layout.box()
    box.enabled = finishing_ready
    box.label(text="Manufacturing Lattice", icon="MESH_GRID")
    box.prop(settings, "lattice_finish_mode", expand=True)
    box.prop(settings, "lattice_pattern", expand=True)
    col = box.column(align=True)
    col.prop(settings, "lattice_cell_size")
    col.prop(settings, "lattice_bar_width")
    if settings.lattice_finish_mode == "ADD":
        col.prop(settings, "lattice_height")
    box.operator("rigo.lattice_paint", text="Paint Lattice Area", icon="BRUSH_DATA")
    label = "Cut Lattice Ventilation" if settings.lattice_finish_mode == "CUT" else "Add Reinforcing Lattice"
    box.operator("rigo.build_lattice_pattern", text=label, icon="MOD_BOOLEAN")
    box.label(text="Trim-edge protection is automatic", icon="INFO")

    box = layout.box()
    box.enabled = finishing_ready
    box.label(text="Emboss", icon="FONT_DATA")
    box.prop(settings, "emboss_text", text="")
    box.prop(settings, "emboss_mode", expand=True)
    box.prop(settings, "emboss_size")
    box.prop(settings, "emboss_depth")
    row = box.row(align=True)
    row.operator("rigo.place_emboss", text="Place Text on Brace", icon="EYEDROPPER")
    row.operator("rigo.clear_emboss", text="", icon="TRASH")
    box.label(text="Move/rotate/scale the preview if needed", icon="INFO")
    box.operator("rigo.emboss_text", text="Apply Emboss", icon="MOD_BOOLEAN")

_STAGE_DRAW = {
    "FILE": _draw_file,
    "SCAN": _draw_scan,
    "LANDMARKS": _draw_landmarks,
    "MESH": _draw_mesh,
    "DESIGN": _draw_design,
}


# --------------------------------------------------------------------------- #
# Panels
# --------------------------------------------------------------------------- #
class RIGO_PT_main(_RigoPanelBase, Panel):
    bl_idname = "RIGO_PT_main"
    bl_label = "Rigo Brace Designer"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        settings = context.scene.rigo_brace

        tabs = list(WORKFLOW_TABS)
        index = next(i for i, t in enumerate(tabs) if t[0] == settings.brace_stage)
        current = tabs[index]

        # Big numbered step buttons (icon-only badges).
        _draw_step_bar(layout, settings, show_text=False)

        # Clinical header: "Step N of 5  ·  Name".
        header = layout.box()
        head_row = header.row()
        head_row.scale_y = 1.2
        head_row.label(
            text=f"Step {index + 1} of {len(tabs)}  \u00b7  {current[1]}",
            **_tab_icon_args(current[0], current[3]),
        )
        header.label(text=current[2])

        # Current stage content.
        body = layout.column()
        body.use_property_split = False
        _STAGE_DRAW[settings.brace_stage](body, context)

        # Prev / Next navigation — large, full width.
        layout.separator()
        nav = layout.row(align=True)
        nav.scale_y = 1.5
        prev = nav.operator("rigo.step_tab", text="Back", icon="TRIA_LEFT")
        prev.direction = "PREV"
        nxt = nav.operator("rigo.step_tab", text="Next", icon="TRIA_RIGHT")
        nxt.direction = "NEXT"


class RIGO_PT_view(_RigoPanelBase, Panel):
    """uFit-style View panel: Full Screen / Quad / Ortho + fixed view angles."""

    bl_idname = "RIGO_PT_view"
    bl_label = "View"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout

        col = layout.column(align=True)
        col.scale_y = 1.2
        row = col.row(align=True)
        row.operator("rigo.toggle_fullscreen", text="Full Screen", icon="FULLSCREEN_ENTER")
        row.operator("rigo.toggle_quadview", text="Quad View", icon="IMGDISPLAY")
        col.operator("rigo.toggle_ortho", text="Ortho View", icon="VIEW_ORTHO")

        box = layout.box()
        box.label(text="View Modes", icon="ORIENTATION_VIEW")
        grid = box.grid_flow(row_major=True, columns=2, align=True)
        grid.scale_y = 1.2
        for axis, label, _desc in (
            ("TOP", "Top", ""),
            ("FRONT", "Front", ""),
            ("LEFT", "Left", ""),
            ("RIGHT", "Right", ""),
            ("BACK", "Back", ""),
            ("BOTTOM", "Bottom", ""),
        ):
            grid.operator("rigo.view_axis", text=label).axis = axis

        box = layout.box()
        box.label(text="Align", icon="ORIENTATION_GIMBAL")
        box.operator("rigo.align_quad", text="Align in Quad View", icon="ORIENTATION_GIMBAL")
        row = box.row(align=True)
        row.operator("rigo.realign_tool", text="Rotate")
        row.operator("rigo.move_tool", text="Move")
        box.operator("rigo.recenter_floor", text="Recenter & Drop to Floor")


class RIGO_PT_view_options(_RigoPanelBase, Panel):
    """The lower-right floating options from LeoSpinal, as a side sub-panel."""

    bl_label = "View Options"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("rigo.toggle_ground", icon="GRID")
        col.operator("rigo.toggle_landmarks", icon="HIDE_OFF")
        col.operator("rigo.toggle_ortho", icon="VIEW_ORTHO")
        col.operator("rigo.toggle_measure", icon="DRIVER_DISTANCE")


def _draw_tool_header(self, context):
    """Big step bar drawn across the top viewport tool-header."""
    scene = getattr(context, "scene", None)
    settings = getattr(scene, "rigo_brace", None) if scene else None
    if settings is None:
        return
    layout = self.layout
    layout.separator_spacer()
    _draw_step_bar(layout, settings, show_text=True)
    layout.separator_spacer()


class RIGO_UL_regions(bpy.types.UIList):
    """Row per CorrectionRegion: enable · label · kind + amount."""

    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname
    ):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.prop(item, "name", text="", emboss=False)
        kind_icon = (
            "FULLSCREEN_EXIT" if item.kind == "PRESSURE" else "FULLSCREEN_ENTER"
        )
        row.label(text=f"{item.magnitude_mm:.0f}mm", icon=kind_icon)


_CLASSES = (
    RIGO_UL_regions,
    RIGO_PT_main,
    RIGO_PT_view,
    RIGO_PT_view_options,
)


def _tool_header_type():
    """The viewport tool-header class (renamed VIEW3D_* in Blender 5.0)."""
    return getattr(bpy.types, "VIEW3D_HT_tool_header", None) or getattr(
        bpy.types, "VIEW_3D_HT_tool_header", None
    )


def register():
    icons.register()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    header = _tool_header_type()
    if header is not None:
        header.append(_draw_tool_header)


def unregister():
    header = _tool_header_type()
    if header is not None:
        try:
            header.remove(_draw_tool_header)
        except ValueError:
            pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    icons.unregister()
