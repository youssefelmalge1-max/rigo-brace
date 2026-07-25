"""Design tab: corset generation and finishing.

The corrected, padded torso is turned into a wearable shell:

    Generate  -> offset the body for a liner gap, give it wall thickness, then
                 trim top/bottom and open a closure gap (Cheneau / Boston).
    Slots     -> click on the shell to cut strap slots (manual placement).
    Emboss    -> press a name / note into the shell.

Everything is built with native Blender meshing so the result is a clean,
print-ready solid.
"""

import heapq
import logging
import math
from dataclasses import dataclass

import bpy
import bmesh
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from ..core import (
    BUILD_TRIM_PERIMETER_NAME,
    CORSET_NAME,
    CORSET_BASE_NAME,
    OUTLINE_CURVE_NAME,
    brace_ready_for_finishing,
    invalidate_brace_qa,
)
from ..core.signatures import geometry_signature
from .mesh_intersections import triangle_intersection_pairs

_SLOT_COLLECTION = "Rigo Slots"
_SLOT_PREFIX = "SLOT_"
_RIM_BOUNDARY_GROUP = "RIGO_RIM_BOUNDARY"
_CORSET_CANDIDATE_NAME = "Rigo Corset Candidate"
_CORSET_BASE_CANDIDATE_NAME = "Rigo Corset Base Candidate"
_CORSET_BACKUP_NAME = "Rigo Corset Previous"
_CORSET_BASE_BACKUP_NAME = "Rigo Corset Base Previous"
_OUTER_REPAIR_BLEND = 0.25
_OUTER_REPAIR_MAX_ITERATIONS = 12
_OUTER_REPAIR_MAX_ANGLE_RAD = math.radians(25.0)
_TRIM_BOUNDARY_TARGET_M = 0.0006
_TRIM_BOUNDARY_SMOOTH_CYCLES = 18
_TRIM_BOUNDARY_MAX_STEP_M = 0.00015
_TRIM_BOUNDARY_CLEARANCE_M = 0.0
_TRIM_BOUNDARY_MAX_SURFACE_GAP_M = 2.0e-4
_TRIM_BRANCH_REPAIR_MAX_EDGE_M = 0.0015
_TRIM_BAND_TARGET_M = 0.0012
_TRIM_BAND_RINGS = 3
_TRIM_TRANSITION_INNER_TARGET_M = 0.005
_SLOT_ARC_SEGMENTS = 16
_SLOT_BEVEL_SEGMENTS = 4
_SLOT_MIN_CUTTER_DEPTH_M = 0.012
_EMBOSS_PREVIEW_NAME = "Rigo Emboss Preview"
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SourceSurface:
    coordinates: list
    normals: list
    triangles: list
    bvh: BVHTree


@dataclass(frozen=True)
class _OuterRepairStats:
    initial_pairs: int
    remaining_pairs: int
    iterations: int
    modified_vertices: int
    max_direction_change_deg: float


@dataclass(frozen=True)
class _GenerationSnapshot:
    previous_base: object
    previous_brace: object
    view_mode: str
    outline_editing: bool
    brace_dirty: bool


@dataclass
class _GenerationCandidates:
    base: object = None
    brace: object = None
    remove_outline: bool = True


@dataclass(frozen=True)
class _SlotPlacement:
    name: str
    location: Vector
    normal: Vector
    length_mm: float
    width_mm: float


class OuterWallIntersectionError(RuntimeError):
    """The requested paired wall cannot be made without crossing itself."""

    def __init__(self, thickness_mm, remaining_pairs, maximum_angle_deg):
        self.thickness_mm = thickness_mm
        self.remaining_pairs = remaining_pairs
        self.maximum_angle_deg = maximum_angle_deg
        super().__init__(
            f"Requested {thickness_mm:.1f} mm wall cannot be generated without "
            "outer-wall overlap on this corrected shape. Increase Surface "
            "Fairing or reduce Thickness; scan and trimlines were not changed."
        )


class TrimRimQualityError(RuntimeError):
    """The requested trim/fillet combination is not a valid closed solid."""

    def __init__(
        self,
        intersections=0,
        zero_area=0,
        boundary_edges=0,
        nonmanifold_edges=0,
        components=0,
    ):
        self.intersections = intersections
        self.zero_area = zero_area
        self.boundary_edges = boundary_edges
        self.nonmanifold_edges = nonmanifold_edges
        self.components = components
        if components > 1:
            detail = (
                f"{components} separate pieces instead of one brace — the trim "
                "kept detached fragments"
            )
        elif intersections:
            detail = f"{intersections} local rim overlap(s)"
        elif boundary_edges or nonmanifold_edges:
            detail = (
                f"{boundary_edges} open and {nonmanifold_edges} "
                "non-manifold edge(s)"
            )
        else:
            detail = f"{zero_area} collapsed rim face(s)"
        super().__init__(
            f"Trim rim cannot be built safely ({detail}). Undo the last trim "
            "edit or reduce Trim Fillet Radius; the last valid brace was retained."
        )


class SlotCutError(RuntimeError):
    """A placed marker cannot produce exactly one valid local opening."""


class TrimPerimeterWindingError(RuntimeError):
    """The trim boundary encircles the body axis and bounds no brace area."""

    def __init__(self):
        super().__init__(
            "The trimline winds fully around the body without enclosing one "
            "brace area; paint a boundary with a clear top and bottom edge"
        )


def _scan(context):
    settings = context.scene.rigo_brace
    obj = settings.scan_object or context.active_object
    if obj is None or obj.type != "MESH":
        return None
    return obj


def _perimeter_belongs_to_scan(perimeter, scan):
    return bool(
        perimeter is not None
        and perimeter.type == "CURVE"
        and any(
            modifier.type == "SHRINKWRAP" and modifier.target is scan
            for modifier in perimeter.modifiers
        )
    )


def _remove_object_and_orphan_mesh(obj):
    if obj is None:
        return
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _prepare_candidate_base(context, scan, settings):
    """Copy and fair the scan, removing the private copy on any failure."""
    base = None
    prepared = False
    try:
        base = scan.copy()
        base.data = scan.data.copy()
        base.name = _CORSET_BASE_CANDIDATE_NAME
        base.data.name = _CORSET_BASE_CANDIDATE_NAME
        context.scene.collection.objects.link(base)

        offset = settings.corset_offset * 0.001
        if offset > 0.0:
            displacement = base.modifiers.new(
                name="Liner Offset", type="DISPLACE"
            )
            displacement.strength = offset
            displacement.mid_level = 0.0
            displacement.direction = "NORMAL"
            _apply(context, base, "Liner Offset")

        if settings.corset_smooth > 0:
            smoothing = base.modifiers.new(
                name="Shell Fairing", type="LAPLACIANSMOOTH"
            )
            smoothing.lambda_factor = 0.12
            smoothing.lambda_border = 0.04
            smoothing.iterations = settings.corset_smooth
            smoothing.use_volume_preserve = True
            smoothing.use_normalized = True
            _apply(context, base, "Shell Fairing")
        prepared = True
        return base
    finally:
        if not prepared:
            _remove_object_and_orphan_mesh(base)


def _object_is_registered(obj):
    if obj is None:
        return False
    try:
        return bpy.data.objects.get(obj.name) is obj
    except ReferenceError:
        return False


def _capture_generation_snapshot(settings):
    return _GenerationSnapshot(
        previous_base=bpy.data.objects.get(CORSET_BASE_NAME),
        previous_brace=bpy.data.objects.get(CORSET_NAME),
        view_mode=settings.design_view_mode,
        outline_editing=settings.outline_editing,
        brace_dirty=settings.brace_dirty,
    )


def _restore_previous_names(snapshot):
    if _object_is_registered(snapshot.previous_brace):
        snapshot.previous_brace.name = CORSET_NAME
    if _object_is_registered(snapshot.previous_base):
        snapshot.previous_base.name = CORSET_BASE_NAME


def _restore_failed_generation(context, snapshot, candidates):
    """Remove exact candidates and restore the prior canonical state."""
    for candidate in (candidates.brace, candidates.base):
        is_previous = (
            candidate is snapshot.previous_brace
            or candidate is snapshot.previous_base
        )
        if is_previous:
            continue
        if _object_is_registered(candidate):
            _remove_object_and_orphan_mesh(candidate)
    _restore_previous_names(snapshot)
    context.view_layer.update()
    settings = context.scene.rigo_brace
    settings.outline_editing = snapshot.outline_editing
    settings.brace_dirty = snapshot.brace_dirty
    if snapshot.previous_brace is not None:
        _set_design_view(context, snapshot.view_mode)
    else:
        _set_design_view(context, "TRIM")


def _discard_after_commit(obj):
    """Best-effort cleanup that cannot invalidate an already committed build."""
    if not _object_is_registered(obj):
        return
    try:
        _remove_object_and_orphan_mesh(obj)
    except Exception as error:
        _LOGGER.warning(
            "Could not remove a superseded generation object", exc_info=error
        )
        try:
            if _object_is_registered(obj):
                obj.hide_set(True)
        except Exception as hide_error:
            _LOGGER.warning(
                "Could not hide a superseded generation object",
                exc_info=hide_error,
            )
            return


def _commit_generation(context, snapshot, candidates, settings):
    """Atomically replace canonical brace/base after both candidates pass."""
    replace_base = candidates.base is not snapshot.previous_base
    try:
        if snapshot.previous_brace is not None:
            snapshot.previous_brace.name = _CORSET_BACKUP_NAME
        if replace_base and snapshot.previous_base is not None:
            snapshot.previous_base.name = _CORSET_BASE_BACKUP_NAME
        candidates.brace.name = CORSET_NAME
        if replace_base:
            candidates.base.name = CORSET_BASE_NAME
        candidates.base.hide_set(True)
        candidates.brace.data.name = CORSET_NAME
        if replace_base:
            candidates.base.data.name = CORSET_BASE_NAME
        settings.outline_editing = False
        settings.brace_dirty = False
        if not _set_design_view(context, "BRACE"):
            raise RuntimeError("Could not activate the generated brace preview")
    except Exception:
        if _object_is_registered(candidates.brace):
            candidates.brace.name = _CORSET_CANDIDATE_NAME
        if replace_base and _object_is_registered(candidates.base):
            candidates.base.name = _CORSET_BASE_CANDIDATE_NAME
        _restore_previous_names(snapshot)
        settings.outline_editing = snapshot.outline_editing
        settings.brace_dirty = snapshot.brace_dirty
        raise

    replaced_objects = [snapshot.previous_brace]
    if replace_base:
        replaced_objects.append(snapshot.previous_base)
    for previous in replaced_objects:
        _discard_after_commit(previous)
    if candidates.brace.get("rigo_build_method") != "CURVE_EXACT":
        _discard_after_commit(bpy.data.objects.get(BUILD_TRIM_PERIMETER_NAME))
    if candidates.remove_outline:
        _discard_after_commit(bpy.data.objects.get(OUTLINE_CURVE_NAME))


def _rebuild_existing_base(context, settings, top_profile, remove_outline):
    """Transactionally rebuild only the brace from the canonical base."""
    snapshot = _capture_generation_snapshot(settings)
    if snapshot.previous_base is None:
        return None
    candidates = _GenerationCandidates(
        base=snapshot.previous_base,
        remove_outline=remove_outline,
    )
    try:
        candidates.brace = _build_corset(
            context,
            settings,
            top_profile=top_profile,
            base=candidates.base,
        )
        _commit_generation(context, snapshot, candidates, settings)
    except Exception:
        _restore_failed_generation(context, snapshot, candidates)
        raise
    return candidates.brace


def _select_only(context, obj):
    if context.object is not None and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for candidate in context.view_layer.objects:
        if candidate is not None:
            candidate.select_set(False)
    if obj is not None:
        obj.hide_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj


def _set_design_view(context, mode):
    """Expose one clear working state while retaining the source internally."""
    settings = context.scene.rigo_brace
    scan = settings.scan_object
    brace = bpy.data.objects.get(CORSET_NAME)
    perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
    build_perimeter = bpy.data.objects.get(BUILD_TRIM_PERIMETER_NAME)
    if mode == "BRACE":
        if brace is None:
            return False
        show_build_curve = brace.get("rigo_build_method") == "CURVE_EXACT"
        visible = {brace}
        if show_build_curve and build_perimeter is not None:
            visible.add(build_perimeter)
        visible.update(
            obj
            for obj in context.view_layer.objects
            if obj is not None and obj.name.startswith(_SLOT_PREFIX)
        )
        for obj in context.view_layer.objects:
            if obj is not None:
                obj.hide_set(obj not in visible)
        _select_only(context, brace)
    else:
        visible = {obj for obj in (scan, perimeter) if obj is not None}
        for obj in context.view_layer.objects:
            if obj is not None:
                obj.hide_set(obj not in visible)
        if perimeter is not None:
            # Respect body occlusion.  Showing the complete loop in front made
            # the back segment look as if it ran through the patient.
            perimeter.show_in_front = False
        _select_only(context, perimeter or scan)
    settings.design_view_mode = mode
    return True


class RIGO_OT_design_view(Operator):
    """Switch between trim editing and an uncluttered final-brace preview."""

    bl_idname = "rigo.design_view"
    bl_label = "Design View"
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(
        items=(
            ("TRIM", "Edit Trimlines", "Show body and perimeter"),
            ("BRACE", "Brace Preview", "Show only the generated brace"),
        ),
        default="TRIM",
    )

    def execute(self, context):
        if not _set_design_view(context, self.mode):
            self.report({"ERROR"}, "Generate the brace before opening Brace Preview")
            return {"CANCELLED"}
        return {"FINISHED"}


def _slot_collection(context):
    coll = bpy.data.collections.get(_SLOT_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(_SLOT_COLLECTION)
        context.scene.collection.children.link(coll)
    return coll


def _capsule_outline(width, height, arc_segments=_SLOT_ARC_SEGMENTS):
    """Return a counter-clockwise measured capsule outline in local XY."""
    width = max(float(width), 1.0e-6)
    height = max(float(height), 1.0e-6)
    segments = max(4, int(arc_segments))
    if abs(width - height) <= max(width, height) * 1.0e-6:
        radius = width * 0.5
        return [
            Vector(
                (
                    radius * math.cos(math.tau * index / (segments * 2)),
                    radius * math.sin(math.tau * index / (segments * 2)),
                )
            )
            for index in range(segments * 2)
        ]
    points = []
    if width >= height:
        radius = height * 0.5
        half_straight = (width - height) * 0.5
        for index in range(segments + 1):
            angle = -math.pi * 0.5 + math.pi * index / segments
            points.append(
                Vector(
                    (
                        half_straight + radius * math.cos(angle),
                        radius * math.sin(angle),
                    )
                )
            )
        for index in range(segments + 1):
            angle = math.pi * 0.5 + math.pi * index / segments
            points.append(
                Vector(
                    (
                        -half_straight + radius * math.cos(angle),
                        radius * math.sin(angle),
                    )
                )
            )
    else:
        radius = width * 0.5
        half_straight = (height - width) * 0.5
        for index in range(segments + 1):
            angle = math.pi * index / segments
            points.append(
                Vector(
                    (
                        radius * math.cos(angle),
                        half_straight + radius * math.sin(angle),
                    )
                )
            )
        for index in range(segments + 1):
            angle = math.pi + math.pi * index / segments
            points.append(
                Vector(
                    (
                        radius * math.cos(angle),
                        -half_straight + radius * math.sin(angle),
                    )
                )
            )
    return points


def _capsule_prism_mesh(name, width, height, depth):
    """Create a closed capsule prism whose penetration axis is local Z."""
    outline = _capsule_outline(width, height)
    count = len(outline)
    half_depth = max(float(depth), 1.0e-6) * 0.5
    vertices = [
        (point.x, point.y, -half_depth) for point in outline
    ] + [
        (point.x, point.y, half_depth) for point in outline
    ]
    faces = [tuple(reversed(range(count))), tuple(range(count, count * 2))]
    for index in range(count):
        following = (index + 1) % count
        faces.append((index, following, count + following, count + index))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    return mesh


def _capsule_boundary_distance(point, width, height):
    """Unsigned distance to a capsule boundary in its local XY plane."""
    if width >= height:
        radius = height * 0.5
        half_straight = (width - height) * 0.5
        distance = Vector((max(abs(point.x) - half_straight, 0.0), point.y)).length
    else:
        radius = width * 0.5
        half_straight = (height - width) * 0.5
        distance = Vector((point.x, max(abs(point.y) - half_straight, 0.0))).length
    return abs(distance - radius)


def _vertical_surface_rotation(normal):
    """Orient local Y vertically within the tangent plane and local Z outward."""
    normal = normal.normalized()
    vertical = Vector((0.0, 0.0, 1.0))
    vertical -= normal * vertical.dot(normal)
    if vertical.length_squared <= 1.0e-12:
        vertical = Vector((0.0, 1.0, 0.0))
        vertical -= normal * vertical.dot(normal)
    vertical.normalize()
    horizontal = vertical.cross(normal).normalized()
    return Matrix((horizontal, vertical, normal)).transposed().to_quaternion()


def _new_slot_marker(context, placement):
    """Build an accurate wire preview using the same frame as the cutter."""
    mesh = _capsule_prism_mesh(
        f"{placement.name} Preview",
        placement.width_mm * 0.001,
        placement.length_mm * 0.001,
        0.001,
    )
    marker = bpy.data.objects.new(placement.name, mesh)
    marker.location = placement.location
    marker.rotation_mode = "QUATERNION"
    if placement.normal is not None and placement.normal.length > 0.0:
        normal = placement.normal.normalized()
        marker.rotation_quaternion = _vertical_surface_rotation(normal)
        marker["rigo_normal"] = tuple(normal)
    marker.display_type = "WIRE"
    marker.show_in_front = True
    # Preserve these legacy property keys for markers stored in older files.
    marker["rigo_w"] = placement.length_mm
    marker["rigo_h"] = placement.width_mm
    marker["rigo_slot_axis"] = "VERTICAL"
    _slot_collection(context).objects.link(marker)
    return marker


def _mesh_volume(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        return abs(bm.calc_volume(signed=True))
    finally:
        bm.free()


def _surface_euler_characteristic(mesh):
    """Euler characteristic of face-bearing geometry, excluding loose debris."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        used_faces = list(bm.faces)
        used_edges = {edge for face in used_faces for edge in face.edges}
        used_vertices = {vertex for face in used_faces for vertex in face.verts}
        return len(used_vertices) - len(used_edges) + len(used_faces)
    finally:
        bm.free()


def _restore_slot_cut_mesh(corset, original_mesh):
    failed_mesh = corset.data
    corset.data = original_mesh
    if failed_mesh.users == 0:
        bpy.data.meshes.remove(failed_mesh)


def _slot_boundary_edges(corset, slots):
    """Locate only the sharp Boolean loops created by the capsule cutters."""
    bm = bmesh.new()
    bm.from_mesh(corset.data)
    transforms = []
    for slot in slots:
        transforms.append(
            (
                slot.matrix_world.inverted() @ corset.matrix_world,
                float(slot.get("rigo_h", 12.0)) * 0.001,
                float(slot.get("rigo_w", 40.0)) * 0.001,
            )
        )
    eligible = []
    tolerance = 0.0006
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            continue
        if edge.calc_face_angle(0.0) < math.radians(25.0):
            continue
        for transform, width, height in transforms:
            local_points = [transform @ vertex.co for vertex in edge.verts]
            if all(
                _capsule_boundary_distance(point, width, height) <= tolerance
                for point in local_points
            ):
                eligible.append(edge)
                break
    return bm, eligible


def _rounded_cut_edges(corset, markers, requested_radius_mm, thickness_mm):
    """Round Boolean entrance loops identified by measured surface markers."""
    effective_radius_mm = min(
        max(0.0, float(requested_radius_mm)), max(0.0, float(thickness_mm)) * 0.40
    )
    bm, eligible = _slot_boundary_edges(corset, markers)
    try:
        if eligible and effective_radius_mm > 0.0:
            bmesh.ops.bevel(
                bm,
                geom=eligible,
                offset=effective_radius_mm * 0.001,
                segments=_SLOT_BEVEL_SEGMENTS,
                profile=0.5,
                affect="EDGES",
                clamp_overlap=True,
                loop_slide=True,
                harden_normals=True,
            )
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.to_mesh(corset.data)
            corset.data.update()
    finally:
        bm.free()
    return len(eligible), effective_radius_mm


def _round_slot_edges(corset, slots, requested_radius_mm, thickness_mm):
    """Round slot rims and store the measured manufacturing result."""
    rounded_edges, effective_radius_mm = _rounded_cut_edges(
        corset, slots, requested_radius_mm, thickness_mm
    )
    corset["rigo_slot_fillet_requested_mm"] = float(requested_radius_mm)
    corset["rigo_slot_fillet_radius_mm"] = effective_radius_mm
    corset["rigo_slot_fillet_segments"] = _SLOT_BEVEL_SEGMENTS
    corset["rigo_slot_rounded_edges"] = rounded_edges
    return rounded_edges


def _remove_slot_slivers(corset, slots):
    """Remove only microscopic degeneracy inside the edited slot regions."""
    bm = bmesh.new()
    bm.from_mesh(corset.data)
    transforms = [
        (
            slot.matrix_world.inverted() @ corset.matrix_world,
            float(slot.get("rigo_h", 12.0)) * 0.0005 + 0.002,
            float(slot.get("rigo_w", 40.0)) * 0.0005 + 0.002,
        )
        for slot in slots
    ]
    def near_slot(vertex):
        return any(
            abs((transform @ vertex.co).x) <= half_width
            and abs((transform @ vertex.co).y) <= half_height
            and abs((transform @ vertex.co).z) <= 0.012
            for transform, half_width, half_height in transforms
        )

    local_vertices = [vertex for vertex in bm.verts if near_slot(vertex)]
    try:
        if local_vertices:
            bmesh.ops.remove_doubles(bm, verts=local_vertices, dist=5.0e-6)
            local_set = {vertex for vertex in bm.verts if near_slot(vertex)}
            local_edges = [
                edge for edge in bm.edges if all(vertex in local_set for vertex in edge.verts)
            ]
            if local_edges:
                bmesh.ops.dissolve_degenerate(bm, edges=local_edges, dist=5.0e-5)
            local_faces = [
                face for face in bm.faces if all(vertex in local_set for vertex in face.verts)
            ]
            non_triangles = [face for face in local_faces if len(face.verts) > 3]
            if non_triangles:
                bmesh.ops.triangulate(bm, faces=non_triangles)
            for _iteration in range(2):
                zero_edges = {
                    min(face.edges, key=lambda edge: edge.calc_length())
                    for face in bm.faces
                    if face.calc_area() <= 1.0e-12
                    and all(near_slot(vertex) for vertex in face.verts)
                }
                if not zero_edges:
                    break
                bmesh.ops.collapse(bm, edges=list(zero_edges))
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.to_mesh(corset.data)
            corset.data.update()
    finally:
        bm.free()


class RIGO_OT_generate_corset(Operator):
    """Build the corset shell from the corrected torso"""

    bl_idname = "rigo.generate_corset"
    bl_label = "Generate Corset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scan = _scan(context)
        if scan is None:
            self.report({"ERROR"}, "Import and prepare a scan first")
            return {"CANCELLED"}
        if scan.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # Issue #13 guard: a live Bend/Twist/Stretch would be copied into the
        # corset base with soon-dead drivers. The orthotist decides its fate.
        from .deform_ops import DEFORM_MODIFIER
        if scan.modifiers.get(DEFORM_MODIFIER) is not None:
            self.report(
                {"ERROR"},
                "Apply or Reset the active Bend/Twist/Stretch before generating",
            )
            return {"CANCELLED"}
        settings = context.scene.rigo_brace
        if settings.scan_object is None:
            settings.scan_object = scan
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        if perimeter is None:
            self.report(
                {"ERROR"},
                "Create and review Auto Trim Lines before generating the brace",
            )
            return {"CANCELLED"}
        if not _perimeter_belongs_to_scan(perimeter, scan):
            self.report(
                {"ERROR"},
                "Recreate Auto Trim Lines for the current Patient Scan",
            )
            return {"CANCELLED"}

        snapshot = _capture_generation_snapshot(settings)
        for name in (_CORSET_CANDIDATE_NAME, _CORSET_BASE_CANDIDATE_NAME):
            _remove_object_and_orphan_mesh(bpy.data.objects.get(name))

        # Build under private candidate names. The last valid brace and base
        # remain untouched until every wall-construction step succeeds.
        # Liner gap: push the surface outward along normals.
        # Shell smoothing: a splint is a smooth rigid envelope, not a skin
        # copy — relax the base strongly so it bridges folds and creases
        # (the un-smoothed shell reads as shrink-wrapped; DEC-0025).
        candidates = _GenerationCandidates()
        try:
            candidates.base = _prepare_candidate_base(context, scan, settings)
            candidates.brace = _build_corset(
                context, settings, top_profile=None, base=candidates.base
            )
            _commit_generation(context, snapshot, candidates, settings)
        except (
            OuterWallIntersectionError,
            TrimRimQualityError,
            TrimPerimeterWindingError,
        ) as error:
            _restore_failed_generation(context, snapshot, candidates)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        except Exception:
            _restore_failed_generation(context, snapshot, candidates)
            raise
        self.report(
            {"INFO"}, f"{settings.design_style.title()} corset generated"
        )
        return {"FINISHED"}


def _theta_of(px, py, ax, ay, fx, fy):
    """Angle of point (px,py) around axis (ax,ay): 0 at the ``front`` vector,
    increasing toward the patient's left. Matches trimline_ops' drape."""
    vx, vy = px - ax, py - ay
    return math.atan2(vx * (-fy) + vy * fx, vx * fx + vy * fy)


def _sample_curve_theta_z(obj, ax, ay, fx, fy, depsgraph):
    """Sorted (theta, z) world-space samples of an (edited) trim curve.
    Reads the EVALUATED curve — AUTO handles are (0,0,0) on the raw data."""
    from mathutils.geometry import interpolate_bezier

    ev = obj.evaluated_get(depsgraph)
    mw = ev.matrix_world
    samples = []
    for spline in ev.data.splines:
        bps = spline.bezier_points
        n = len(bps)
        for i in range(n):
            a, b = bps[i], bps[(i + 1) % n]
            for p in interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, 8)[:-1]:
                w = mw @ p
                samples.append((_theta_of(w.x, w.y, ax, ay, fx, fy), w.z))
    samples.sort(key=lambda s: s[0])
    return samples


def _trimline_curves(context):
    """(top_profile, bot_profile, ax, ay, fx, fy) from the auto trim lines,
    or None when they are not in the scene."""
    top = bpy.data.objects.get("Rigo Trim Top")
    bot = bpy.data.objects.get("Rigo Trim Bottom")
    if top is None or bot is None:
        return None
    axis = top.get("rigo_trim_axis")
    front = top.get("rigo_trim_front")
    if axis is None or front is None:
        return None
    ax, ay = float(axis[0]), float(axis[1])
    fx, fy = float(front[0]), float(front[1])
    deps = context.evaluated_depsgraph_get()
    top_prof = _sample_curve_theta_z(top, ax, ay, fx, fy, deps)
    bot_prof = _sample_curve_theta_z(bot, ax, ay, fx, fy, deps)
    if len(top_prof) < 8 or len(bot_prof) < 8:
        return None
    return top_prof, bot_prof, ax, ay, fx, fy


def _trim_perimeter_uv(context):
    """Dense evaluated perimeter in cylindrical (angle 0..2pi, world Z)."""
    perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
    if perimeter is None:
        return None
    axis = perimeter.get("rigo_trim_axis")
    front = perimeter.get("rigo_trim_front")
    if axis is None or front is None:
        return None
    ax, ay = float(axis[0]), float(axis[1])
    fx, fy = float(front[0]), float(front[1])
    depsgraph = context.evaluated_depsgraph_get()
    # Sample the authored Bezier once and project every dense sample below.
    # Reading the Shrinkwrap-evaluated control data and then projecting again
    # made a no-op Fit move the generated boundary by up to 0.7 mm on facets.
    matrix = perimeter.matrix_world
    scan = _scan(context)
    scan_bvh = BVHTree.FromObject(scan, depsgraph) if scan is not None else None
    scan_inverse = scan.matrix_world.inverted() if scan is not None else None
    scan_normal_matrix = (
        scan.matrix_world.inverted().transposed().to_3x3()
        if scan is not None
        else None
    )
    scan_inverse_3 = scan_inverse.to_3x3() if scan_inverse is not None else None
    scan_reach = 0.0
    if scan is not None:
        scan_corners = [
            scan.matrix_world @ Vector(corner) for corner in scan.bound_box
        ]
        scan_reach = max(
            max(corner.x for corner in scan_corners)
            - min(corner.x for corner in scan_corners),
            max(corner.y for corner in scan_corners)
            - min(corner.y for corner in scan_corners),
        )
    polygon = []
    from mathutils.geometry import interpolate_bezier

    for spline in perimeter.data.splines:
        points = spline.bezier_points
        segment_intervals = max(8, 1344 // max(1, len(points)))
        for index, first in enumerate(points):
            second = points[(index + 1) % len(points)]
            samples = interpolate_bezier(
                first.co,
                first.handle_right,
                second.handle_left,
                second.co,
                segment_intervals + 1,
            )
            for sample in samples[:-1]:
                world = matrix @ sample
                # The Shrinkwrap modifier deforms the evaluated tessellation,
                # not these manually interpolated Bezier handles.  Re-project
                # every generator sample explicitly so no segment can cross a
                # concavity or enter the corrected body between controls.
                if scan_bvh is not None:
                    sample_angle = _theta_of(
                        world.x, world.y, ax, ay, fx, fy
                    )
                    radial = Vector(
                        (
                            fx * math.cos(sample_angle)
                            - fy * math.sin(sample_angle),
                            fx * math.sin(sample_angle)
                            + fy * math.cos(sample_angle),
                            0.0,
                        )
                    )
                    origin_world = Vector((ax, ay, world.z)) + radial * scan_reach
                    origin_local = scan_inverse @ origin_world
                    direction_local = (
                        scan_inverse_3 @ (-radial)
                    ).normalized()
                    far_local = scan_inverse @ (
                        origin_world - radial * (scan_reach * 2.0)
                    )
                    hit = scan_bvh.ray_cast(
                        origin_local,
                        direction_local,
                        (far_local - origin_local).length,
                    )
                    if hit[0] is None:
                        hit = scan_bvh.find_nearest(scan_inverse @ world)
                    if hit[0] is not None:
                        normal_world = (scan_normal_matrix @ hit[1]).normalized()
                        world = (
                            scan.matrix_world @ hit[0]
                            + normal_world * 0.0015
                        )
                angle = _theta_of(world.x, world.y, ax, ay, fx, fy)
                polygon.append((angle % (2.0 * math.pi), world.z))
    unwrapped, _theta_min, _theta_max = _unwrap_uv_polygon(polygon)
    return list(unwrapped), ax, ay, fx, fy


def _inside_polygon(point, polygon):
    """Odd-even containment in the perimeter's cylindrical parameter plane."""
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x0, y0 = previous
        x1, y1 = current
        crosses = (y0 > y) != (y1 > y)
        if crosses and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
        previous = current
    return inside


def _unwrap_uv_polygon(polygon):
    """Continuously unwrap a densely sampled cylindrical (theta, z) polygon.

    Per-sample ``theta % tau`` puts a boundary that crosses the front seam
    (theta = 0) on both ends of the parameter domain, and the jump segments
    corrupt every planar odd-even test (verified: 52% of the torso band
    misclassified for a painted area covering the front). Samples are dense,
    so any |delta theta| > pi between neighbours is a seam jump, not real
    geometry. Returns (unwrapped, theta_min, theta_max).
    """
    tau = 2.0 * math.pi
    unwrapped = []
    offset = 0.0
    previous = None
    for angle, height in polygon:
        if previous is not None:
            while angle + offset - previous > math.pi:
                offset -= tau
            while angle + offset - previous < -math.pi:
                offset += tau
        previous = angle + offset
        unwrapped.append((previous, height))
    closing = polygon[0][0] - polygon[-1][0]
    closing = ((closing + math.pi) % tau) - math.pi
    winding = round((unwrapped[-1][0] + closing - unwrapped[0][0]) / tau)
    if winding:
        raise TrimPerimeterWindingError()
    angles = [angle for angle, _height in unwrapped]
    return tuple(unwrapped), min(angles), max(angles)


def _inside_unwrapped_polygon(point, unwrapped, theta_min, theta_max):
    """Seam-correct containment: test every 2*pi replica of the query angle
    that can fall inside the unwrapped polygon's angular span. An embedded
    boundary loop contains at most one replica of any cylinder point."""
    angle, height = point
    tau = 2.0 * math.pi
    lowest = math.ceil((theta_min - angle) / tau)
    highest = math.floor((theta_max - angle) / tau)
    return any(
        _inside_polygon((angle + step * tau, height), unwrapped)
        for step in range(lowest, highest + 1)
    )


def _segment_hit(first, second, edge_start, edge_end):
    """Parameter t where first->second intersects one perimeter segment."""
    ax, ay = first
    bx, by = second
    cx, cy = edge_start
    dx, dy = edge_end
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1.0e-12:
        return None
    qx, qy = cx - ax, cy - ay
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    if -1.0e-9 <= t <= 1.0 + 1.0e-9 and -1.0e-9 <= u <= 1.0 + 1.0e-9:
        return max(0.0, min(1.0, t))
    return None


def _first_perimeter_hit(first, second, polygon):
    hits = []
    previous = polygon[-1]
    for current in polygon:
        hit = _segment_hit(first, second, previous, current)
        if hit is not None:
            hits.append(hit)
        previous = current
    return min(hits) if hits else None


def _clip_triangle_cylindrical(vertices, polygon, theta_min, theta_max):
    """Clip one triangle whose uv angles are mutually continuous against the
    unwrapped perimeter, trying every 2*pi replica that can reach it."""
    tau = 2.0 * math.pi
    triangle_low = min(vertex[1][0] for vertex in vertices)
    triangle_high = max(vertex[1][0] for vertex in vertices)
    lowest = math.ceil((theta_min - triangle_high) / tau)
    highest = math.floor((theta_max - triangle_low) / tau)
    for step in range(lowest, highest + 1):
        shifted = [
            (vertex[0], (vertex[1][0] + step * tau, vertex[1][1]))
            for vertex in vertices
        ]
        if any(_inside_polygon(vertex[1], polygon) for vertex in shifted):
            return _clip_triangle(shifted, polygon)
    return []


def _clip_triangle(vertices, polygon):
    """Clip one small surface triangle against the simple perimeter polygon."""
    inside = [_inside_polygon(vertex[1], polygon) for vertex in vertices]
    if all(inside):
        return vertices
    if not any(inside):
        return []
    clipped = []
    for index, current in enumerate(vertices):
        following = vertices[(index + 1) % 3]
        current_inside = inside[index]
        following_inside = inside[(index + 1) % 3]
        if current_inside:
            clipped.append(current)
        if current_inside != following_inside:
            hit = _first_perimeter_hit(current[1], following[1], polygon)
            if hit is None:
                continue
            coordinate = current[0].lerp(following[0], hit)
            uv = (
                current[1][0] + (following[1][0] - current[1][0]) * hit,
                current[1][1] + (following[1][1] - current[1][1]) * hit,
            )
            clipped.append((coordinate, uv))
    return clipped


def _source_surface(mesh):
    mesh.calc_loop_triangles()
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    return _SourceSurface(
        coordinates=coordinates,
        normals=[vertex.normal.copy() for vertex in mesh.vertices],
        triangles=triangles,
        bvh=BVHTree.FromPolygons(
            coordinates, triangles, all_triangles=True, epsilon=0.0
        ),
    )


def _barycentric_weights(first, second, third, point):
    first_edge = second - first
    second_edge = third - first
    relative = point - first
    first_dot = first_edge.dot(first_edge)
    cross_dot = first_edge.dot(second_edge)
    second_dot = second_edge.dot(second_edge)
    first_relative = relative.dot(first_edge)
    second_relative = relative.dot(second_edge)
    denominator = first_dot * second_dot - cross_dot * cross_dot
    second_weight = (second_dot * first_relative - cross_dot * second_relative) / denominator
    third_weight = (first_dot * second_relative - cross_dot * first_relative) / denominator
    return 1.0 - second_weight - third_weight, second_weight, third_weight


def _surface_normal_at(source_surface, coordinate):
    nearest_coordinate, _normal, triangle_index, _distance = (
        source_surface.bvh.find_nearest(coordinate)
    )
    triangle = source_surface.triangles[triangle_index]
    triangle_coordinates = [source_surface.coordinates[index] for index in triangle]
    weights = _barycentric_weights(*triangle_coordinates, nearest_coordinate)
    normal = sum(
        (
            source_surface.normals[index] * weight
            for index, weight in zip(triangle, weights)
        ),
        Vector(),
    )
    return normal.normalized()


def _store_full_surface_normals(mesh, source_surface):
    normal_attribute = mesh.attributes.new(
        name="rigo_full_surface_normal", type="FLOAT_VECTOR", domain="POINT"
    )
    for vertex, normal_entry in zip(mesh.vertices, normal_attribute.data):
        normal_entry.vector = _surface_normal_at(source_surface, vertex.co)


def _boundary_neighbours(bm):
    """Boundary vertex -> its boundary neighbours for every open loop."""
    neighbours = {}
    for edge in bm.edges:
        if not edge.is_boundary:
            continue
        first, second = edge.verts
        neighbours.setdefault(first, []).append(second)
        neighbours.setdefault(second, []).append(first)
    return neighbours


def _project_to_source(source_surface, coordinate):
    hit = source_surface.bvh.find_nearest(coordinate)
    return hit[0].copy() if hit[0] is not None else coordinate.copy()


def _constrain_to_source_band(source_surface, coordinate):
    """Keep a faired rim just outside, and within 0.2 mm of, the body.

    Re-projecting every fairing step exactly onto a faceted scan copies its
    triangle noise into the trim silhouette.  A narrow one-sided tolerance
    band preserves body curvature and prevents penetration while allowing the
    boundary curve to bridge sub-millimetre scan facets smoothly.
    """
    hit = source_surface.bvh.find_nearest(coordinate)
    if hit[0] is None:
        return coordinate.copy()
    surface_coordinate = hit[0]
    normal = _surface_normal_at(source_surface, surface_coordinate)
    signed_gap = (coordinate - surface_coordinate).dot(normal)
    clamped_gap = min(
        _TRIM_BOUNDARY_MAX_SURFACE_GAP_M,
        max(_TRIM_BOUNDARY_CLEARANCE_M, signed_gap),
    )
    return surface_coordinate + normal * clamped_gap


def _split_long_boundary_edges(bm):
    split_count = 0
    for _pass in range(3):
        long_edges = [
            edge
            for edge in bm.edges
            if edge.is_boundary
            and edge.calc_length() > _TRIM_BOUNDARY_TARGET_M * 1.35
        ]
        if not long_edges:
            break
        split_count += len(long_edges)
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1, use_grid_fill=False)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
    return split_count


def _boundary_band_faces(bm):
    band = {
        face
        for edge in bm.edges
        if edge.is_boundary
        for face in edge.link_faces
    }
    frontier = set(band)
    for _ring in range(_TRIM_BAND_RINGS - 1):
        neighbours = {
            linked_face
            for face in frontier
            for edge in face.edges
            for linked_face in edge.link_faces
            if linked_face not in band
        }
        if not neighbours:
            break
        band.update(neighbours)
        frontier = neighbours
    return band


def _refine_boundary_band(bm, source_surface):
    split_count = 0
    for _pass in range(2):
        band = _boundary_band_faces(bm)
        long_edges = {
            edge
            for face in band
            for edge in face.edges
            if edge.calc_length() > _TRIM_BAND_TARGET_M * 1.5
        }
        if not long_edges:
            break
        split_count += len(long_edges)
        bmesh.ops.subdivide_edges(
            bm, edges=list(long_edges), cuts=1, use_grid_fill=False
        )
        band = _boundary_band_faces(bm)
        for vertex in {vertex for face in band for vertex in face.verts}:
            vertex.co = _project_to_source(source_surface, vertex.co)
        bmesh.ops.triangulate(bm, faces=list(band))
        bmesh.ops.beautify_fill(bm, faces=list(band), method="AREA")
    return split_count


def _collapse_short_boundary_edges(bm):
    collapsed = 0
    for _pass in range(3):
        boundary = [edge for edge in bm.edges if edge.is_boundary]
        if len(boundary) <= 20:
            break
        occupied = set()
        candidates = []
        for edge in sorted(boundary, key=lambda candidate: candidate.calc_length()):
            if edge.calc_length() >= _TRIM_BOUNDARY_TARGET_M * 0.55:
                break
            if any(vertex in occupied for vertex in edge.verts):
                continue
            candidates.append(edge)
            occupied.update(edge.verts)
        if not candidates:
            break
        collapsed += len(candidates)
        bmesh.ops.collapse(bm, edges=candidates)
    return collapsed


def _boundary_relax_updates(bm, source_surface, coefficient):
    updates = {}
    for vertex, adjacent in _boundary_neighbours(bm).items():
        if len(adjacent) != 2:
            continue
        target = (adjacent[0].co + adjacent[1].co) * 0.5
        normal = _surface_normal_at(source_surface, vertex.co)
        delta = (target - vertex.co) * coefficient
        # Fair tangentially.  Normal motion would reproduce the underlying
        # scan facets as teeth or let a control point fall through the body.
        delta -= normal * delta.dot(normal)
        if delta.length > _TRIM_BOUNDARY_MAX_STEP_M:
            delta.length = _TRIM_BOUNDARY_MAX_STEP_M
        updates[vertex] = _constrain_to_source_band(
            source_surface, vertex.co + delta
        )
    return updates


def _apply_boundary_updates(updates):
    movement = 0.0
    smoothed_vertices = set()
    for vertex, coordinate in updates.items():
        movement += (coordinate - vertex.co).length
        vertex.co = coordinate
        smoothed_vertices.add(vertex)
    return movement, smoothed_vertices


def _boundary_spacing_stats(bm):
    lengths = [
        edge.calc_length() * 1000.0 for edge in bm.edges if edge.is_boundary
    ]
    if not lengths:
        return 0.0, 0.0, 0.0, 0.0
    mean = sum(lengths) / len(lengths)
    variance = sum((length - mean) ** 2 for length in lengths) / len(lengths)
    return mean, min(lengths), max(lengths), math.sqrt(variance)


def _regularize_cut_boundary(bm, source_surface):
    """Remesh and relax the cut loop while constraining it to the source wall.

    This is the geometric equivalent of Meshmixer's boundary-remesh followed
    by Smooth Boundary: long rim edges are split first, then only the open loop
    is Laplacian-relaxed and re-projected after every pass.  Interior body
    vertices are untouched, so the orthotist's corrected mold is preserved.
    """
    band_split_edges = _refine_boundary_band(bm, source_surface)
    split_edges = _split_long_boundary_edges(bm)
    collapsed_edges = _collapse_short_boundary_edges(bm)
    smoothed_vertices = set()
    total_movement = 0.0
    for _cycle in range(_TRIM_BOUNDARY_SMOOTH_CYCLES):
        for coefficient in (0.50, -0.53):
            movement, moved_vertices = _apply_boundary_updates(
                _boundary_relax_updates(bm, source_surface, coefficient)
            )
            total_movement += movement
            smoothed_vertices.update(moved_vertices)

    split_edges += _split_long_boundary_edges(bm)
    collapsed_edges += _collapse_short_boundary_edges(bm)

    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    band = _boundary_band_faces(bm)
    bmesh.ops.beautify_fill(bm, faces=list(band), method="AREA")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    mean_spacing, min_spacing, max_spacing, spacing_deviation = (
        _boundary_spacing_stats(bm)
    )
    return {
        "band_split_edges": band_split_edges,
        "split_edges": split_edges,
        "collapsed_edges": collapsed_edges,
        "vertices": len(smoothed_vertices),
        "mean_spacing_mm": mean_spacing,
        "min_spacing_mm": min_spacing,
        "max_spacing_mm": max_spacing,
        "spacing_deviation_mm": spacing_deviation,
        "movement_mm": total_movement * 1000.0,
    }


def _clip_to_perimeter(corset, perimeter_data):
    """Insert the evaluated perimeter into the mesh instead of deleting faces."""
    polygon, ax, ay, fx, fy = perimeter_data
    source = corset.data
    source_surface = _source_surface(source)
    matrix = corset.matrix_world
    vertices = []
    faces = []
    vertex_lookup = {}

    def add_vertex(coordinate):
        key = tuple(round(component, 9) for component in coordinate)
        existing = vertex_lookup.get(key)
        if existing is not None:
            return existing
        vertex_lookup[key] = len(vertices)
        vertices.append(tuple(coordinate))
        return len(vertices) - 1

    tau = 2.0 * math.pi
    theta_min = min(angle for angle, _height in polygon)
    theta_max = max(angle for angle, _height in polygon)
    for triangle in source.loop_triangles:
        triangle_data = []
        anchor = None
        for vertex_index in triangle.vertices:
            local = source.vertices[vertex_index].co.copy()
            world = matrix @ local
            angle = _theta_of(world.x, world.y, ax, ay, fx, fy) % tau
            if anchor is None:
                anchor = angle
            else:
                # Keep the triangle's three angles mutually continuous so a
                # triangle straddling the front seam stays one small triangle
                # in the parameter plane instead of spanning the whole domain.
                angle = anchor + ((angle - anchor + math.pi) % tau) - math.pi
            triangle_data.append((local, (angle, world.z)))
        clipped = _clip_triangle_cylindrical(
            triangle_data, polygon, theta_min, theta_max
        )
        if len(clipped) < 3:
            continue
        indices = [add_vertex(vertex[0]) for vertex in clipped]
        for index in range(1, len(indices) - 1):
            faces.append((indices[0], indices[index], indices[index + 1]))

    clipped_mesh = bpy.data.meshes.new(f"{corset.name} Trimmed")
    clipped_mesh.from_pydata(vertices, [], faces)
    clipped_mesh.update()
    cleanup = bmesh.new()
    cleanup.from_mesh(clipped_mesh)
    bmesh.ops.remove_doubles(cleanup, verts=list(cleanup.verts), dist=5.0e-5)
    bmesh.ops.dissolve_degenerate(cleanup, edges=list(cleanup.edges), dist=3.0e-4)
    bmesh.ops.triangulate(cleanup, faces=list(cleanup.faces))
    bmesh.ops.beautify_fill(cleanup, faces=list(cleanup.faces), method="AREA")
    _collapse_skinny_triangles(cleanup)
    boundary_stats = _regularize_cut_boundary(cleanup, source_surface)
    cleanup.to_mesh(clipped_mesh)
    cleanup.free()
    clipped_mesh.update()
    _store_full_surface_normals(clipped_mesh, source_surface)
    old_mesh = corset.data
    corset.data = clipped_mesh
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    for group in list(corset.vertex_groups):
        corset.vertex_groups.remove(group)
    corset["rigo_trim_boundary_vertices"] = boundary_stats["vertices"]
    corset["rigo_trim_boundary_split_edges"] = boundary_stats["split_edges"]
    corset["rigo_trim_band_split_edges"] = boundary_stats["band_split_edges"]
    corset["rigo_trim_boundary_collapsed_edges"] = boundary_stats[
        "collapsed_edges"
    ]
    corset["rigo_trim_boundary_mean_spacing_mm"] = boundary_stats[
        "mean_spacing_mm"
    ]
    corset["rigo_trim_boundary_max_spacing_mm"] = boundary_stats[
        "max_spacing_mm"
    ]
    corset["rigo_trim_boundary_min_spacing_mm"] = boundary_stats[
        "min_spacing_mm"
    ]
    corset["rigo_trim_boundary_spacing_deviation_mm"] = boundary_stats[
        "spacing_deviation_mm"
    ]


def _boundary_edges(triangles):
    edge_uses = {}
    for triangle in triangles:
        for first, second in (
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ):
            key = tuple(sorted((first, second)))
            edge_uses.setdefault(key, []).append((first, second))
    return [uses[0] for uses in edge_uses.values() if len(uses) == 1]


def _vertex_adjacency(vertex_count, triangles):
    adjacency = [set() for _ in range(vertex_count)]
    for first, second, third in triangles:
        for start, end in (
            (first, second),
            (second, third),
            (third, first),
        ):
            adjacency[start].add(end)
            adjacency[end].add(start)
    return adjacency


def _outer_coordinates(inner, directions, thickness_m):
    return [
        coordinate + direction * thickness_m
        for coordinate, direction in zip(inner, directions)
    ]


def _maximum_direction_change_deg(original, directions):
    return max(
        (
            math.degrees(original_direction.angle(direction))
            for original_direction, direction in zip(original, directions)
        ),
        default=0.0,
    )


def _limit_direction_change(original, candidate):
    angle = original.angle(candidate)
    if angle <= _OUTER_REPAIR_MAX_ANGLE_RAD:
        return candidate
    try:
        return original.slerp(
            candidate, _OUTER_REPAIR_MAX_ANGLE_RAD / angle
        ).normalized()
    except ValueError:
        return original.copy()


def _repair_outer_offset_directions(inner, original, triangles, thickness_m):
    """Untangle only colliding outer directions while retaining their length."""
    directions = [direction.copy() for direction in original]
    adjacency = _vertex_adjacency(len(inner), triangles)
    pairs = triangle_intersection_pairs(
        _outer_coordinates(inner, directions, thickness_m), triangles
    )
    initial_pairs = len(pairs)
    modified_vertices = set()
    iterations = 0
    while pairs and iterations < _OUTER_REPAIR_MAX_ITERATIONS:
        targets = {
            vertex_index
            for first_triangle, second_triangle in pairs
            for triangle_index in (first_triangle, second_triangle)
            for vertex_index in triangles[triangle_index]
        }
        modified_vertices.update(targets)
        previous = [direction.copy() for direction in directions]
        for vertex_index in targets:
            average = sum(
                (previous[index] for index in adjacency[vertex_index]),
                previous[vertex_index].copy(),
            )
            if average.length_squared <= 1.0e-20:
                continue
            candidate = previous[vertex_index].lerp(
                average.normalized(), _OUTER_REPAIR_BLEND
            )
            if candidate.length_squared <= 1.0e-20:
                continue
            directions[vertex_index] = _limit_direction_change(
                original[vertex_index], candidate.normalized()
            )
        iterations += 1
        pairs = triangle_intersection_pairs(
            _outer_coordinates(inner, directions, thickness_m), triangles
        )

    maximum_angle = _maximum_direction_change_deg(original, directions)
    stats = _OuterRepairStats(
        initial_pairs=initial_pairs,
        remaining_pairs=len(pairs),
        iterations=iterations,
        modified_vertices=len(modified_vertices),
        max_direction_change_deg=maximum_angle,
    )
    if pairs:
        raise OuterWallIntersectionError(
            thickness_m * 1000.0, len(pairs), maximum_angle
        )
    return directions, stats


def _paired_coordinates(source, triangles, thickness_m):
    normal_attribute = source.attributes["rigo_full_surface_normal"]
    inner = [vertex.co.copy() for vertex in source.vertices]
    normals = [
        Vector(normal_attribute.data[index].vector).normalized()
        for index in range(len(inner))
    ]
    repaired, stats = _repair_outer_offset_directions(
        inner, normals, triangles, thickness_m
    )
    return inner + _outer_coordinates(inner, repaired, thickness_m), stats


def _rim_outward_directions(coordinates, triangles, boundary, vertex_count):
    """Find the tangent-plane direction outside the retained shell surface."""
    inner = coordinates[:vertex_count]
    outer = coordinates[vertex_count : vertex_count * 2]
    adjacency = _vertex_adjacency(vertex_count, triangles)
    boundary_neighbours = {}
    for first, second in boundary:
        boundary_neighbours.setdefault(first, set()).add(second)
        boundary_neighbours.setdefault(second, set()).add(first)
    directions = {}
    for index, neighbours in boundary_neighbours.items():
        if len(neighbours) != 2:
            continue
        previous, following = neighbours
        normal = (outer[index] - inner[index]).normalized()
        tangent = inner[following] - inner[previous]
        tangent -= normal * tangent.dot(normal)
        tangent.normalize()
        outward = tangent.cross(normal).normalized()
        interior = sum(
            (inner[neighbour] - inner[index] for neighbour in adjacency[index]),
            Vector(),
        )
        interior -= normal * interior.dot(normal)
        interior -= tangent * interior.dot(tangent)
        if outward.dot(interior) > 0.0:
            outward.negate()
        directions[index] = outward
    return directions


def _rounded_paired_geometry(
    coordinates, triangles, boundary, vertex_count, radius_m, segments
):
    """Join the paired walls with a regular, radius-controlled rounded strip."""
    segments = max(2, int(segments))
    untrimmed = [coordinate.copy() for coordinate in coordinates]
    directions = _rim_outward_directions(
        untrimmed, triangles, boundary, vertex_count
    )
    boundary_vertices = {index for edge in boundary for index in edge}
    boundary_neighbours = {}
    for first, second in boundary:
        boundary_neighbours.setdefault(first, set()).add(second)
        boundary_neighbours.setdefault(second, set()).add(first)
    local_radii = {index: radius_m for index in boundary_vertices}
    profile_indices = {}
    profile_sources = {}
    for index in boundary_vertices:
        profile_indices[(index, 0)] = index
        profile_indices[(index, segments)] = index + vertex_count
        for step in range(1, segments):
            profile_indices[(index, step)] = len(coordinates)
            profile_sources[len(coordinates)] = index
            coordinates.append(Vector())

    def update_profile(index):
        """Cut back the sharp wall first, then add the round nose."""
        radius = local_radii[index]
        inward = -directions[index] * radius
        inner_index = profile_indices[(index, 0)]
        outer_index = profile_indices[(index, segments)]
        coordinates[inner_index] = untrimmed[index] + inward
        coordinates[outer_index] = untrimmed[index + vertex_count] + inward
        for step in range(1, segments):
            fraction = step / segments
            centre = coordinates[inner_index].lerp(
                coordinates[outer_index], fraction
            )
            bulge = radius * math.sin(math.pi * fraction)
            coordinates[profile_indices[(index, step)]] = (
                centre + directions[index] * bulge
            )

    for index in boundary_vertices:
        update_profile(index)

    faces = [tuple(reversed(triangle)) for triangle in triangles]
    faces.extend(
        tuple(index + vertex_count for index in triangle) for triangle in triangles
    )
    for first, second in boundary:
        for step in range(segments):
            lower_first = profile_indices[(first, step)]
            lower_second = profile_indices[(second, step)]
            upper_second = profile_indices[(second, step + 1)]
            upper_first = profile_indices[(first, step + 1)]
            faces.extend(
                (
                    (lower_first, lower_second, upper_second),
                    (lower_first, upper_second, upper_first),
                )
            )

    for _iteration in range(16):
        intersections = triangle_intersection_pairs(coordinates, faces)
        if not intersections:
            break
        affected = set()
        for pair in intersections:
            for face_index in pair:
                for vertex in faces[face_index]:
                    if vertex in profile_sources:
                        affected.add(profile_sources[vertex])
                    elif vertex in boundary_vertices:
                        affected.add(vertex)
                    elif (
                        vertex_count <= vertex < vertex_count * 2
                        and vertex - vertex_count in boundary_vertices
                    ):
                        affected.add(vertex - vertex_count)
        if not affected:
            break
        neighbours = {
            neighbour
            for index in affected
            for neighbour in boundary_neighbours.get(index, ())
        }
        for index in affected:
            local_radii[index] *= 0.55
        for index in neighbours - affected:
            local_radii[index] *= 0.80
        for index in affected | neighbours:
            update_profile(index)
    return coordinates, faces, local_radii


def _replace_corset_mesh(corset, coordinates, faces):
    shell_mesh = bpy.data.meshes.new(f"{corset.name} Paired Shell")
    shell_mesh.from_pydata([tuple(coordinate) for coordinate in coordinates], [], faces)
    shell_mesh.update()
    for polygon in shell_mesh.polygons:
        polygon.use_smooth = True
    old_mesh = corset.data
    corset.data = shell_mesh
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def _mark_rim_boundary(corset, boundary, vertex_count):
    old_group = corset.vertex_groups.get(_RIM_BOUNDARY_GROUP)
    if old_group is not None:
        corset.vertex_groups.remove(old_group)
    rim_group = corset.vertex_groups.new(name=_RIM_BOUNDARY_GROUP)
    for vertex_index in {index for edge in boundary for index in edge}:
        rim_group.add((vertex_index, vertex_index + vertex_count), 1.0, "REPLACE")


def _transition_vertex_distances(seeds, width_m):
    distances = {vertex: 0.0 for vertex in seeds}
    pending = [(0.0, id(vertex), vertex) for vertex in seeds]
    heapq.heapify(pending)
    while pending:
        distance, _identity, vertex = heapq.heappop(pending)
        if distance != distances.get(vertex) or distance > width_m:
            continue
        for edge in vertex.link_edges:
            neighbour = edge.other_vert(vertex)
            candidate = distance + edge.calc_length()
            if candidate > width_m or candidate >= distances.get(neighbour, math.inf):
                continue
            distances[neighbour] = candidate
            heapq.heappush(pending, (candidate, id(neighbour), neighbour))
    return distances


def _transition_target(distance, width_m):
    fraction = min(1.0, distance / max(width_m, 1.0e-9))
    return _TRIM_BAND_TARGET_M + fraction * (
        _TRIM_TRANSITION_INNER_TARGET_M - _TRIM_BAND_TARGET_M
    )


def _transition_seed_vertices(bm, deform_layer, group_index):
    if deform_layer is None:
        return set()
    return {
        vertex
        for vertex in bm.verts
        if vertex[deform_layer].get(group_index, 0.0) > 0.5
    }


def _transition_faces(bm, seeds, width_m):
    distances = _transition_vertex_distances(seeds, width_m)
    return [
        face
        for face in bm.faces
        if any(vertex in distances for vertex in face.verts)
        and max(edge.calc_length() for edge in face.edges)
        > _transition_target(
            min(distances.get(vertex, width_m) for vertex in face.verts),
            width_m,
        )
        * 1.5
    ]


def _write_refined_transition_mesh(bm, mesh):
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1.0e-9)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1.0e-9)
    non_triangles = [face for face in bm.faces if len(face.verts) > 3]
    if non_triangles:
        bmesh.ops.triangulate(bm, faces=non_triangles)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    mesh.update()


def _refine_finished_trim_transition(corset, width_m):
    mesh = corset.data
    rim_group = corset.vertex_groups.get(_RIM_BOUNDARY_GROUP)
    if rim_group is None:
        return 0
    bm = bmesh.new()
    bm.from_mesh(mesh)
    deform_layer = bm.verts.layers.deform.active
    refined_face_count = 0
    for _pass in range(2):
        seeds = _transition_seed_vertices(bm, deform_layer, rim_group.index)
        faces = _transition_faces(bm, seeds, width_m)
        if not faces:
            break
        refined_face_count += len(faces)
        bmesh.ops.poke(
            bm,
            faces=faces,
            offset=0.0,
            center_mode="MEAN_WEIGHTED",
            use_relative_offset=False,
        )
    _write_refined_transition_mesh(bm, mesh)
    bm.free()
    return refined_face_count


def _build_paired_shell(corset, thickness_m, radius_mm, segments):
    """Offset with uncut-torso normals so the rim cannot fold through the wall."""
    source = corset.data
    source.calc_loop_triangles()
    vertex_count = len(source.vertices)
    triangles = [tuple(triangle.vertices) for triangle in source.loop_triangles]
    boundary = _boundary_edges(triangles)
    coordinates, repair = _paired_coordinates(source, triangles, thickness_m)
    separations = [
        (coordinates[index + vertex_count] - coordinates[index]).length * 1000.0
        for index in range(vertex_count)
    ]
    corset["rigo_pair_min_thickness_mm"] = min(separations, default=0.0)
    corset["rigo_pair_max_thickness_mm"] = max(separations, default=0.0)
    corset["rigo_paired_source_vertices"] = vertex_count
    corset["rigo_outer_collision_initial"] = repair.initial_pairs
    corset["rigo_outer_collision_remaining"] = repair.remaining_pairs
    corset["rigo_outer_collision_iterations"] = repair.iterations
    corset["rigo_outer_collision_vertices"] = repair.modified_vertices
    corset["rigo_outer_collision_max_angle_deg"] = (
        repair.max_direction_change_deg
    )
    effective_radius_mm = min(float(radius_mm), thickness_m * 1000.0 * 0.45)
    coordinates, faces, local_radii = _rounded_paired_geometry(
        coordinates,
        triangles,
        boundary,
        vertex_count,
        effective_radius_mm * 0.001,
        segments,
    )
    _replace_corset_mesh(corset, coordinates, faces)
    _mark_rim_boundary(corset, boundary, vertex_count)
    corset["rigo_trim_fillet_requested_mm"] = float(radius_mm)
    corset["rigo_trim_fillet_radius_mm"] = effective_radius_mm
    corset["rigo_trim_fillet_min_radius_mm"] = (
        min(local_radii.values(), default=0.0) * 1000.0
    )
    corset["rigo_trim_fillet_mean_radius_mm"] = (
        sum(local_radii.values()) / max(1, len(local_radii)) * 1000.0
    )
    corset["rigo_trim_fillet_segments"] = max(2, int(segments))
    corset["rigo_rounded_rim_edges"] = len(boundary)
    return len(boundary)


def _clean_open_trim_surface(corset):
    """Remove microscopic branch points before building the structured rim."""
    mesh = corset.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=5.0e-6)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1.0e-5)
    _repair_branched_trim_boundary(bm)
    non_triangles = [face for face in bm.faces if len(face.verts) > 3]
    if non_triangles:
        bmesh.ops.triangulate(bm, faces=non_triangles)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def _branched_trim_vertices(bm):
    branched_vertices = []
    for vertex in bm.verts:
        boundary_degree = sum(edge.is_boundary for edge in vertex.link_edges)
        if boundary_degree and boundary_degree != 2:
            branched_vertices.append(vertex)
    return branched_vertices


def _repair_branched_trim_boundary(bm):
    """Remove submillimetre pinch vertices created by perimeter clipping."""
    for _attempt in range(8):
        branched_vertices = _branched_trim_vertices(bm)
        if not branched_vertices:
            return
        if any(
            max(
                edge.calc_length()
                for edge in vertex.link_edges
                if edge.is_boundary
            )
            > _TRIM_BRANCH_REPAIR_MAX_EDGE_M
            for vertex in branched_vertices
        ):
            raise TrimRimQualityError(
                nonmanifold_edges=len(branched_vertices)
            )
        bmesh.ops.dissolve_verts(
            bm,
            verts=branched_vertices,
            use_face_split=False,
            use_boundary_tear=True,
        )
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
    raise TrimRimQualityError(
        nonmanifold_edges=len(_branched_trim_vertices(bm))
    )


def _collapse_skinny_triangles(bm):
    """Collapse only short edges belonging to extreme-aspect triangles."""
    for _iteration in range(4):
        short_edges = set()
        for face in bm.faces:
            if len(face.verts) != 3:
                continue
            area = face.calc_area()
            if area <= 1.0e-12:
                short_edges.add(min(face.edges, key=lambda edge: edge.calc_length()))
                continue
            lengths = [edge.calc_length() for edge in face.edges]
            aspect = sum(length * length for length in lengths) / (
                4.0 * math.sqrt(3.0) * area
            )
            shortest = min(face.edges, key=lambda edge: edge.calc_length())
            if (
                aspect > 20.0 and shortest.calc_length() < 0.001
            ) or (
                aspect > 100.0 and shortest.calc_length() < 0.0025
            ):
                short_edges.add(shortest)
        if not short_edges:
            return
        bmesh.ops.collapse(bm, edges=list(short_edges))
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bmesh.ops.beautify_fill(bm, faces=list(bm.faces), method="AREA")


def _remove_exact_fillet_degenerates(corset):
    """Remove numerical zero-area remnants without reshaping the fillet.

    The tolerance is 0.0001 mm: far below printable or visible geometry and
    roughly three orders of magnitude below an eight-segment 1 mm round-over.
    Unlike ``_remove_shell_slivers``, this never collapses skinny triangles or
    re-triangulates the finished rim.
    """
    mesh = corset.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1.0e-8)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=5.0e-7)
    support_ngons = [face for face in bm.faces if len(face.verts) > 3]
    if support_ngons:
        triangulated = bmesh.ops.triangulate(bm, faces=support_ngons)
        bmesh.ops.beautify_fill(
            bm,
            faces=triangulated.get("faces", []),
            method="AREA",
        )
        bmesh.ops.dissolve_degenerate(
            bm, edges=list(bm.edges), dist=5.0e-7
        )
    nearly_collinear = [face for face in bm.faces if face.calc_area() <= 1.0e-11]
    middle_vertices = set()
    for face in nearly_collinear:
        if len(face.edges) != 3:
            continue
        shortest = sorted(face.edges, key=lambda edge: edge.calc_length())[:2]
        shared = set(shortest[0].verts).intersection(shortest[1].verts)
        middle_vertices.update(shared)
    if middle_vertices:
        bmesh.ops.dissolve_verts(
            bm,
            verts=list(middle_vertices),
            use_face_split=False,
            use_boundary_tear=False,
        )
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    for _pass in range(2):
        mesh.calc_loop_triangles()
        repaired = False
        for triangle in mesh.loop_triangles:
            indices = tuple(triangle.vertices)
            coordinates = [mesh.vertices[index].co for index in indices]
            area = 0.5 * (coordinates[1] - coordinates[0]).cross(
                coordinates[2] - coordinates[0]
            ).length
            if area > 1.0e-12:
                continue
            pairs = (
                ((indices[0], indices[1]), (coordinates[0] - coordinates[1]).length),
                ((indices[1], indices[2]), (coordinates[1] - coordinates[2]).length),
                ((indices[2], indices[0]), (coordinates[2] - coordinates[0]).length),
            )
            endpoints = max(pairs, key=lambda pair: pair[1])[0]
            middle_index = next(index for index in indices if index not in endpoints)
            normal = mesh.vertices[middle_index].normal.copy()
            if normal.length_squared > 1.0e-20:
                mesh.vertices[middle_index].co += normal.normalized() * 1.0e-6
                repaired = True
        if not repaired:
            break
        mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = True


def _mesh_edge_use_counts(triangles):
    uses = {}
    for triangle in triangles:
        for first, second in (
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ):
            edge = tuple(sorted((first, second)))
            uses[edge] = uses.get(edge, 0) + 1
    return uses


def _zero_area_triangle_count(coordinates, triangles):
    count = 0
    for first, second, third in triangles:
        cross = (coordinates[second] - coordinates[first]).cross(
            coordinates[third] - coordinates[first]
        )
        count += 0.5 * cross.length <= 1.0e-12
    return count


def _connected_component_count(triangles, vertex_count):
    """Number of connected pieces in a triangle soup, by union-find."""
    parent = list(range(vertex_count))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    used = set()
    for triangle in triangles:
        used.update(triangle)
        first = root(triangle[0])
        for vertex in triangle[1:]:
            second = root(vertex)
            if first != second:
                parent[second] = first
    return len({root(vertex) for vertex in used})


def _validate_finished_rim(corset):
    """Fail transactionally before a folded/degenerate brace can replace one."""
    mesh = corset.data
    mesh.calc_loop_triangles()
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    edge_uses = _mesh_edge_use_counts(triangles)
    boundary_edges = sum(count == 1 for count in edge_uses.values())
    nonmanifold_edges = sum(count > 2 for count in edge_uses.values())
    if boundary_edges or nonmanifold_edges:
        raise TrimRimQualityError(
            boundary_edges=boundary_edges,
            nonmanifold_edges=nonmanifold_edges,
        )
    # A watertight, manifold, non-overlapping result can still be several
    # detached closed ribbons — every other gate here passes for those, which is
    # how a fragmented "brace" reached a user.
    components = _connected_component_count(triangles, len(coordinates))
    if components != 1:
        raise TrimRimQualityError(components=components)
    zero_area = _zero_area_triangle_count(coordinates, triangles)
    if zero_area:
        raise TrimRimQualityError(zero_area=zero_area)
    intersections = triangle_intersection_pairs(coordinates, triangles)
    if intersections:
        raise TrimRimQualityError(intersections=len(intersections))
    corset["rigo_generation_rim_intersections"] = 0
    corset["rigo_generation_zero_area_faces"] = 0


def _round_legacy_rim(context, corset, thickness_mm):
    bevel = corset.modifiers.new(name="Rounded Trim Rim", type="BEVEL")
    bevel.width = min(0.0015, thickness_mm * 0.0003)
    bevel.segments = 3
    bevel.limit_method = "ANGLE"
    bevel.angle_limit = math.radians(35.0)
    _apply(context, corset, "Rounded Trim Rim")


def _bake_generation_metadata(context, corset, settings):
    corset.color = (0.85, 0.85, 0.9, settings.corset_opacity)
    corset["rigo_requested_thickness_mm"] = settings.corset_thickness
    corset["rigo_requested_offset_mm"] = settings.corset_offset
    corset["rigo_requested_fairing"] = settings.corset_smooth
    corset["rigo_trim_transition_width_mm"] = settings.trim_transition_width
    corset["rigo_source_scan_signature"] = geometry_signature(
        context, settings.scan_object
    )
    corset["rigo_source_trim_signature"] = geometry_signature(
        context, bpy.data.objects.get("Rigo Trim Perimeter")
    )
    source_faces = settings.scan_object.data.polygons
    brace_faces = corset.data.polygons
    corset["rigo_source_quad_ratio"] = sum(
        len(face.vertices) == 4 for face in source_faces
    ) / max(1, len(source_faces))
    corset["rigo_brace_quad_ratio"] = sum(
        len(face.vertices) == 4 for face in brace_faces
    ) / max(1, len(brace_faces))
    corset["rigo_brace_dirty"] = False
    corset["rigo_brace_dirty_reason"] = ""


def _build_corset(context, settings, top_profile=None, base=None):
    """(Re)build the solid corset from the cached single-wall base.

    Trim precedence: the Rigo auto trim lines (top+bottom curves), when
    present, define the kept region per angle — the flat trims and the
    parametric opening are skipped entirely. Otherwise ``top_profile`` (the
    legacy editable outline) or the flat ``trim_top`` is used.
    """
    base = base or bpy.data.objects.get(CORSET_BASE_NAME)
    if base is None:
        return None

    stale_candidate = bpy.data.objects.get(_CORSET_CANDIDATE_NAME)
    if stale_candidate is not None:
        _remove_object_and_orphan_mesh(stale_candidate)

    corset = None
    build_complete = False
    try:
        corset = base.copy()
        corset.data = base.data.copy()
        corset.name = _CORSET_CANDIDATE_NAME
        corset.data.name = _CORSET_CANDIDATE_NAME
        corset.hide_set(False)
        context.scene.collection.objects.link(corset)

        perimeter_data = _trim_perimeter_uv(context)
        if perimeter_data is not None:
            _clip_to_perimeter(corset, perimeter_data)
            _clean_open_trim_surface(corset)
        else:
            trim_curves = _trimline_curves(context)
            _trim_and_open(
                corset, settings, top_profile, trim_curves=trim_curves
            )

        corset["rigo_paired_rim_edges"] = _build_paired_shell(
            corset,
            settings.corset_thickness * 0.001,
            settings.trim_fillet_radius if perimeter_data is not None else 0.0,
            settings.trim_fillet_segments if perimeter_data is not None else 2,
        )

        if perimeter_data is None:
            _round_legacy_rim(context, corset, settings.corset_thickness)
            corset["rigo_rounded_rim_edges"] = -1
        if perimeter_data is not None:
            _remove_exact_fillet_degenerates(corset)
            _validate_finished_rim(corset)
            corset["rigo_trim_transition_refined_faces"] = (
                _refine_finished_trim_transition(
                    corset, settings.trim_transition_width * 0.001
                )
            )
            _validate_finished_rim(corset)
        if perimeter_data is not None:
            from .trim_ops import _bake_band_from_vertex_group

            _bake_band_from_vertex_group(
                corset, _RIM_BOUNDARY_GROUP, settings.edge_band
            )

        _bake_generation_metadata(context, corset, settings)
        build_complete = True
        return corset
    finally:
        if not build_complete and _object_is_registered(corset):
            _remove_object_and_orphan_mesh(corset)


def _trim_and_open(corset, settings, top_profile=None, trim_curves=None):
    """Delete faces above/below the trims and inside the closure gap.

    ``trim_curves`` (the Rigo auto trim lines) wins: faces survive only where
    bottom(theta) <= z <= top(theta) in the stamped landmark parameterization —
    this is what keeps the shell off the head/arms of a full-body scan.
    Otherwise ``top_profile`` (legacy outline) or flat cuts apply.
    """
    mesh = corset.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    if trim_curves is not None:
        top_prof, bot_prof, ax, ay, fx, fy = trim_curves
        mw = corset.matrix_world
        doomed = []
        for f in bm.faces:
            c = mw @ f.calc_center_median()
            th = _theta_of(c.x, c.y, ax, ay, fx, fy)
            if not (
                _profile_height(bot_prof, th) <= c.z <= _profile_height(top_prof, th)
            ):
                doomed.append(f)
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        return

    zs = [v.co.z for v in bm.verts]
    if not zs:
        bm.free()
        return
    z_min, z_max = min(zs), max(zs)
    flat_top = z_max - settings.trim_top * 0.001
    bot_cut = z_min + settings.trim_bottom * 0.001

    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    cx = (min(xs) + max(xs)) * 0.5
    cy = (min(ys) + max(ys)) * 0.5
    half_gap = math.radians(settings.opening_width) * 0.5

    # Cheneau opens at the front (-Y), Boston at the back (+Y).
    open_dir = -1.0 if settings.design_style == "CHENEAU" else 1.0

    doomed = []
    for f in bm.faces:
        c = f.calc_center_median()
        top_cut = flat_top
        if top_profile:
            ang = math.atan2(c.x - cx, c.y - cy)
            top_cut = _profile_height(top_profile, ang)
        if c.z > top_cut or c.z < bot_cut:
            doomed.append(f)
            continue
        if half_gap > 0.0:
            ang = math.atan2(c.x - cx, (c.y - cy) * open_dir)
            if abs(ang) < half_gap:
                doomed.append(f)

    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def _profile_height(profile, angle):
    """Linearly interpolate the top-trim height for ``angle`` (radians, -pi..pi)
    from a sorted list of ``(angle, z)`` samples, wrapping around the seam."""
    n = len(profile)
    if n == 1:
        return profile[0][1]
    for i in range(n):
        a0, z0 = profile[i]
        a1, z1 = profile[(i + 1) % n]
        if i + 1 == n:
            a1 += 2.0 * math.pi  # wrap the last span back to the first point
        a = angle if angle >= a0 else angle + 2.0 * math.pi
        if a0 <= a <= a1:
            span = a1 - a0
            t = 0.0 if span == 0.0 else (a - a0) / span
            return z0 + (z1 - z0) * t
    return profile[0][1]


def _apply(context, obj, modifier_name):
    context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier_name)


class RIGO_OT_place_slot(Operator):
    """Click on the corset to drop a strap slot"""

    bl_idname = "rigo.place_slot"
    bl_label = "Place Strap Slot"

    _region = None
    _rv3d = None

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and brace_ready_for_finishing(context)
        )

    def invoke(self, context, event):
        for region in context.area.regions:
            if region.type == "WINDOW":
                self._region = region
                break
        self._rv3d = context.area.spaces.active.region_3d
        if self._region is None or self._rv3d is None:
            self.report({"WARNING"}, "Open this from the 3D viewport")
            return {"CANCELLED"}
        context.window.cursor_modal_set("EYEDROPPER")
        context.workspace.status_text_set(
            "Click on the corset to drop a strap slot  |  Right-click / Esc to finish"
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _ray(self, context, event):
        region, rv3d = self._region, self._rv3d
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        if not (0 <= coord[0] <= region.width and 0 <= coord[1] <= region.height):
            return None, None
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        depsgraph = context.evaluated_depsgraph_get()
        hit, loc, normal, _i, _o, _m = context.scene.ray_cast(
            depsgraph, origin, direction
        )
        return (loc, normal) if hit else (None, None)

    def _add_slot(self, context, location, normal):
        settings = context.scene.rigo_brace
        n = sum(1 for o in bpy.data.objects if o.name.startswith(_SLOT_PREFIX))
        _new_slot_marker(
            context,
            _SlotPlacement(
                f"{_SLOT_PREFIX}{n}",
                location,
                normal,
                settings.slot_width,
                settings.slot_height,
            ),
        )
        if settings.symmetrical:
            mloc = location.copy()
            mloc.x = -mloc.x
            mirrored_normal = normal.copy() if normal is not None else None
            if mirrored_normal is not None:
                mirrored_normal.x = -mirrored_normal.x
            _new_slot_marker(
                context,
                _SlotPlacement(
                    f"{_SLOT_PREFIX}{n}_m",
                    mloc,
                    mirrored_normal,
                    settings.slot_width,
                    settings.slot_height,
                ),
            )

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            context.window.cursor_modal_restore()
            context.workspace.status_text_set(None)
            return {"FINISHED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            loc, normal = self._ray(context, event)
            if loc is None:
                self.report({"WARNING"}, "Click on the corset")
                return {"RUNNING_MODAL"}
            self._add_slot(context, loc, normal)
            return {"RUNNING_MODAL"}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}


class RIGO_OT_cut_slots(Operator):
    """Cut every placed strap slot out of the corset"""

    bl_idname = "rigo.cut_slots"
    bl_label = "Cut Strap Slots"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return brace_ready_for_finishing(context)

    def execute(self, context):
        corset = bpy.data.objects.get(CORSET_NAME)
        if corset is None:
            self.report({"ERROR"}, "Generate the corset first")
            return {"CANCELLED"}
        slots = [o for o in bpy.data.objects if o.name.startswith(_SLOT_PREFIX)]
        if not slots:
            self.report({"WARNING"}, "Place at least one slot first")
            return {"CANCELLED"}

        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        settings = context.scene.rigo_brace
        original_mesh = corset.data.copy()
        initial_volume = _mesh_volume(corset.data)
        initial_surface_chi = _surface_euler_characteristic(corset.data)
        cut = 0
        try:
            for slot in slots:
                cutter = self._make_cutter(context, slot)
                modifier = corset.modifiers.new(name=f"Strap Slot {cut + 1}", type="BOOLEAN")
                modifier_name = modifier.name
                cutter_name = cutter.name
                modifier.operation = "DIFFERENCE"
                modifier.solver = "EXACT"
                modifier.object = cutter
                try:
                    _apply(context, corset, modifier_name)
                except RuntimeError as error:
                    raise SlotCutError("Blender could not resolve the local cut") from error
                finally:
                    remaining = corset.modifiers.get(modifier_name)
                    if remaining is not None:
                        corset.modifiers.remove(remaining)
                    stale_cutter = bpy.data.objects.get(cutter_name)
                    if stale_cutter is not None:
                        _remove_object_and_orphan_mesh(stale_cutter)
                cut += 1

            final_volume = _mesh_volume(corset.data)
            removed_volume = initial_volume - final_volume
            minimum_change = max(1.0e-12, initial_volume * 1.0e-8)
            if removed_volume <= minimum_change:
                raise SlotCutError(
                    "the slot markers do not intersect the brace; place them on the surface"
                )

            rounded_edges = _round_slot_edges(
                corset,
                slots,
                settings.slot_edge_radius,
                settings.corset_thickness,
            )
            if settings.slot_edge_radius > 0.0 and rounded_edges == 0:
                raise SlotCutError("the new slot rim could not be identified for rounding")
            # Exact Boolean intersections against a dense scan-derived wall
            # can leave microscopic triangles at the fillet junction. Clean
            # only the slot neighbourhood so unrelated brace topology stays
            # untouched; validation below remains the final authority.
            _remove_slot_slivers(corset, slots)
            final_surface_chi = _surface_euler_characteristic(corset.data)
            expected_chi = initial_surface_chi - 2 * cut
            if final_surface_chi != expected_chi:
                openings = (initial_surface_chi - final_surface_chi) // 2
                raise SlotCutError(
                    "a marker crossed more or fewer than one brace wall; "
                    f"expected {cut} opening(s), measured {openings}; "
                    "reposition it on a clear local surface"
                )
            _validate_finished_rim(corset)
        except (SlotCutError, TrimRimQualityError) as error:
            _restore_slot_cut_mesh(corset, original_mesh)
            corset["rigo_slot_status"] = f"FAILED: {error}"
            self.report(
                {"ERROR"},
                f"Slot cut cancelled; the previous brace was kept ({error})",
            )
            return {"CANCELLED"}
        except Exception:
            _restore_slot_cut_mesh(corset, original_mesh)
            raise

        if original_mesh.users == 0:
            bpy.data.meshes.remove(original_mesh)
        for slot in slots:
            _remove_object_and_orphan_mesh(slot)
        corset["rigo_slot_count"] = cut
        corset["rigo_slot_width_mm"] = float(settings.slot_width)
        corset["rigo_slot_height_mm"] = float(settings.slot_height)
        corset["rigo_slot_status"] = f"CUT: {cut} vertical rounded slot(s)"
        invalidate_brace_qa(corset, "Strap slots changed")
        self.report(
            {"INFO"},
            f"Cut {cut} rounded strap slot(s); manufacturing QA must be verified again",
        )
        return {"FINISHED"}

    @staticmethod
    def _make_cutter(context, slot):
        w = slot.get("rigo_h", 12.0) * 0.001
        h = slot.get("rigo_w", 40.0) * 0.001
        brace = bpy.data.objects.get(CORSET_NAME)
        built_thickness_mm = (
            brace.get("rigo_requested_thickness_mm")
            if brace is not None
            else None
        )
        if built_thickness_mm is None:
            built_thickness_mm = context.scene.rigo_brace.corset_thickness
        wall_thickness = float(built_thickness_mm) * 0.001
        depth = max(
            _SLOT_MIN_CUTTER_DEPTH_M,
            wall_thickness * 2.0 + 0.004,
        )
        mesh = _capsule_prism_mesh("Rigo Slot Cutter", w, h, depth)
        cutter = bpy.data.objects.new("Rigo Slot Cutter", mesh)
        context.scene.collection.objects.link(cutter)
        cutter.rotation_mode = slot.rotation_mode
        if slot.rotation_mode == "QUATERNION":
            cutter.rotation_quaternion = slot.rotation_quaternion
        else:
            cutter.rotation_euler = slot.rotation_euler
        stored_normal = slot.get("rigo_normal")
        if stored_normal is not None:
            surface_normal = Vector(stored_normal).normalized()
        else:
            surface_normal = cutter.rotation_quaternion @ Vector((0.0, 0.0, 1.0))
        cutter.location = slot.location - surface_normal * wall_thickness
        return cutter


class RIGO_OT_clear_slots(Operator):
    """Remove all placed (uncut) strap slots"""

    bl_idname = "rigo.clear_slots"
    bl_label = "Clear Strap Slots"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = 0
        for o in list(bpy.data.objects):
            if o.name.startswith(_SLOT_PREFIX):
                _remove_object_and_orphan_mesh(o)
                removed += 1
        self.report({"INFO"}, f"Removed {removed} slot(s)")
        return {"FINISHED"}


def _remove_emboss_preview(preview):
    if preview is None:
        return
    preview_data = preview.data
    bpy.data.objects.remove(preview, do_unlink=True)
    if preview_data.users == 0:
        bpy.data.curves.remove(preview_data)


def _new_emboss_preview(context, corset, text, location, normal, size_mm):
    _remove_emboss_preview(bpy.data.objects.get(_EMBOSS_PREVIEW_NAME))
    font = bpy.data.curves.new(f"{_EMBOSS_PREVIEW_NAME} Font", type="FONT")
    font.body = text
    font.align_x = "CENTER"
    font.align_y = "CENTER"
    font.size = size_mm * 0.001
    font.resolution_u = 12
    preview = bpy.data.objects.new(_EMBOSS_PREVIEW_NAME, font)
    local_frame = Matrix.Translation(location) @ _vertical_surface_rotation(normal).to_matrix().to_4x4()
    preview.matrix_world = corset.matrix_world @ local_frame
    preview.show_in_front = True
    preview.display_type = "WIRE"
    preview["rigo_surface_normal"] = tuple(normal.normalized())
    context.scene.collection.objects.link(preview)
    bpy.ops.object.select_all(action="DESELECT")
    preview.select_set(True)
    context.view_layer.objects.active = preview
    return preview


class RIGO_OT_place_emboss(Operator):
    """Click the brace to place an editable text preview."""

    bl_idname = "rigo.place_emboss"
    bl_label = "Place Text on Brace"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and brace_ready_for_finishing(context)

    def invoke(self, context, event):
        text = context.scene.rigo_brace.emboss_text.strip()
        if not text:
            self.report({"WARNING"}, "Type the emboss text first")
            return {"CANCELLED"}
        self._region = next(region for region in context.area.regions if region.type == "WINDOW")
        self._rv3d = context.area.spaces.active.region_3d
        context.window.cursor_modal_set("EYEDROPPER")
        context.workspace.status_text_set("Click the exact brace area for the text | Esc cancels")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            context.window.cursor_modal_restore()
            context.workspace.status_text_set(None)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            location, normal = self._surface_hit(context, event)
            if location is None:
                self.report({"WARNING"}, "Click directly on the brace")
                return {"RUNNING_MODAL"}
            settings = context.scene.rigo_brace
            _new_emboss_preview(context, bpy.data.objects[CORSET_NAME], settings.emboss_text.strip(), location, normal, settings.emboss_size)
            context.window.cursor_modal_restore()
            context.workspace.status_text_set(None)
            return {"FINISHED"}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def _surface_hit(self, context, event):
        coordinate = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
        direction = view3d_utils.region_2d_to_vector_3d(self._region, self._rv3d, coordinate)
        origin = view3d_utils.region_2d_to_origin_3d(self._region, self._rv3d, coordinate)
        brace = bpy.data.objects.get(CORSET_NAME)
        inverse = brace.matrix_world.inverted()
        local_origin = inverse @ origin
        local_direction = (inverse.to_3x3() @ direction).normalized()
        hit, location, normal, _face = brace.ray_cast(local_origin, local_direction)
        return (location, normal.normalized()) if hit else (None, None)


class RIGO_OT_clear_emboss(Operator):
    """Remove the uncommitted text preview."""

    bl_idname = "rigo.clear_emboss"
    bl_label = "Clear Text Preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _remove_emboss_preview(bpy.data.objects.get(_EMBOSS_PREVIEW_NAME))
        return {"FINISHED"}


class RIGO_OT_emboss_text(Operator):
    """Project measured raised or engraved text onto the anterior brace."""

    bl_idname = "rigo.emboss_text"
    bl_label = "Emboss Text"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return brace_ready_for_finishing(context)

    def execute(self, context):
        settings = context.scene.rigo_brace
        corset = bpy.data.objects.get(CORSET_NAME)
        if corset is None:
            self.report({"ERROR"}, "Generate the corset first")
            return {"CANCELLED"}
        text = settings.emboss_text.strip()
        if not text:
            self.report({"WARNING"}, "Type some text first")
            return {"CANCELLED"}
        preview = bpy.data.objects.get(_EMBOSS_PREVIEW_NAME)
        if preview is None or preview.type != "FONT":
            self.report({"WARNING"}, "Place the text on the brace first")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        original_mesh = corset.data.copy()
        initial_volume = _mesh_volume(corset.data)
        text_mesh = self._text_tool(context, preview, settings)
        try:
            self._apply_text(context, corset, text_mesh, settings.emboss_mode)
            final_volume = _mesh_volume(corset.data)
            if not self._volume_changed(initial_volume, final_volume, settings.emboss_mode):
                raise RuntimeError("text did not intersect the curved brace surface")
            _remove_exact_fillet_degenerates(corset)
            _validate_finished_rim(corset)
        except (RuntimeError, TrimRimQualityError) as error:
            _restore_slot_cut_mesh(corset, original_mesh)
            self.report({"ERROR"}, f"Emboss cancelled; previous brace kept ({error})")
            return {"CANCELLED"}
        finally:
            _remove_object_and_orphan_mesh(text_mesh)
        if original_mesh.users == 0:
            bpy.data.meshes.remove(original_mesh)
        _remove_emboss_preview(preview)
        corset["rigo_emboss_text"] = text
        corset["rigo_emboss_mode"] = settings.emboss_mode
        corset["rigo_emboss_depth_mm"] = float(settings.emboss_depth)
        invalidate_brace_qa(corset, "Emboss changed")
        self.report({"INFO"}, f"{settings.emboss_mode.title()} text applied")
        return {"FINISHED"}

    @staticmethod
    def _text_tool(context, preview, settings):
        text_object = preview.copy()
        text_object.data = preview.data.copy()
        text_object.name = "Rigo Emboss Tool"
        text_object.data.extrude = 0.001
        text_object.data.bevel_depth = min(0.00025, settings.emboss_depth * 0.00015)
        text_object.data.bevel_resolution = 3
        context.scene.collection.objects.link(text_object)
        bpy.ops.object.select_all(action="DESELECT")
        text_object.select_set(True)
        context.view_layer.objects.active = text_object
        bpy.ops.object.convert(target="MESH")
        RIGO_OT_emboss_text._fit_tool_depth(text_object.data, settings)
        tool_bmesh = bmesh.new()
        tool_bmesh.from_mesh(text_object.data)
        bmesh.ops.recalc_face_normals(tool_bmesh, faces=list(tool_bmesh.faces))
        tool_bmesh.to_mesh(text_object.data)
        tool_bmesh.free()
        text_object.data.update()
        remesh = text_object.modifiers.new(name="Emboss Tool Remesh", type="REMESH")
        remesh.mode = "VOXEL"
        remesh.voxel_size = max(0.00012, min(0.0003, settings.emboss_size * 0.000015))
        remesh.adaptivity = 0.0
        remesh.use_remove_disconnected = False
        _apply(context, text_object, remesh.name)
        return text_object

    @staticmethod
    def _fit_tool_depth(mesh, settings):
        minimum_z = min(vertex.co.z for vertex in mesh.vertices)
        maximum_z = max(vertex.co.z for vertex in mesh.vertices)
        current_depth = max(maximum_z - minimum_z, 1.0e-9)
        overlap = min(0.0006, settings.emboss_depth * 0.0004)
        if settings.emboss_mode == "RAISED":
            target_minimum, target_maximum = -overlap, settings.emboss_depth * 0.001
        else:
            target_minimum, target_maximum = -settings.emboss_depth * 0.001, overlap
        scale = (target_maximum - target_minimum) / current_depth
        for vertex in mesh.vertices:
            vertex.co.z = target_minimum + (vertex.co.z - minimum_z) * scale
        mesh.update()

    @staticmethod
    def _apply_text(context, corset, text_mesh, mode):
        modifier = corset.modifiers.new(name="Emboss", type="BOOLEAN")
        modifier.operation = "UNION" if mode == "RAISED" else "DIFFERENCE"
        modifier.solver = "EXACT"
        modifier.object = text_mesh
        _apply(context, corset, modifier.name)

    @staticmethod
    def _volume_changed(initial_volume, final_volume, mode):
        tolerance = max(1.0e-12, initial_volume * 1.0e-8)
        if mode == "RAISED":
            return final_volume - initial_volume > tolerance
        return initial_volume - final_volume > tolerance


# --------------------------------------------------------------------------- #
# Editable top trim line (the "Outline" tool in LeoSpinal)
# --------------------------------------------------------------------------- #

def _centroid_xy(obj):
    """Object-space XY centre of a mesh from its bounding box."""
    corners = [Vector(c) for c in obj.bound_box]
    cx = sum(c.x for c in corners) / 8.0
    cy = sum(c.y for c in corners) / 8.0
    return cx, cy


def _seed_outline_points(base, settings):
    """Sample the cached base shell into a ring of (x, y, z) control points that
    sit on the surface at the flat trim-top height — the starting trim line."""
    mesh = base.data
    verts = mesh.vertices
    if not verts:
        return []
    zs = [v.co.z for v in verts]
    z_max = max(zs)
    flat_top = z_max - settings.trim_top * 0.001
    cx, cy = _centroid_xy(base)

    # Verts in a height band around the trim line; widen until we have enough.
    band = 0.015
    band_verts = []
    for _ in range(6):
        band_verts = [v.co for v in verts if abs(v.co.z - flat_top) <= band]
        if len(band_verts) >= settings.outline_segments * 2:
            break
        band += 0.015
    if not band_verts:
        band_verts = [v.co for v in verts]

    n = settings.outline_segments
    points = []
    for i in range(n):
        ang = -math.pi + (2.0 * math.pi) * i / n
        dx, dy = math.sin(ang), math.cos(ang)  # matches atan2(x-cx, y-cy)
        best = None
        best_proj = -1e9
        for co in band_verts:
            proj = (co.x - cx) * dx + (co.y - cy) * dy
            if proj > best_proj:
                best_proj = proj
                best = co
        if best is None:
            continue
        points.append((best.x, best.y, flat_top))
    return points


def _make_outline_curve(context, base, points):
    """Create the editable closed Bezier outline aligned to the base."""
    old = bpy.data.objects.get(OUTLINE_CURVE_NAME)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)

    curve = bpy.data.curves.new(OUTLINE_CURVE_NAME, type="CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.003  # a visible tube so the trim line reads clearly
    curve.resolution_u = 6

    spline = curve.splines.new("BEZIER")
    spline.use_cyclic_u = True
    spline.bezier_points.add(len(points) - 1)
    for bp, co in zip(spline.bezier_points, points):
        bp.co = co
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"

    obj = bpy.data.objects.new(OUTLINE_CURVE_NAME, curve)
    obj.matrix_world = base.matrix_world.copy()
    obj.color = (0.15, 0.45, 0.95, 1.0)  # blue, like LeoSpinal trim lines
    context.scene.collection.objects.link(obj)
    return obj


def _outline_profile(curve_obj, base):
    """Read the curve's control points into a sorted (angle, z) profile."""
    cx, cy = _centroid_xy(base)
    samples = []
    for spline in curve_obj.data.splines:
        for bp in spline.bezier_points:
            ang = math.atan2(bp.co.x - cx, bp.co.y - cy)
            samples.append((ang, bp.co.z))
    samples.sort(key=lambda s: s[0])
    return samples


class RIGO_OT_edit_outline(Operator):
    """Show draggable control points for the top trim line"""

    bl_idname = "rigo.edit_outline"
    bl_label = "Edit Trim Line"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bpy.data.objects.get(CORSET_BASE_NAME) is not None

    def execute(self, context):
        settings = context.scene.rigo_brace
        base = bpy.data.objects.get(CORSET_BASE_NAME)
        if base is None:
            self.report({"ERROR"}, "Generate the corset first")
            return {"CANCELLED"}

        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        curve = bpy.data.objects.get(OUTLINE_CURVE_NAME)
        if curve is None:
            points = _seed_outline_points(base, settings)
            if not points:
                self.report({"ERROR"}, "Could not read the corset surface")
                return {"CANCELLED"}
            curve = _make_outline_curve(context, base, points)

        # Hide the solid corset while editing, exactly like the reference tool.
        corset = bpy.data.objects.get(CORSET_NAME)
        if corset is not None:
            corset.hide_set(True)

        for obj in context.view_layer.objects:
            obj.select_set(False)
        curve.hide_set(False)
        curve.select_set(True)
        context.view_layer.objects.active = curve
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.curve.select_all(action="SELECT")

        settings.outline_editing = True
        self.report(
            {"INFO"},
            "Drag the blue points to move the trim line, green handles to round it",
        )
        return {"FINISHED"}


class RIGO_OT_apply_outline(Operator):
    """Re-trim the corset to the edited top trim line"""

    bl_idname = "rigo.apply_outline"
    bl_label = "Apply Trim Line"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bpy.data.objects.get(OUTLINE_CURVE_NAME) is not None

    def execute(self, context):
        settings = context.scene.rigo_brace
        base = bpy.data.objects.get(CORSET_BASE_NAME)
        curve = bpy.data.objects.get(OUTLINE_CURVE_NAME)
        if base is None or curve is None:
            self.report({"ERROR"}, "Generate the corset and edit the trim first")
            return {"CANCELLED"}

        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        profile = _outline_profile(curve, base)
        try:
            corset = _rebuild_existing_base(
                context, settings, profile, remove_outline=False
            )
        except (OuterWallIntersectionError, TrimRimQualityError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if corset is None:
            self.report({"ERROR"}, "Could not rebuild the corset")
            return {"CANCELLED"}

        curve.hide_set(True)
        settings.outline_editing = False
        for obj in context.view_layer.objects:
            obj.select_set(False)
        corset.select_set(True)
        context.view_layer.objects.active = corset
        self.report({"INFO"}, "Trim line applied")
        return {"FINISHED"}


class RIGO_OT_reset_outline(Operator):
    """Reset the top trim line back to a flat cut"""

    bl_idname = "rigo.reset_outline"
    bl_label = "Reset Trim Line"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bpy.data.objects.get(CORSET_BASE_NAME) is not None

    def execute(self, context):
        settings = context.scene.rigo_brace
        base = bpy.data.objects.get(CORSET_BASE_NAME)
        if base is None:
            self.report({"ERROR"}, "Generate the corset first")
            return {"CANCELLED"}

        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        try:
            corset = _rebuild_existing_base(
                context, settings, top_profile=None, remove_outline=True
            )
        except (OuterWallIntersectionError, TrimRimQualityError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.outline_editing = False
        if corset is not None:
            corset.hide_set(False)
            context.view_layer.objects.active = corset
        self.report({"INFO"}, "Trim line reset to a flat cut")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_design_view,
    RIGO_OT_generate_corset,
    RIGO_OT_edit_outline,
    RIGO_OT_apply_outline,
    RIGO_OT_reset_outline,
    RIGO_OT_place_slot,
    RIGO_OT_cut_slots,
    RIGO_OT_clear_slots,
    RIGO_OT_place_emboss,
    RIGO_OT_clear_emboss,
    RIGO_OT_emboss_text,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
