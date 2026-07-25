"""Core data: anatomical landmark definitions and per-scene settings."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from .signatures import brace_has_source_record


# --------------------------------------------------------------------------- #
# Anatomical landmarks relevant to Rigo-Cheneau brace design.
# Each entry: (identifier, UI label, tooltip/description).
# These points are placed on the patient scan and later drive automatic
# placement of correction pads and expansion (relief) chambers.
# --------------------------------------------------------------------------- #
LANDMARKS = (
    ("C7", "C7 (Vertebra Prominens)", "Most prominent cervical vertebra at the neck base"),
    ("ACROMION_L", "Acromion L", "Left shoulder tip"),
    ("ACROMION_R", "Acromion R", "Right shoulder tip"),
    ("SCAPULA_L", "Inferior Scapula Angle L", "Lower tip of the left shoulder blade"),
    ("SCAPULA_R", "Inferior Scapula Angle R", "Lower tip of the right shoulder blade"),
    ("AXILLA_L", "Axilla L", "Left armpit reference"),
    ("AXILLA_R", "Axilla R", "Right armpit reference"),
    ("THORACIC_APEX", "Thoracic Curve Apex", "Apex vertebra of the thoracic curve"),
    ("LUMBAR_APEX", "Lumbar Curve Apex", "Apex vertebra of the lumbar curve"),
    ("ILIAC_L", "Iliac Crest L", "Top of the left hip bone"),
    ("ILIAC_R", "Iliac Crest R", "Top of the right hip bone"),
    ("ASIS_L", "ASIS L", "Left anterior superior iliac spine"),
    ("ASIS_R", "ASIS R", "Right anterior superior iliac spine"),
    ("PSIS_L", "PSIS L", "Left posterior superior iliac spine"),
    ("PSIS_R", "PSIS R", "Right posterior superior iliac spine"),
    ("TROCHANTER_L", "Greater Trochanter L", "Left hip pivot reference"),
    ("TROCHANTER_R", "Greater Trochanter R", "Right hip pivot reference"),
    ("WAISTLINE", "Waistline", "Narrowest waist reference level"),
)

# Name of the collection that holds the placed landmark empties.
LANDMARK_COLLECTION = "Rigo Landmarks"

# Prefix used when naming landmark empty objects, e.g. "LM_C7".
LANDMARK_PREFIX = "LM_"


# --------------------------------------------------------------------------- #
# Pressure / Relief shape library (LeoSpinal-style).
# The entries (builtin clinical set + the orthotist's recorded shapes, each
# with a favourite depth/size/kind) live in core/pad_library.py, persisted to
# a per-PC json file.
# --------------------------------------------------------------------------- #
from . import pad_library, region_library

PAD_COLLECTION = "Rigo Pads"
PAD_PREFIX = "PAD_"

# Reentrancy guard: the prefill callback sets other properties, which must not
# re-trigger anything; it also fires during .blend load, so it must never raise.
_PAD_PREFILL_BUSY = [False]


def _on_pad_type_selected(self, context):
    """Selecting a library shape pre-fills its favourite depth/size/kind."""
    if _PAD_PREFILL_BUSY[0]:
        return
    _PAD_PREFILL_BUSY[0] = True
    try:
        entry = pad_library.get_entry(self.pad_type)
        if entry is not None:
            self.pad_depth = float(entry.get("depth_mm", 8.0))
            self.pad_size = float(entry.get("size_mm", 90.0))
            self.pad_kind = entry.get("kind", "PRESSURE")
    except Exception:
        pass
    finally:
        _PAD_PREFILL_BUSY[0] = False


def _landmark_enum_items(self, context):
    return [(ident, label, desc) for ident, label, desc in LANDMARKS]


def _trim_type_items(self, context):
    from . import trim_templates
    return trim_templates.type_enum_items(self, context)


# Name of the live "derotation" deform modifier and its origin empty.
DEFORM_MODIFIER = "Rigo Deform"
DEFORM_ORIGIN = "Rigo Deform Origin"
# Three draggable section rings.  An active pair (lower-middle or middle-upper)
# drives the modifier limits; the remaining body segment stays rigid.
DEFORM_RING_LOWER = "Rigo Lower Ring"
DEFORM_RING_MIDDLE = "Rigo Middle Ring"
DEFORM_RING_UPPER = "Rigo Upper Ring"
# Legacy aliases keep old saved files and scripts importable.
DEFORM_PLANE_FROM = DEFORM_RING_LOWER
DEFORM_PLANE_TO = DEFORM_RING_UPPER
# Red axis-of-rotation indicator (LeoSpinal's red line), parented to the From
# plane so it always marks where the correction pivots.
DEFORM_AXIS = "Rigo Bend Axis"


def _update_deform(self, context):
    """Live-drive the active deform modifier from the sliders."""
    import math

    scan = self.scan_object or context.active_object
    if scan is None:
        return
    mod = scan.modifiers.get(DEFORM_MODIFIER)
    if mod is None:
        return
    if mod.deform_method == "BEND":
        mod.angle = math.radians(self.bend_angle)
    elif mod.deform_method == "TWIST":
        mod.angle = math.radians(self.twist_angle)
    elif mod.deform_method == "STRETCH":
        scan["rigo_requested_stretch_mm"] = self.stretch_mm
        gain = max(float(scan.get("rigo_stretch_gain", 1.0)), 1e-6)
        mod.factor = self.stretch_mm * 0.001 / gain


def _update_deform_range(self, context):
    """Live-drive the deform modifier's affected range (the two planes).

    From/To are millimetres above the scan's base.  Below 'From' the body is
    frozen (the origin empty sits on that plane), above 'To' it is carried
    rigidly — matching LeoSpinal's movable deform planes.
    """
    scan = self.scan_object or context.active_object
    if scan is None:
        return
    mod = scan.modifiers.get(DEFORM_MODIFIER)
    if mod is None:
        return
    z_min = scan.get("rigo_deform_zmin")
    span = scan.get("rigo_deform_zspan")
    if z_min is None or not span:
        return
    lo_mm, hi_mm = sorted((self.deform_from, self.deform_to))

    # Preferred path: position the draggable rings — drivers propagate their
    # world Z into the modifier limits and the origin empty.
    plane_lo = bpy.data.objects.get(DEFORM_PLANE_FROM)
    plane_hi = bpy.data.objects.get(DEFORM_PLANE_TO)
    if plane_lo is not None and plane_hi is not None:
        plane_lo.location.z = z_min + lo_mm * 0.001
        plane_hi.location.z = z_min + hi_mm * 0.001
        return

    # Fallback (no rings in the scene): write the limits directly.
    lo = max(0.0, min(1.0, lo_mm * 0.001 / span))
    hi = max(0.0, min(1.0, hi_mm * 0.001 / span))
    mod.limits[0] = lo
    mod.limits[1] = hi
    origin = bpy.data.objects.get(DEFORM_ORIGIN)
    if origin is not None:
        origin.location.z = z_min + lo * span


def _update_xray(self, context):
    """Live-drive the X-ray overlay opacity."""
    img = bpy.data.objects.get("Rigo X-ray")
    if img is not None and img.type == "EMPTY":
        img.use_empty_image_alpha = True
        img.color[3] = self.xray_opacity


# Name of the generated corset object.
CORSET_NAME = "Rigo Corset"
# Hidden, untrimmed shell kept so the top trim line can be re-applied freely.
CORSET_BASE_NAME = "Rigo Corset Base"
# Editable Bezier curve that drives the top trim line.
OUTLINE_CURVE_NAME = "Rigo Outline"
BUILD_TRIM_PERIMETER_NAME = "Rigo Build Trim Perimeter"


def _update_corset_opacity(self, context):
    """Live-drive the generated corset's display alpha."""
    corset = bpy.data.objects.get(CORSET_NAME)
    if corset is None:
        return
    corset.color[3] = self.corset_opacity
    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.shading.color_type = "OBJECT"


def invalidate_brace_qa(brace, reason="Brace geometry changed"):
    """Clear a previous manufacturing result without marking a brace dirty."""
    if brace is None:
        return False
    brace["rigo_qa_pass"] = False
    brace["rigo_qa_report"] = f"OUT OF DATE: {reason}; verify QA again"
    for key in (
        "rigo_qa_signature",
        "rigo_qa_boundary",
        "rigo_qa_nonmanifold",
        "rigo_qa_self_intersections",
        "rigo_qa_min_thickness_mm",
        "rigo_qa_thickness_coverage",
    ):
        if key in brace:
            del brace[key]
    return True


def mark_brace_dirty(context, reason="Design parameters changed"):
    """Invalidate a generated brace without rebuilding it during slider edits."""
    if context is None or getattr(context, "scene", None) is None:
        return False
    settings = getattr(context.scene, "rigo_brace", None)
    brace = bpy.data.objects.get(CORSET_NAME)
    if settings is None or brace is None:
        return False
    settings.brace_dirty = True
    brace["rigo_brace_dirty"] = True
    brace["rigo_brace_dirty_reason"] = reason
    invalidate_brace_qa(brace, reason)
    brace["rigo_qa_report"] = f"OUT OF DATE: {reason}; click Update Brace"
    return True


def _mark_brace_parameter_dirty(self, context):
    mark_brace_dirty(context, "Thickness, offset or fairing changed")


def brace_ready_for_finishing(context):
    """True only for the current, visible brace-preview working state."""
    if context is None or getattr(context, "scene", None) is None:
        return False
    settings = getattr(context.scene, "rigo_brace", None)
    brace = bpy.data.objects.get(CORSET_NAME)
    if settings is None or brace is None or brace.type != "MESH":
        return False
    return (
        not settings.brace_dirty
        and not bool(brace.get("rigo_brace_dirty", False))
        and brace_has_source_record(brace)
        and settings.design_view_mode == "BRACE"
        and not brace.hide_get()
    )


# The one canonical workflow used by the panel, toolbar, workspaces and navigation.
WORKFLOW_TABS = (
    ("FILE", "File", "Import the patient scan", "FILE_FOLDER"),
    ("SCAN", "Scan", "Scale, align and clean the raw scan", "MOD_REMESH"),
    ("LANDMARKS", "Landmarks", "Mark the anatomical reference points", "EMPTY_DATA"),
    ("MESH", "Mesh Edit", "Derotate, correct and remold the torso", "MOD_LATTICE"),
    ("DESIGN", "Design", "Generate, finish and export the brace", "MOD_SOLIDIFY"),
)

# Maps a workspace name (Option A: top tabs) to a workflow tab id.
WORKSPACE_TAB_MAP = {
    "Rigo File": "FILE",
    "Rigo Scan": "SCAN",
    "Rigo Landmarks": "LANDMARKS",
    "Rigo Mesh Edit": "MESH",
    "Rigo Design": "DESIGN",
}


# Compatibility view for the legacy mesh-snapshot module. Deriving it from the
# canonical workflow prevents a second stage list from drifting out of sync.
BRACE_STAGES = tuple((sid, label, assist) for sid, label, assist, _icon in WORKFLOW_TABS)

# Quick lookups (ordered ids + index).
BRACE_STAGE_IDS = tuple(s[0] for s in BRACE_STAGES)


def brace_stage_index(stage_id):
    try:
        return BRACE_STAGE_IDS.index(stage_id)
    except ValueError:
        return 0


def brace_stage_label(stage_id):
    for sid, label, _assist in BRACE_STAGES:
        if sid == stage_id:
            return label
    return stage_id


def brace_stage_assist(stage_id):
    for sid, _label, assist in BRACE_STAGES:
        if sid == stage_id:
            return assist
    return ""


class RigoCorrectionRegion(PropertyGroup):
    """One measurable pressure/expansion correction, stored ON the brace object.

    The clinical record of a correction: what it is (anatomical label + kind),
    where (centroid + mean surface normal of the painted region), how much
    (magnitude/radius in mm) and exactly which vertices (the falloff-weighted
    vertex group named in ``surface_mask``).  Never "some vertices I moved" —
    every correction is reproducible, undoable and reviewable (DEC-0014).
    """

    # PropertyGroup provides ``name`` (used as the user-facing label).
    anatomical_label: EnumProperty(
        name="Landmark",
        description="Anatomical site this correction belongs to",
        items=[("NONE", "—", "No specific landmark")]
        + [(i, l, d) for i, l, d in LANDMARKS],
        default="NONE",
    )
    kind: EnumProperty(
        name="Kind",
        description="Pressure pushes the surface in; Expansion lifts it out",
        items=(
            ("PRESSURE", "Pressure", "Corrective push toward the body (inward)"),
            ("EXPANSION", "Expansion", "Relief space away from the body (outward)"),
        ),
        default="PRESSURE",
    )
    center: FloatVectorProperty(
        name="Center", subtype="XYZ", size=3, default=(0.0, 0.0, 0.0)
    )
    direction: FloatVectorProperty(
        name="Direction", subtype="XYZ", size=3, default=(0.0, 0.0, 1.0),
        description="Mean outward surface normal of the region (object space)",
    )
    magnitude_mm: FloatProperty(
        name="Amount (mm)",
        description="How far the surface moves at the region core",
        default=5.0, min=0.0, max=60.0, soft_max=25.0,
    )
    radius_mm: FloatProperty(
        name="Radius (mm)",
        description="Measured extent of the painted region (informational)",
        default=0.0, min=0.0,
    )
    falloff_type: EnumProperty(
        name="Falloff",
        items=(
            ("SMOOTH", "Smooth", "Smoothstep feather (recommended)"),
            ("LINEAR", "Linear", "Straight-line feather"),
            ("SHARP", "Sharp", "Narrow feather, hard edge"),
        ),
        default="SMOOTH",
    )
    surface_mask: StringProperty(
        name="Mask",
        description="Vertex group holding the region weights (the falloff)",
        default="",
    )
    opposing_region: IntProperty(
        name="Opposing",
        description="Index of the coupled opposite-side region (-1 = none)",
        default=-1,
    )
    enabled: BoolProperty(name="Enabled", default=True)
    requires_review: BoolProperty(
        name="Requires Orthotist Review", default=True,
        description="Clinical safety: every correction is reviewed by the orthotist",
    )


class RigoBraceSettings(PropertyGroup):
    """All tunable values for the brace pipeline, stored per-scene."""

    # --- UI navigation ------------------------------------------------------ #
    ui_mode: EnumProperty(
        name="Layout",
        description="How to switch between workflow stages",
        items=(
            ("PANEL", "Side Panel Tabs", "Tab buttons inside one side panel (Option B)"),
            ("WORKSPACE", "Top Tabs", "Blender workspace tabs across the top (Option A)"),
        ),
        default="PANEL",
    )
    # --- Canonical workflow ------------------------------------------------- #
    brace_stage: EnumProperty(
        name="Workflow Stage",
        description="Current stage shown by every Rigo Brace navigation control",
        items=[(sid, label, assist) for sid, label, assist in BRACE_STAGES],
        default="FILE",
    )
    brace_patient: StringProperty(
        name="Patient",
        description="Name used to group this design's version history",
        default="",
    )

    # --- Scan settings ------------------------------------------------------ #
    scan_units: EnumProperty(
        name="Scan Units",
        description="The real-world unit the imported scan was saved in",
        items=(
            ("mm", "Millimeters", "Scan is in millimeters"),
            ("cm", "Centimeters", "Scan is in centimeters"),
            ("m", "Meters", "Scan is in meters"),
        ),
        default="mm",
    )

    # --- Working objects ---------------------------------------------------- #
    scan_object: PointerProperty(
        name="Patient Scan",
        description="The imported body scan currently being worked on",
        type=bpy.types.Object,
    )

    # --- Remesh ------------------------------------------------------------- #
    remesh_voxel: FloatProperty(
        name="Voxel Size (mm)",
        description="Smaller = more detail and more triangles. 3-5 mm is a good start",
        default=4.0,
        min=0.5,
        max=20.0,
        soft_max=10.0,
    )

    quad_target_faces: IntProperty(
        name="Quad Faces",
        description=(
            "Target face count for Quad Remesh (ZRemesher-style flow topology). "
            "Fewer faces = lighter, smoother-deforming mesh; 5000-10000 suits a torso"
        ),
        default=8000,
        min=500,
        max=200000,
        soft_max=50000,
    )

    quad_remesh_engine: EnumProperty(
        name="Quad Remesher",
        description="Choose the topology engine used by Quad Remesh",
        items=(
            (
                "EXOSIDE",
                "Exoside Quad Remesher",
                "Commercial Quad Remesher bridge; best option for organic torso flow",
            ),
            (
                "BLENDER",
                "Blender QuadriFlow",
                "Built-in fallback; requires a closed manifold scan",
            ),
        ),
        default="EXOSIDE",
    )

    quad_adaptive_size: FloatProperty(
        name="Curvature Adaptation",
        description=(
            "Places smaller quads in curved areas; 50 percent is a balanced start"
        ),
        default=50.0,
        min=0.0,
        max=100.0,
        subtype="PERCENTAGE",
    )

    # --- Guided sculpt (CorrectionRegion) defaults at Add time --------------- #
    region_kind: EnumProperty(
        name="Kind",
        items=(
            ("PRESSURE", "Pressure", "Corrective push toward the body (inward)"),
            ("EXPANSION", "Expansion", "Relief space away from the body (outward)"),
        ),
        default="PRESSURE",
    )
    region_magnitude: FloatProperty(
        name="Amount (mm)",
        description="Default correction depth for a newly added region",
        default=5.0, min=0.0, max=60.0, soft_max=25.0,
    )
    region_feather: FloatProperty(
        name="Feather (mm)",
        description="Width of the soft edge from full effect down to zero",
        default=10.0, min=0.0, max=60.0, soft_max=30.0,
    )
    region_radius: FloatProperty(
        name="Circle Radius (mm)",
        description="Radius of a quick circular region dropped at the 3D cursor",
        default=30.0, min=2.0, max=150.0, soft_max=80.0,
    )
    region_falloff: EnumProperty(
        name="Falloff",
        description="How the effect fades from the region core to its edge",
        items=(
            ("SMOOTH", "Smooth", "Smoothstep feather (recommended)"),
            ("LINEAR", "Linear", "Straight-line feather"),
            ("SHARP", "Sharp", "Narrow feather, hard edge"),
        ),
        default="SMOOTH",
    )
    region_style: EnumProperty(
        name="Saved Style",
        description="Reusable pressure/expansion mask authored and reviewed by you",
        items=region_library.enum_items,
    )

    # --- Lattice derotation --------------------------------------------------- #
    lattice_sections: IntProperty(
        name="Sections",
        description="Horizontal slices of the cage — each can rotate independently",
        default=5, min=2, max=10,
    )
    lattice_twist: FloatProperty(
        name="Twist (°)",
        description=(
            "Total derotation at the top section; distributed as a gradient "
            "from 0 at the pelvis upward (fine-tune per section afterwards)"
        ),
        default=10.0, min=-180.0, max=180.0, soft_min=-45.0, soft_max=45.0,
    )

    corset_smooth: IntProperty(
        name="Surface Fairing",
        description=(
            "Gentle volume-preserving removal of scan texture before trimming. "
            "Use Scan cleanup for major smoothing; 0 preserves the corrected mold"
        ),
        default=5, min=0, max=30, soft_max=15,
        update=_mark_brace_parameter_dirty,
    )

    # --- Auto trim lines (Rigo templates) ------------------------------------- #
    trim_source_mode: EnumProperty(
        name="Trimline Source",
        description="Use a landmark template or paint the wanted brace area",
        items=(
            (
                "TEMPLATE",
                "Template",
                "Generate the reviewed landmark-driven Rigo perimeter",
            ),
            (
                "CUSTOM_PAINT",
                "Custom Paint",
                "Paint the brace area green and extract its boundary",
            ),
        ),
        default="TEMPLATE",
    )
    trim_type: EnumProperty(
        name="Rigo Type",
        description=(
            "Which clinic reference brace the auto trim lines follow "
            "(templates extracted from your A/B reference pairs)"
        ),
        items=_trim_type_items,
    )

    trim_brush_radius: FloatProperty(
        name="Brush Radius (mm)",
        description=(
            "Arc-length radius of the local trimline smoothing brush; points "
            "outside this distance and points hidden behind the body stay fixed"
        ),
        default=60.0,
        min=5.0,
        max=150.0,
        soft_max=100.0,
    )
    trim_brush_strength: FloatProperty(
        name="Brush Strength",
        description=(
            "Strength of each local, surface-following trimline relaxation dab"
        ),
        default=0.60,
        min=0.05,
        max=1.0,
    )
    trim_brush_lock_opening: BoolProperty(
        name="Lock Opening Corners",
        description=(
            "Keep the four opening transitions and vertical opening edges fixed "
            "while brushing"
        ),
        default=True,
    )
    trim_smooth_mm: FloatProperty(
        name="Trimline Smoothing (mm)",
        description=(
            "Size of the boundary wobble removed when the trimline is created. "
            "Applied once in a single pass — this is a physical size, not a "
            "number of iterations, so the same value always gives the same "
            "line. 0 keeps the painted boundary exactly"
        ),
        default=8.0,
        min=0.0,
        max=40.0,
        soft_max=25.0,
    )
    trim_custom_spacing: FloatProperty(
        name="Boundary Detail (mm)",
        description=(
            "Spacing of the surface-bound controls extracted from the painted "
            "brace area; smaller values retain more detail"
        ),
        default=6.0,
        min=2.0,
        max=15.0,
        soft_max=10.0,
    )
    trim_mask_steps: IntProperty(
        name="Mask Steps",
        description="Number of grow or shrink rings applied to the painted mask",
        default=1,
        min=1,
        max=20,
        soft_max=5,
    )
    trim_mask_smooth: IntProperty(
        name="Mask Smooth Passes",
        description=(
            "Neighbour averaging passes used only when Smooth Mask is pressed; "
            "Create Trimline does not add hidden smoothing"
        ),
        default=8,
        min=1,
        max=50,
        soft_max=20,
    )

    # --- Trim edge finishing -------------------------------------------------- #
    trim_smooth_iters: IntProperty(
        name="Smooth Passes",
        description="How strongly to relax the jagged cut edge of the shell",
        default=50, min=1, max=500, soft_max=200,
    )
    trim_fillet_radius: FloatProperty(
        name="Trim Fillet Radius (mm)",
        description=(
            "Requested round-over radius around the complete trim rim; "
            "wall thickness and local overlap safety can limit it"
        ),
        default=1.00,
        min=0.20,
        max=3.0,
        soft_max=2.0,
        update=_mark_brace_parameter_dirty,
    )
    trim_fillet_segments: IntProperty(
        name="Fillet Smoothness",
        description="Number of geometric segments across the trim round-over",
        default=8,
        min=2,
        max=12,
        soft_max=8,
        update=_mark_brace_parameter_dirty,
    )
    trim_transition_width: FloatProperty(
        name="Trim Transition (mm)",
        description=(
            "Width of the progressively refined mesh below the trim edge; "
            "a wider band blends the fine rim into the brace body"
        ),
        default=30.0,
        min=5.0,
        max=60.0,
        soft_max=40.0,
        update=_mark_brace_parameter_dirty,
    )
    edge_flare: FloatProperty(
        name="Flare (mm)",
        description="How far the shell edge bends away from the body",
        default=6.0, min=0.0, max=30.0, soft_max=15.0,
    )
    edge_band: FloatProperty(
        name="Edge Band (mm)",
        description="Width of the edge zone the smoothing/flare works on",
        default=15.0, min=2.0, max=60.0, soft_max=40.0,
    )

    # --- Ventilation ---------------------------------------------------------- #
    vent_diameter: FloatProperty(
        name="Hole Ø (mm)",
        description="Diameter of each ventilation hole",
        default=6.0, min=1.0, max=30.0, soft_max=12.0,
    )
    vent_spacing: FloatProperty(
        name="Spacing (mm)",
        description=(
            "Centre-to-centre distance of the hole grid. The bridge between "
            "holes (spacing − Ø) must stay ≥ 3 mm to be printable"
        ),
        default=15.0, min=3.0, max=80.0, soft_max=40.0,
    )
    lattice_pattern: EnumProperty(
        name="Pattern",
        description="Cell geometry used by the manufacturing lattice",
        items=(
            ("DIAMOND", "Diamond", "Rhombus cells with diagonal load paths"),
            ("SQUARE", "Square", "Orthogonal square cells"),
            ("HEX", "Hexagonal", "Honeycomb-style six-sided cells"),
        ),
        default="DIAMOND",
    )
    lattice_finish_mode: EnumProperty(
        name="Result",
        description="Cut open cells or add a raised reinforcing lattice",
        items=(
            ("CUT", "Ventilation", "Cut the cell interiors through the brace"),
            ("ADD", "Reinforcement", "Add raised ribs around the cells"),
        ),
        default="CUT",
    )
    lattice_cell_size: FloatProperty(
        name="Cell Size (mm)",
        description="Outside diameter of each lattice cell",
        default=14.0,
        min=5.0,
        max=50.0,
        soft_max=25.0,
    )
    lattice_bar_width: FloatProperty(
        name="Bar Width (mm)",
        description="Material bridge left between ventilation cells or added as ribs",
        default=3.0,
        min=1.0,
        max=12.0,
        soft_max=6.0,
    )
    lattice_height: FloatProperty(
        name="Reinforcement Height (mm)",
        description="Height added above the brace in Reinforcement mode",
        default=1.5,
        min=0.3,
        max=8.0,
        soft_max=4.0,
    )

    # --- Smooth ------------------------------------------------------------- #
    smooth_iterations: IntProperty(
        name="Smooth Passes",
        description="How many times to relax the surface",
        default=10,
        min=1,
        max=200,
    )
    smooth_factor: FloatProperty(
        name="Smooth Strength",
        description="Strength of each smoothing pass",
        default=0.5,
        min=0.0,
        max=1.0,
    )

    # --- Remold (sculpt) ---------------------------------------------------- #
    remold_brush_size: IntProperty(
        name="Brush Size",
        description="Radius of the remold brush, in screen pixels",
        default=80,
        min=5,
        max=500,
    )
    remold_brush_strength: FloatProperty(
        name="Brush Strength",
        description="How strongly the remold brush pushes the surface",
        default=0.4,
        min=0.0,
        max=1.0,
    )

    # --- Mesh edit: derotation deform tools --------------------------------- #
    deform_region: EnumProperty(
        name="Region",
        description="Which part of the body the deform affects",
        items=(
            ("ALL", "All", "Affect the whole model"),
            ("BOTTOM", "Bottom Part", "Affect only the lower portion"),
        ),
        default="ALL",
    )
    deform_segment: EnumProperty(
        name="Active Segment",
        description="Which pair of the three draggable rings bounds the deformation",
        items=(
            ("LOWER", "Lower ↔ Middle", "Modify the lower segment; upper stays rigid"),
            ("UPPER", "Middle ↔ Upper", "Modify the upper segment; lower stays fixed"),
            ("FULL", "Lower ↔ Upper", "Modify the full model using the outer rings"),
        ),
        default="UPPER",
    )
    bend_angle: FloatProperty(
        name="Bend",
        description="Bend angle in degrees (coronal/sagittal correction)",
        default=0.0,
        min=-90.0,
        max=90.0,
        update=_update_deform,
    )
    twist_angle: FloatProperty(
        name="Twist",
        description="Twist angle in degrees (transverse-plane derotation)",
        default=0.0,
        min=-90.0,
        max=90.0,
        update=_update_deform,
    )
    stretch_factor: FloatProperty(
        name="Legacy Stretch Factor",
        description="Compatibility value from older files; use Stretch (mm)",
        default=0.0,
        min=-1.0,
        max=2.0,
    )
    stretch_mm: FloatProperty(
        name="Stretch (mm)",
        description="Requested axial stretch (+) or reduction (-) in millimetres",
        default=0.0,
        min=-200.0,
        max=500.0,
        soft_min=-100.0,
        soft_max=150.0,
        update=_update_deform,
    )
    scale_amount: FloatProperty(
        name="Inflate / Deflate",
        description="Grow (+) or shrink (-) girth as a fraction",
        default=0.10,
        min=-0.5,
        max=0.5,
    )
    deform_from: FloatProperty(
        name="From (mm)",
        description="Lower deform plane: height above the base where the "
        "correction starts — everything below stays fixed",
        default=0.0,
        min=0.0,
        max=1000000.0,   # hard max generous: unscaled scans are metres-huge
        soft_max=2500.0,
        update=_update_deform_range,
    )
    deform_to: FloatProperty(
        name="To (mm)",
        description="Upper deform plane: height above the base where the "
        "correction ends — everything above moves rigidly with it",
        default=650.0,
        min=0.0,
        max=1000000.0,
        soft_max=2500.0,
        update=_update_deform_range,
    )

    # --- Mesh edit: X-ray overlay ------------------------------------------- #
    xray_opacity: FloatProperty(
        name="X-ray Opacity",
        description="See-through level of the imported X-ray overlay",
        default=0.5,
        min=0.0,
        max=1.0,
        update=_update_xray,
    )

    # --- Pressure / Relief library ------------------------------------------ #
    pad_type: EnumProperty(
        name="Shape",
        description="Modification shape from the library (★ = recorded by you). "
        "Selecting one loads its favourite depth, size and kind",
        items=pad_library.pad_enum_items,
        update=_on_pad_type_selected,
    )
    pad_kind: EnumProperty(
        name="Effect",
        description="What the shape does to the surface when applied",
        items=(
            ("PRESSURE", "Pressure (in)", "Push the surface inward (corrective force)"),
            ("EXPANSION", "Expansion (out)", "Build a relief chamber outward"),
        ),
        default="PRESSURE",
    )
    pad_depth: FloatProperty(
        name="Depth (mm)",
        description="How far the shape pushes. Pressure pushes in, expansion out",
        default=8.0,
        min=0.0,
        max=40.0,
    )
    pad_size: FloatProperty(
        name="Size (mm)",
        description="Width of the shape when placed on the scan",
        default=90.0,
        min=20.0,
        max=400.0,
        soft_max=200.0,
    )
    active_pad: PointerProperty(
        name="Active Pad",
        description="The pad shape currently selected for editing",
        type=bpy.types.Object,
    )

    # --- Correction (free-form / lattice) ----------------------------------- #
    correction_lattice: PointerProperty(
        name="Correction Cage",
        description="The lattice used to deform the scan for curve correction",
        type=bpy.types.Object,
    )
    correction_div_width: IntProperty(
        name="Width Divisions",
        description="Control points across the body (left-right)",
        default=3,
        min=2,
        max=10,
    )
    correction_div_depth: IntProperty(
        name="Depth Divisions",
        description="Control points front-to-back",
        default=3,
        min=2,
        max=10,
    )
    correction_div_height: IntProperty(
        name="Height Divisions",
        description="Control points up the spine (more = finer curve control)",
        default=6,
        min=2,
        max=20,
    )

    # --- Painted region selection ------------------------------------------- #
    select_grow_steps: IntProperty(
        name="Grow/Shrink Steps",
        description="How far to expand or contract the painted region each click",
        default=1,
        min=1,
        max=20,
    )
    select_depth: FloatProperty(
        name="Depth (mm)",
        description="How far to push the selected area in or out",
        default=5.0,
        min=0.0,
        max=40.0,
    )
    select_thickness: FloatProperty(
        name="Local Thickness (mm)",
        description="Wall thickness added over the selected area only",
        default=4.0,
        min=0.5,
        max=15.0,
    )
    select_smooth_factor: FloatProperty(
        name="Smooth Strength",
        description="Strength of each smoothing pass over the painted area",
        default=0.5,
        min=0.0,
        max=1.0,
    )
    select_smooth_iters: IntProperty(
        name="Smooth Passes",
        description="How many smoothing passes to run over the painted area",
        default=5,
        min=1,
        max=50,
    )

    # --- Thickness / shell -------------------------------------------------- #
    shell_thickness: FloatProperty(
        name="Brace Thickness (mm)",
        description="Wall thickness of the finished brace",
        default=4.0,
        min=1.0,
        max=15.0,
    )

    # --- Design / corset ---------------------------------------------------- #
    design_style: EnumProperty(
        name="Design",
        description="Brace style to generate",
        items=(
            ("CHENEAU", "Cheneau", "Asymmetric Rigo-Cheneau style with openings"),
            ("BOSTON", "Boston", "Symmetric TLSO with a posterior opening"),
        ),
        default="CHENEAU",
    )
    corset_thickness: FloatProperty(
        name="General Thickness (mm)",
        description="Wall thickness of the corset shell",
        default=4.0,
        min=1.5,
        max=12.0,
        update=_mark_brace_parameter_dirty,
    )
    corset_offset: FloatProperty(
        name="General Offset (mm)",
        description="Gap left between body and shell for a padded liner",
        default=3.0,
        min=0.0,
        max=15.0,
        update=_mark_brace_parameter_dirty,
    )
    brace_dirty: BoolProperty(
        name="Brace Out of Date",
        description="The visible brace was generated from older design parameters",
        default=False,
        options={"HIDDEN"},
    )
    design_view_mode: EnumProperty(
        name="Design View",
        items=(
            ("TRIM", "Edit Trimlines", "Show corrected body and trim perimeter"),
            ("BRACE", "Brace Preview", "Show only the generated brace"),
        ),
        default="TRIM",
        options={"HIDDEN"},
    )
    trim_top: FloatProperty(
        name="Trim Top (mm)",
        description="How much to cut from the top edge",
        default=20.0,
        min=0.0,
        max=300.0,
    )
    trim_bottom: FloatProperty(
        name="Trim Bottom (mm)",
        description="How much to cut from the bottom edge",
        default=20.0,
        min=0.0,
        max=300.0,
    )
    opening_width: FloatProperty(
        name="Opening Width (mm)",
        description="Measured straight-line width of the anterior closure gap",
        default=25.0,
        min=10.0,
        max=80.0,
        soft_min=15.0,
        soft_max=50.0,
    )
    corset_opacity: FloatProperty(
        name="Corset Opacity",
        description="See-through level of the generated corset",
        default=1.0,
        min=0.1,
        max=1.0,
        update=_update_corset_opacity,
    )
    reinforcement: BoolProperty(
        name="Reinforcement Edge",
        description="Add a thicker reinforcing rim around the trim edges",
        default=False,
    )
    symmetrical: BoolProperty(
        name="Symmetrical",
        description="Mirror strap slots left/right (Boston style)",
        default=False,
    )

    # --- Top trim line (editable outline) ----------------------------------- #
    outline_segments: IntProperty(
        name="Outline Points",
        description="Number of control points around the editable top trim line",
        default=12,
        min=6,
        max=32,
    )
    outline_editing: BoolProperty(
        name="Editing Outline",
        description="True while the top trim line is being edited",
        default=False,
    )

    # --- Strap slots -------------------------------------------------------- #
    slot_width: FloatProperty(
        name="Slot Length (mm)",
        description="Long vertical dimension of the strap opening",
        default=40.0,
        min=10.0,
        max=120.0,
    )
    slot_height: FloatProperty(
        name="Slot Width (mm)",
        description="Short dimension across the strap opening",
        default=12.0,
        min=4.0,
        max=40.0,
    )
    slot_edge_radius: FloatProperty(
        name="Edge Fillet (mm)",
        description=(
            "Round-over radius on both faces of the cut strap slot; the "
            "effective radius is safely clamped to the brace wall"
        ),
        default=0.8,
        min=0.0,
        max=3.0,
        precision=2,
    )

    # --- Rivet holes ------------------------------------------------------- #
    rivet_diameter: FloatProperty(
        name="Rivet Hole Diameter (mm)",
        description="Diameter of the editable circular rivet contour",
        default=4.0,
        min=1.5,
        max=15.0,
        soft_max=8.0,
        precision=2,
    )
    rivet_edge_radius: FloatProperty(
        name="Edge Fillet (mm)",
        description="Round-over radius on both faces of each rivet hole",
        default=0.4,
        min=0.0,
        max=2.0,
        precision=2,
    )

    # --- Embossing ---------------------------------------------------------- #
    emboss_text: StringProperty(
        name="Text",
        description="Name or note embossed into the brace",
        default="",
    )
    emboss_depth: FloatProperty(
        name="Emboss Depth (mm)",
        default=1.0,
        min=0.2,
        max=5.0,
    )
    emboss_size: FloatProperty(
        name="Text Height (mm)",
        description="Nominal height of the embossed lettering",
        default=12.0,
        min=3.0,
        max=40.0,
        soft_max=20.0,
    )
    emboss_mode: EnumProperty(
        name="Style",
        description="Create raised lettering or engrave it into the brace",
        items=(
            ("RAISED", "Raised", "Fuse raised lettering to the outer wall"),
            ("ENGRAVED", "Engraved", "Cut lettering into the outer wall"),
        ),
        default="RAISED",
    )

    # --- Landmark placement ------------------------------------------------- #
    active_landmark: EnumProperty(
        name="Landmark",
        description="Anatomical point to place next",
        items=_landmark_enum_items,
    )

    # --- Export ------------------------------------------------------------- #
    qa_min_thickness: FloatProperty(
        name="Minimum Wall (mm)",
        description=(
            "Manufacturing QA threshold selected for this material/process; "
            "confirm it with the clinic and fabricator"
        ),
        default=3.0,
        min=0.5,
        max=12.0,
        soft_max=6.0,
    )
    export_path: StringProperty(
        name="Export Folder",
        description="Where the print-ready brace STL will be saved",
        subtype="DIR_PATH",
        default="//",
    )


_CLASSES = (RigoCorrectionRegion, RigoBraceSettings)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.rigo_brace = PointerProperty(type=RigoBraceSettings)
    # Corrections travel WITH the mesh they correct (saved in the .blend,
    # duplicated with history versions) — hence Object, not Scene.
    bpy.types.Object.rigo_regions = CollectionProperty(type=RigoCorrectionRegion)
    bpy.types.Object.rigo_region_index = IntProperty(default=0)


def unregister():
    del bpy.types.Object.rigo_region_index
    del bpy.types.Object.rigo_regions
    del bpy.types.Scene.rigo_brace
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
