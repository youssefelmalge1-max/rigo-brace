"""Curve-first brace construction from one immutable trim perimeter."""

import math
from dataclasses import dataclass

import bmesh
import bpy
from bpy.types import Operator
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier, intersect_point_line
from mathutils.kdtree import KDTree

from ..core import (
    BUILD_TRIM_PERIMETER_NAME,
)
from . import design_ops
from .custom_trim_ops import (
    CustomTrimMaskError,
    _mask_values,
    _smooth_closed_parametric,
    _turn_radius_m,
)

_BUILD_CURVE_CANDIDATE = "Rigo Build Trim Perimeter Candidate"
# The BRACE-view overlay must never touch the shell. Its Shrinkwrap target is
# the BASE - the shell's inner-wall surface - so any offset smaller than the
# wall thickness leaves the line inside the wall material: the previous
# 1.2 mm tube on a 0.2 mm offset had 100 % of its centerline closer to the
# shell than the tube radius, and its emerging half read as a doubled trim
# edge. The overlay therefore clears the OUTER wall: offset = requested wall
# thickness + this clearance, with a thin tube well below the clearance.
_PREVIEW_BEVEL_M = 0.0003
_PREVIEW_CLEARANCE_M = 0.0015
_CUTTER_TAG_ATTRIBUTE = "rigo_curve_cutter_face"
_CUTTER_HALF_DEPTH_M = 0.0015
_EXACT_CUT_WELD_M = 0.000005
_RIM_MIN_EDGE_M = 0.0001
_CUT_SLIVER_AREA_M2 = 5.0e-9
_RIM_SPACING_RADIUS_FACTOR = 4.0
_RIM_SPACING_MIN_M = 0.0008
# Capped at the finest spacing proven to articulate the smallest genuine
# boundary feature on the reference trimline (a ~1.8 mm hairpin nub): at the
# earlier 2.5 mm cap the collapse floor (1.25 mm) mangled that nub into a
# fold the rim strip crossed (4 wall-vs-rim overlaps at the default 1.0 mm
# radius request). The consequence is that delivered fillet radius is
# spacing-limited to ~0.35 x 1.2 mm regardless of larger requests - reported
# honestly in the stored rigo_trim_fillet_* properties.
_RIM_SPACING_MAX_M = 0.0012
_RIM_SPLIT_TRIGGER = 1.3
_RIM_COLLAPSE_TRIGGER = 0.5
_RIM_CORNER_TURN_RAD = math.radians(50.0)
_RIM_CORNER_WINDOW = 1.5
_RIM_RELAX_PASSES = 30
_RIM_RELAX_STEP = 0.5
_RIM_RELAX_CAP = 0.33
_RIM_RELAX_MAX_TURN_RAD = math.radians(40.0)
# Stage-2 projection de-burring. Sigma is a physical millimetre feature size
# (see `_smooth_closed_parametric`); the feature radius protects genuine
# corners; the shift cap keeps any single correction well inside the
# one-sided 0.2 mm band the constraint allows.
_PROJECTION_SMOOTH_M = 0.0010
_PROJECTION_FEATURE_TURN_M = 0.004
# A safety stop only - it must NOT bind in normal use. Tightening it to
# 0.15 mm to bound the correction made things worse, not better (the
# reference brace went from clean to 7 rim overlaps): clipping each point's
# shift to a fixed magnitude while its neighbours are clipped by different
# amounts destroys exactly the smoothness the Gaussian just created.
# Correction strength is controlled by sigma, which is continuous.
_PROJECTION_MAX_SHIFT_M = 0.0004
_RIM_CUSP_TURN_RAD = math.radians(30.0)
_RIM_CUSP_PASSES = 12
_RIM_CUSP_STEP = 0.35
# Displacement cap, as a fraction of local spacing (~0.7 mm at the worst
# corner, so ~0.35 mm of travel). At 0.30 the pass took the corner from 111
# to 58 degrees but was still clamped; the residual is close to what a
# genuine 0.74 mm turn radius sampled at 0.66 mm must show, so the remaining
# lever is letting the corner open slightly further - which is bounded local
# softening of a sub-millimetre cusp, not a change to the clinical trimline.
_RIM_CUSP_MAX_SHIFT = 0.50
_RIM_REPROJECT_MAX_M = 0.00015
_RIM_CROSSING_REPAIR_PASSES = 4
_RIM_BAND_SLIVER_TRIGGER = 0.35
_RIM_REPAIR_MAX_EDGE = 0.75
_RIM_FRAME_DOT_SAFE = 0.5
# Ceiling on the rim radius as a multiple of local boundary spacing.
# This looks over-conservative - it holds the delivered radius to ~0.35 mm
# against a 1.0 mm request - and the argument that it is unmotivated is
# tempting, because spacing runs ALONG the boundary while the cap bulges
# PERPENDICULAR to it. Measurement says otherwise. Swept at 0.35/0.5/0.75/
# 1.0/1.5/2.0 on three fixtures:
#   4 mm wall, reference trimline : clean at every factor
#   4 mm wall, hostile hairpin    : clean to 0.75, then 12/13/19 overlaps
#   6 mm wall, reference trimline : clean ONLY at 0.35; 0.5 already gives 2
# Thicker walls carry the cap further from the surface, so the profiles of
# neighbouring boundary points converge sooner - a real limit that the
# curvature clamp alone does not cover. 0.35 is the only value safe across
# all three, and raising it to 0.75 did in fact break the 6 mm case in
# thicknesstest. Do not raise this without re-running the sweep across wall
# thicknesses as well as trimlines.
_RIM_SPACING_RADIUS_CEILING = 0.35


@dataclass(frozen=True)
class _ProjectedPerimeter:
    coordinates: tuple
    normals: tuple
    polygon: tuple
    theta_min: float
    theta_max: float
    axis: tuple
    front: tuple

    def contains(self, world_coordinate):
        angle = design_ops._theta_of(
            world_coordinate.x,
            world_coordinate.y,
            self.axis[0],
            self.axis[1],
            self.front[0],
            self.front[1],
        )
        return design_ops._inside_unwrapped_polygon(
            (angle % math.tau, world_coordinate.z),
            self.polygon,
            self.theta_min,
            self.theta_max,
        )


@dataclass(frozen=True)
class _OrientedProjectedRegion:
    projected: _ProjectedPerimeter
    keep_inside: bool

    def contains(self, world_coordinate):
        return self.projected.contains(world_coordinate) == self.keep_inside


@dataclass(frozen=True)
class _ShellTopology:
    triangles: tuple
    surface_faces: tuple
    boundary: tuple
    vertex_count: int
    segments: int


@dataclass(frozen=True)
class _RimVertex:
    index: int
    outward: Vector
    radius: float


def _curve_world_samples(perimeter):
    matrix = perimeter.matrix_world
    samples = []
    for spline in perimeter.data.splines:
        points = spline.bezier_points
        intervals = max(24, 2048 // max(1, len(points)))
        for index, first in enumerate(points):
            second = points[(index + 1) % len(points)]
            segment = interpolate_bezier(
                first.co,
                first.handle_right,
                second.handle_left,
                second.co,
                intervals + 1,
            )
            samples.extend(matrix @ coordinate for coordinate in segment[:-1])
    return samples


def _projection_target(base):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return (
        base.matrix_world.inverted(),
        BVHTree.FromObject(base, depsgraph),
        design_ops._source_surface(base.data),
    )


def _debur_projected_curve(coordinates, source_surface):
    """Take the mold's triangle noise back out of the projected trimline.

    `find_nearest` lands every sample exactly on a mold facet, so a ~3.7 mm
    triangulation is stamped into a curve later sampled at ~1 mm. Measured
    over identical sample counts, that projection alone multiplies the
    trimline's turn angle by 2.7x (p95 2.32 -> 6.19 degrees) and puts 28.8 %
    of points into sign alternation - the repeated silhouette scalloping.
    Every later stage tracks its input faithfully and none removes it, so it
    is corrected here, at the injection point.

    `design_ops._constrain_to_source_band` already documents this exact
    failure on the legacy path ("re-projecting every fairing step exactly
    onto a faceted scan copies its triangle noise into the trim silhouette")
    and the one-sided band is reused rather than reinvented: the curve may
    bridge facets outward by up to 0.2 mm, and can never sink into the mold.

    Genuine corners are protected by the turn radius of the SMOOTHED curve,
    not the raw one - facet noise looks like a tight turn on the raw curve
    and would protect itself from correction. The weight ramps in over a
    further feature radius so protected and corrected stretches meet
    continuously.
    """
    count = len(coordinates)
    if _PROJECTION_SMOOTH_M <= 0.0 or count < 16:
        return list(coordinates)
    spacing = (
        sum(
            (coordinates[(index + 1) % count] - coordinates[index]).length
            for index in range(count)
        )
        / count
    )
    if spacing <= 1.0e-9:
        return list(coordinates)
    smoothed = _smooth_closed_parametric(
        coordinates, _PROJECTION_SMOOTH_M, spacing
    )
    feature = _PROJECTION_FEATURE_TURN_M
    corrected = []
    for index, point in enumerate(coordinates):
        turn = _turn_radius_m(
            smoothed[index - 1], smoothed[index], smoothed[(index + 1) % count]
        )
        weight = 0.0 if feature <= 0.0 else min(
            1.0, max(0.0, (turn - feature) / feature)
        )
        if weight <= 0.0:
            corrected.append(point.copy())
            continue
        candidate = point.lerp(smoothed[index], weight)
        shift = candidate - point
        if shift.length > _PROJECTION_MAX_SHIFT_M:
            candidate = point + shift.normalized() * _PROJECTION_MAX_SHIFT_M
        corrected.append(
            design_ops._constrain_to_source_band(source_surface, candidate)
        )
    return corrected


def _projected_samples(base, perimeter):
    inverse, bvh, source_surface = _projection_target(base)
    coordinates = []
    for world_coordinate in _curve_world_samples(perimeter):
        hit = bvh.find_nearest(inverse @ world_coordinate)
        if hit[0] is None:
            raise RuntimeError(
                "The trimline could not be projected onto the offset mold"
            )
        coordinates.append(hit[0].copy())
    coordinates = _debur_projected_curve(coordinates, source_surface)
    # Normals are taken at the CORRECTED positions, so the cutter ribbon is
    # built on the curve that is actually used.
    normals = [
        design_ops._surface_normal_at(source_surface, coordinate)
        for coordinate in coordinates
    ]
    return tuple(coordinates), tuple(normals)


def _projected_perimeter(base, perimeter):
    axis = tuple(float(component) for component in perimeter["rigo_trim_axis"])
    front = tuple(float(component) for component in perimeter["rigo_trim_front"])
    coordinates, normals = _projected_samples(base, perimeter)
    polygon, theta_min, theta_max = design_ops._unwrap_uv_polygon(
        [
            _projected_uv(base, coordinate, axis, front)
            for coordinate in coordinates
        ]
    )
    return _ProjectedPerimeter(
        coordinates, normals, polygon, theta_min, theta_max, axis, front
    )


def _projected_uv(base, coordinate, axis, front):
    world = base.matrix_world @ coordinate
    angle = design_ops._theta_of(
        world.x, world.y, axis[0], axis[1], front[0], front[1]
    )
    return angle % math.tau, world.z


def _cutter_mesh(projected):
    count = len(projected.coordinates)
    lower = [
        coordinate - normal * _CUTTER_HALF_DEPTH_M
        for coordinate, normal in zip(projected.coordinates, projected.normals)
    ]
    upper = [
        coordinate + normal * _CUTTER_HALF_DEPTH_M
        for coordinate, normal in zip(projected.coordinates, projected.normals)
    ]
    faces = [
        (index, (index + 1) % count, count + (index + 1) % count, count + index)
        for index in range(count)
    ]
    mesh = bpy.data.meshes.new("Rigo Curve Cutter")
    mesh.from_pydata(lower + upper, [], faces)
    mesh.update()
    return mesh


def _new_cutter(context, base, projected):
    cutter = bpy.data.objects.new("Rigo Curve Cutter", _cutter_mesh(projected))
    cutter.matrix_world = base.matrix_world.copy()
    _set_face_tag(base.data, 0)
    _set_face_tag(cutter.data, 1)
    context.scene.collection.objects.link(cutter)
    for polygon in cutter.data.polygons:
        polygon.select = True
    return cutter


def _set_face_tag(mesh, value):
    attribute = mesh.attributes.get(_CUTTER_TAG_ATTRIBUTE)
    if attribute is None:
        attribute = mesh.attributes.new(
            _CUTTER_TAG_ATTRIBUTE, "INT", "FACE"
        )
    for entry in attribute.data:
        entry.value = value


def _delete_tagged_cutter_faces(surface):
    bm = bmesh.new()
    bm.from_mesh(surface.data)
    tag = bm.faces.layers.int.get(_CUTTER_TAG_ATTRIBUTE)
    if tag is None:
        bm.free()
        raise RuntimeError("Exact cutter tag was lost during mesh intersection")
    tagged = [face for face in bm.faces if face[tag] == 1]
    bmesh.ops.delete(bm, geom=tagged, context="FACES")
    loose = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(surface.data)
    bm.free()
    surface.data.update()


def _intersect_curve_cutter(context, surface, cutter):
    for polygon in surface.data.polygons:
        polygon.select = False
    bpy.ops.object.select_all(action="DESELECT")
    surface.select_set(True)
    cutter.select_set(True)
    context.view_layer.objects.active = surface
    bpy.ops.object.join()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.intersect(
        mode="SELECT_UNSELECT", separate_mode="ALL", solver="EXACT"
    )
    bpy.ops.object.mode_set(mode="OBJECT")
    _delete_tagged_cutter_faces(surface)
    attribute = surface.data.attributes.get(_CUTTER_TAG_ATTRIBUTE)
    if attribute is not None:
        surface.data.attributes.remove(attribute)


def _inside_mask_agreement(scan, projected):
    mask_values = _mask_values(scan)
    stride = max(1, len(mask_values) // 256)
    agreement = 0.0
    sample_count = 0
    for index in range(0, len(mask_values), stride):
        vertex = scan.data.vertices[index]
        mask_level = mask_values[index]
        world = scan.matrix_world @ vertex.co
        retained = projected.contains(world)
        agreement += mask_level if retained else 1.0 - mask_level
        sample_count += 1
    return agreement, sample_count


def _painted_projected_region(scan, projected):
    inside_score, sample_count = _inside_mask_agreement(scan, projected)
    outside_score = sample_count - inside_score
    return _OrientedProjectedRegion(projected, inside_score >= outside_score)


def _retained_region(settings, perimeter, projected):
    if perimeter.get("rigo_trim_source") != "CUSTOM_PAINT":
        return projected
    scan = settings.scan_object
    if scan is None:
        raise CustomTrimMaskError("The painted patient scan is no longer available")
    return _painted_projected_region(scan, projected)


def _face_is_inside(surface, face, retained_region):
    world = surface.matrix_world @ face.calc_center_median()
    return retained_region.contains(world)


def _keep_curve_interior(surface, retained_region):
    bm = bmesh.new()
    bm.from_mesh(surface.data)
    outside = [
        face
        for face in bm.faces
        if not _face_is_inside(surface, face, retained_region)
    ]
    bmesh.ops.delete(bm, geom=outside, context="FACES")
    loose = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(surface.data)
    bm.free()
    surface.data.update()


def _cut_boundary_vertices(bm):
    """Boundary vertices in a stable order.

    A Python set of BMVert iterates in address order, which changes between
    sessions; `remove_doubles` keeps whichever member of a coincident pair comes
    first, so an unordered input made the generated brace differ run to run for
    identical inputs. Same patient, same settings, same brace is a clinical
    requirement, so the order is pinned to the mesh's own indices.
    """
    bm.verts.index_update()
    unique = {
        vertex for edge in bm.edges if edge.is_boundary for vertex in edge.verts
    }
    return sorted(unique, key=lambda vertex: vertex.index)


def _collapse_cut_slivers(bm):
    bmesh.ops.remove_doubles(
        bm,
        verts=_cut_boundary_vertices(bm),
        dist=_EXACT_CUT_WELD_M,
    )
    bmesh.ops.dissolve_degenerate(
        bm,
        edges=list(bm.edges),
        dist=_EXACT_CUT_WELD_M,
    )
    short_boundary = [
        edge
        for edge in bm.edges
        if edge.is_boundary and edge.calc_length() < _RIM_MIN_EDGE_M
    ]
    if short_boundary:
        bmesh.ops.collapse(bm, edges=short_boundary)
    tiny_cut_faces = [
        face for face in bm.faces if face.calc_area() < _CUT_SLIVER_AREA_M2
    ]
    if tiny_cut_faces:
        shortest_edges = {
            min(face.edges, key=lambda edge: edge.calc_length())
            for face in tiny_cut_faces
        }
        bmesh.ops.collapse(bm, edges=list(shortest_edges))


def _write_clean_bmesh(bm, surface):
    """Keep stable triangles/quads while resolving ambiguous cutter n-gons."""
    cutter_ngons = [face for face in bm.faces if len(face.verts) > 4]
    if cutter_ngons:
        bmesh.ops.triangulate(bm, faces=cutter_ngons)
        _collapse_cut_slivers(bm)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(surface.data)
    bm.free()
    surface.data.update()


def _weld_exact_cut_tolerance(surface):
    """Remove only sub-printer-tolerance slivers created by Exact Intersect."""
    bm = bmesh.new()
    bm.from_mesh(surface.data)
    _collapse_cut_slivers(bm)
    _write_clean_bmesh(bm, surface)


def _boundary_loop_count(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    boundary = [edge for edge in bm.edges if edge.is_boundary]
    invalid = [
        vertex
        for vertex in bm.verts
        if sum(edge.is_boundary for edge in vertex.link_edges) not in (0, 2)
    ]
    loops = _count_edge_components(boundary)
    bm.free()
    if invalid:
        raise design_ops.TrimRimQualityError(nonmanifold_edges=len(invalid))
    return loops


def _count_edge_components(edges):
    remaining = set(edges)
    components = 0
    while remaining:
        components += 1
        pending = [remaining.pop()]
        while pending:
            linked = {
                neighbour
                for vertex in pending.pop().verts
                for neighbour in vertex.link_edges
                if neighbour in remaining and neighbour.is_boundary
            }
            remaining.difference_update(linked)
            pending.extend(linked)
    return components


def _rim_target_spacing_m(settings):
    """Boundary spacing that makes the requested fillet radius achievable.

    The per-vertex rim ceiling is 0.35 x local spacing, so the spacing must
    exceed the delivered radius by a comfortable margin; 4x leaves the ceiling
    above the request even where relaxation settles ~25 % below target. Both
    clamps are physical: finer than 0.8 mm re-creates the dense clusters the
    resample exists to remove, coarser than 2.5 mm starts to straighten the
    clinical trimline between samples.
    """
    requested = settings.trim_fillet_radius * 0.001
    thickness = settings.corset_thickness * 0.001
    radius = min(requested, thickness * 0.45)
    return min(
        max(_RIM_SPACING_RADIUS_FACTOR * radius, _RIM_SPACING_MIN_M),
        _RIM_SPACING_MAX_M,
    )


def _bm_boundary_ring(bm):
    """The open boundary as one deterministically ordered BMVert cycle."""
    bm.verts.index_update()
    linked = {}
    for edge in bm.edges:
        if not edge.is_boundary:
            continue
        first, second = edge.verts
        linked.setdefault(first, []).append(second)
        linked.setdefault(second, []).append(first)
    if not linked or any(len(pair) != 2 for pair in linked.values()):
        return []
    start = min(linked, key=lambda vertex: vertex.index)
    ring = [start]
    visited = {start}
    previous, current = None, start
    while True:
        following = sorted(
            (vertex for vertex in linked[current] if vertex != previous),
            key=lambda vertex: vertex.index,
        )
        if not following or following[0] in visited:
            break
        ring.append(following[0])
        visited.add(following[0])
        previous, current = current, following[0]
    return ring if len(ring) == len(linked) else []


def _split_long_boundary_edges(bm, spacing):
    """Halve boundary edges until none exceeds the target spacing.

    Subdivision points lie exactly on the cut surface, so this phase cannot
    move the trimline at all.
    """
    for _pass in range(16):
        long_edges = [
            edge
            for edge in bm.edges
            if edge.is_boundary
            and edge.calc_length() > spacing * _RIM_SPLIT_TRIGGER
        ]
        if not long_edges:
            return
        # use_single_edge is essential: without it a face whose edge is
        # subdivided is NOT split - it silently becomes an n-gon carrying
        # collinear midpoints, and triangulating that n-gon later emits the
        # zero-area triangles the final validator rejects (measured: 3 such
        # n-gons, one with an exactly-zero corner triple).
        bmesh.ops.subdivide_edges(
            bm, edges=long_edges, cuts=1, use_single_edge=True
        )


def _boundary_corner_anchors(ring, window):
    """Vertices where the trimline genuinely turns, measured over a window.

    Per-edge angles are noise inside the dense Exact-cut clusters, so the
    entering and leaving directions are taken across a fixed arc length
    instead. Anchors are pinned through collapse and relaxation: a clinical
    corner must survive resampling in place, not be averaged away.
    """
    count = len(ring)
    if count < 8:
        return set()
    coordinates = [vertex.co.copy() for vertex in ring]

    def reach(position, direction):
        total = 0.0
        step = position
        for _ in range(count):
            following = (step + direction) % count
            total += (coordinates[following] - coordinates[step]).length
            step = following
            if total >= window:
                break
        return coordinates[step]

    anchors = set()
    for position, vertex in enumerate(ring):
        entering = coordinates[position] - reach(position, -1)
        leaving = reach(position, 1) - coordinates[position]
        if min(entering.length, leaving.length) <= 1.0e-12:
            continue
        if entering.angle(leaving) > _RIM_CORNER_TURN_RAD:
            anchors.add(vertex)
    return anchors


def _collapse_short_boundary_edges(bm, spacing, anchors):
    """Weld sub-spacing boundary edges without moving a pinned corner."""
    floor = spacing * _RIM_COLLAPSE_TRIGGER
    for _pass in range(64):
        bm.verts.index_update()
        short = sorted(
            (
                edge
                for edge in bm.edges
                if edge.is_boundary and edge.calc_length() < floor
            ),
            key=lambda edge: (
                edge.calc_length(),
                min(vertex.index for vertex in edge.verts),
            ),
        )
        if not short:
            return
        used = set()
        targetmap = {}
        for edge in short:
            first, second = sorted(
                edge.verts, key=lambda vertex: vertex.index
            )
            if first in used or second in used:
                continue
            if first in anchors and second in anchors:
                continue
            if second in anchors:
                first, second = second, first
            elif first not in anchors:
                first.co = (first.co + second.co) * 0.5
            targetmap[second] = first
            used.update((first, second))
        if not targetmap:
            return
        bmesh.ops.weld_verts(bm, targetmap=targetmap)


def _relax_boundary_spacing(bm, ring, anchors, source_surface):
    """Equalise boundary spacing by sliding vertices along the trimline.

    Movement is restricted to the local chord direction (so the curve is not
    Laplacian-shrunk), capped per pass below the shortest incident edge (so no
    adjacent face can invert), and every new position is re-projected onto the
    pre-cut offset mold, which keeps the boundary on the original surface by
    construction.
    """
    count = len(ring)
    originals = {vertex: vertex.co.copy() for vertex in ring}
    if count < 4:
        return originals
    for _pass in range(_RIM_RELAX_PASSES):
        snapshot = [vertex.co.copy() for vertex in ring]
        caps = [
            _RIM_RELAX_CAP
            * min(
                (edge.calc_length() for edge in vertex.link_edges),
                default=0.0,
            )
            for vertex in ring
        ]
        moved = []
        for position, vertex in enumerate(ring):
            if vertex in anchors or caps[position] <= 0.0:
                moved.append(None)
                continue
            before = snapshot[position - 1]
            after = snapshot[(position + 1) % count]
            entering = snapshot[position] - before
            leaving = after - snapshot[position]
            if min(entering.length, leaving.length) <= 1.0e-12:
                moved.append(None)
                continue
            # At a hairpin the chord cuts across the throat, so sliding along
            # it drags the apex into the opposite side (measured: 5 of the 8
            # post-relax surface self-crossings). A sharply turning vertex
            # keeps its position.
            if entering.angle(leaving) > _RIM_RELAX_MAX_TURN_RAD:
                moved.append(None)
                continue
            chord = after - before
            if chord.length_squared <= 1.0e-24:
                moved.append(None)
                continue
            tangent = chord.normalized()
            slide = _RIM_RELAX_STEP * (
                ((before + after) * 0.5 - snapshot[position]).dot(tangent)
            )
            slide = max(-caps[position], min(caps[position], slide))
            candidate = snapshot[position] + tangent * slide
            # The legitimate chord-to-surface correction is micrometres; a
            # larger snap means find_nearest picked the WRONG SHEET across a
            # concave pocket, which folds the boundary onto itself.
            hit = source_surface.bvh.find_nearest(candidate)
            if (
                hit[0] is not None
                and (hit[0] - candidate).length <= _RIM_REPROJECT_MAX_M
            ):
                moved.append(hit[0].copy())
            else:
                moved.append(candidate)
        for vertex, position in zip(ring, moved):
            if position is not None:
                vertex.co = position
    return originals


def _soften_boundary_cusps(bm, ring, source_surface, spacing):
    """Round the sub-millimetre cusps that spacing relaxation skips.

    `_relax_boundary_spacing` refuses to move any vertex turning more than
    `_RIM_RELAX_MAX_TURN_RAD`, because sliding along the chord at a hairpin
    drags the apex through the opposite side. That guard is right, but it
    leaves precisely the worst corners untouched: measured on the reference
    brace, one corner turns 110/97/93 degrees between consecutive boundary
    edges over a local turn radius of 0.64 mm, while the samples there sit
    0.9 mm apart - a curve far tighter than its own sampling, which the
    silhouette shows as a cut-off facet (0.84 mm from smooth, against a
    0.031 mm median elsewhere).

    Subdividing cannot fix this: a new midpoint lies ON the existing chord,
    so the polyline keeps its shape. The vertices themselves have to move.
    Each one is drawn toward the midpoint of its neighbours - which rounds
    the cusp rather than sliding along it - with total displacement capped
    at a fraction of the local spacing so a genuine clinical corner is
    softened, never erased, and every new position re-projected onto the
    mold under the same wrong-sheet guard the relaxation uses.
    """
    count = len(ring)
    if count < 5:
        return {}
    originals = {vertex: vertex.co.copy() for vertex in ring}
    limit = _RIM_CUSP_MAX_SHIFT * spacing
    for _pass in range(_RIM_CUSP_PASSES):
        snapshot = [vertex.co.copy() for vertex in ring]
        moved = []
        for position, vertex in enumerate(ring):
            before = snapshot[position - 1]
            here = snapshot[position]
            after = snapshot[(position + 1) % count]
            entering, leaving = here - before, after - here
            if min(entering.length, leaving.length) <= 1.0e-12:
                moved.append(None)
                continue
            if entering.angle(leaving) < _RIM_CUSP_TURN_RAD:
                moved.append(None)
                continue
            candidate = here.lerp((before + after) * 0.5, _RIM_CUSP_STEP)
            shift = candidate - originals[vertex]
            if shift.length > limit:
                candidate = originals[vertex] + shift.normalized() * limit
            hit = source_surface.bvh.find_nearest(candidate)
            if (
                hit[0] is not None
                and (hit[0] - candidate).length <= _RIM_REPROJECT_MAX_M
            ):
                candidate = hit[0].copy()
            moved.append(candidate)
        if not any(position is not None for position in moved):
            break
        for vertex, position in zip(ring, moved):
            if position is not None:
                vertex.co = position
    return originals


def _surface_triangle_crossings(bm):
    bm.verts.index_update()
    coordinates = [tuple(vertex.co) for vertex in bm.verts]
    triangles = []
    owners = []
    for face in bm.faces:
        corners = list(face.verts)
        for step in range(1, len(corners) - 1):
            triangles.append(
                (
                    corners[0].index,
                    corners[step].index,
                    corners[step + 1].index,
                )
            )
            owners.append(face)
    pairs = design_ops.triangle_intersection_pairs(coordinates, triangles)
    return pairs, owners


def _revert_folding_relaxation(bm, originals):
    """Undo the spacing relaxation exactly where it folded the surface.

    One region of the reference mold nearly self-touches; there, any
    tangential slide can push a boundary fan through the neighbouring sheet,
    and no amount of collapsing repairs it without new damage (measured:
    repair reduced 11 crossings to a stubborn 2 that moved with every
    collapse). Uniform spacing is a preference; a non-self-intersecting
    surface is a requirement - so the vertices involved in a crossing simply
    return to their pre-relaxation positions, giving up uniformity only
    there.
    """
    for _round in range(_RIM_CROSSING_REPAIR_PASSES):
        pairs, owners = _surface_triangle_crossings(bm)
        if not pairs:
            return
        reverted = 0
        for first, second in pairs:
            for face in (owners[first], owners[second]):
                if not face.is_valid:
                    continue
                for vertex in face.verts:
                    original = originals.get(vertex)
                    if original is not None and vertex.co != original:
                        vertex.co = original
                        reverted += 1
        if not reverted:
            return


def _boundary_vertex_set(bm):
    return {
        vertex
        for edge in bm.edges
        if edge.is_boundary
        for vertex in edge.verts
    }


def _collapse_boundary_band_slivers(bm, spacing):
    """Remove the Exact cut's interior sliver fans behind the boundary.

    The cut scatters 0.2-0.4 mm interior edges immediately behind the
    trimline. Sliding the boundary above them folds those slivers over their
    neighbours (measured: every post-relax surface self-crossing involved
    one). Only interior-interior edges are collapsed: merging two interior
    vertices can neither pinch the boundary loop nor seal a boundary edge,
    which both happen when an interior vertex is welded INTO the boundary.
    """
    floor = spacing * _RIM_BAND_SLIVER_TRIGGER
    for _pass in range(16):
        boundary_vertices = _boundary_vertex_set(bm)
        band_faces = {
            face
            for vertex in boundary_vertices
            for face in vertex.link_faces
        }
        bm.verts.index_update()
        used = set()
        targets = []
        for edge in sorted(
            (
                edge
                for face in band_faces
                for edge in face.edges
                if edge.calc_length() < floor
                and not any(
                    vertex in boundary_vertices for vertex in edge.verts
                )
            ),
            key=lambda edge: (
                edge.calc_length(),
                min(vertex.index for vertex in edge.verts),
            ),
        ):
            start, end = edge.verts
            if start in used or end in used:
                continue
            targets.append(edge)
            used.update((start, end))
        if not targets:
            return
        bmesh.ops.collapse(bm, edges=targets)


def _repair_boundary_sliver_crossings(bm, spacing):
    """Collapse the sliver edges of locally crossing surface triangles.

    The Exact cut leaves grazing contacts whose triangles share a vertex, so
    the intersection test treats them as adjacent and ignores them; splitting
    the boundary separates the sharing and they surface as genuine crossings
    (measured: 3 on the reference brace, sliver edges 0.26-0.51 mm). Only two
    kinds of edge may be collapsed: a genuine boundary edge between
    ring-adjacent vertices, or a short interior-interior edge. Welding an
    interior vertex into a boundary vertex seals the adjacent boundary edge,
    and welding two non-adjacent boundary vertices pinches the loop into a
    figure-8 - both were measured to corrupt the boundary valence.
    """
    ceiling = spacing * _RIM_REPAIR_MAX_EDGE
    for _pass in range(_RIM_CROSSING_REPAIR_PASSES):
        pairs, owners = _surface_triangle_crossings(bm)
        if not pairs:
            return
        boundary_vertices = _boundary_vertex_set(bm)
        ring = _bm_boundary_ring(bm)
        positions = {vertex: index for index, vertex in enumerate(ring)}
        count = len(ring)
        used = set()
        targets = []
        for first, second in sorted(pairs):
            for face in (owners[first], owners[second]):
                if not face.is_valid:
                    continue
                for edge in sorted(
                    face.edges,
                    key=lambda candidate: (
                        candidate.calc_length(),
                        min(vertex.index for vertex in candidate.verts),
                    ),
                ):
                    start, end = edge.verts
                    if start in used or end in used:
                        continue
                    interior = (
                        start not in boundary_vertices
                        and end not in boundary_vertices
                    )
                    if interior:
                        if edge.calc_length() >= ceiling:
                            continue
                    elif edge.is_boundary:
                        first_ring = positions.get(start)
                        second_ring = positions.get(end)
                        if first_ring is None or second_ring is None:
                            continue
                        gap = min(
                            (first_ring - second_ring) % count,
                            (second_ring - first_ring) % count,
                        )
                        if gap != 1:
                            continue
                    else:
                        continue
                    targets.append(edge)
                    used.update((start, end))
                    break
        if not targets:
            return
        bmesh.ops.collapse(bm, edges=targets)


def _fan_triangulate_face(bm, face, root):
    while face.is_valid and len(face.verts) > 3:
        corners = list(face.verts)
        here = corners.index(root)
        target = corners[(here + 2) % len(corners)]
        try:
            new_face, _loop = bmesh.utils.face_split(face, root, target)
        except ValueError:
            return
        pieces = [
            piece
            for piece in (face, new_face)
            if piece.is_valid and root in set(piece.verts)
        ]
        if not pieces:
            return
        face = max(pieces, key=lambda piece: len(piece.verts))


def _triangulate_boundary_ngons(bm):
    """Take n-gon triangulation out of Blender's hands near the boundary.

    Faces with five or more corners exist only where the resample phases
    merged or split geometry. Leaving them to downstream ear-clipping emitted
    both zero-area triangles (collinear corners that are NOT consecutive, so
    the quad-corner splitter cannot see them) and boundary-shortcut
    diagonals. Fanning from an interior corner is deterministic and can
    produce neither; an all-boundary n-gon fans from its kink middle, the
    same corner the ear splitter would choose.
    """
    boundary_vertices = _boundary_vertex_set(bm)
    ring = _bm_boundary_ring(bm)
    positions = {vertex: index for index, vertex in enumerate(ring)}
    count = max(1, len(ring))
    bm.verts.index_update()
    ngons = sorted(
        (face for face in bm.faces if len(face.verts) > 4),
        key=lambda face: min(vertex.index for vertex in face.verts),
    )
    for face in ngons:
        if not face.is_valid:
            continue
        corners = list(face.verts)
        interior = sorted(
            (vertex for vertex in corners if vertex not in boundary_vertices),
            key=lambda vertex: vertex.index,
        )
        if interior:
            root = interior[0]
        else:
            members = set(corners)
            middles = sorted(
                (
                    vertex
                    for vertex in corners
                    if positions.get(vertex) is not None
                    and ring[positions[vertex] - 1] in members
                    and ring[(positions[vertex] + 1) % count] in members
                ),
                key=lambda vertex: vertex.index,
            )
            root = middles[0] if middles else min(
                corners, key=lambda vertex: vertex.index
            )
        _fan_triangulate_face(bm, face, root)


def _rotate_zero_area_triangles(bm):
    """Resolve collinear triangles by flipping their base diagonal.

    A collinear triangle cannot be dissolved (its edges are full length) and
    collapsing it would move or seal boundary geometry. Rotating its longest
    interior edge re-pairs it with the neighbouring face's off-line corner:
    no vertex moves, boundary valence is untouched, and both resulting
    triangles have area.
    """
    for _pass in range(4):
        bm.verts.index_update()
        rotten = sorted(
            (
                face
                for face in bm.faces
                if len(face.verts) == 3 and face.calc_area() <= 1.0e-11
            ),
            key=lambda face: min(vertex.index for vertex in face.verts),
        )
        if not rotten:
            return
        used = set()
        targets = []
        for face in rotten:
            longest = max(
                face.edges,
                key=lambda edge: (
                    edge.calc_length(),
                    -min(vertex.index for vertex in edge.verts),
                ),
            )
            if (
                longest.is_boundary
                or longest in used
                or len(longest.link_faces) != 2
            ):
                continue
            targets.append(longest)
            used.add(longest)
        if not targets:
            return
        bmesh.ops.rotate_edges(bm, edges=targets, use_ccw=False)


def _split_collinear_quad_corners(bm):
    """Pre-empt the zero-area triangle hiding inside a healthy-looking quad.

    A collapse can leave a quad with three collinear corners (measured: one,
    its middle corner the exact midpoint of a 2.55 mm chord). The quad has
    area, so dissolve_degenerate ignores it - but downstream triangulation
    emits a zero-area triangle from those three corners, which the final
    validator rejects. Splitting through the collinear corner decides the
    triangulation here, where both halves are known to have area.
    """
    targets = []
    for face in bm.faces:
        corners = list(face.verts)
        count = len(corners)
        if count < 4:
            continue
        for position in range(count):
            previous = corners[position - 1].co
            middle = corners[position].co
            following = corners[(position + 1) % count].co
            cross = (middle - previous).cross(following - previous)
            if 0.5 * cross.length <= 1.0e-11:
                targets.append(
                    (
                        face,
                        corners[position],
                        corners[(position + count // 2) % count],
                    )
                )
                break
    for face, middle, opposite in targets:
        if face.is_valid:
            bmesh.ops.connect_verts(bm, verts=[middle, opposite])


def _split_boundary_ear_quads(bm):
    """Force ear-prone faces to triangulate through the kink vertex.

    A face with three consecutive boundary-ring corners (B1, B2, B3) can be
    triangulated along its B1-B3 diagonal, which shortcuts the kink at B2 and
    protrudes past the trimline - the rim strip at B2 then cuts through it
    (measured: 15 of the 16 remaining wall-vs-rim penetrations sat on such
    quad diagonals; the diagonal never exists as a mesh edge, so no
    edge-based repair can see it). Connecting B2 to a non-boundary corner
    decides the triangulation here, on the safe side of the trimline.
    """
    ring = _bm_boundary_ring(bm)
    if not ring:
        return
    positions = {vertex: index for index, vertex in enumerate(ring)}
    count = len(ring)
    bm.verts.index_update()
    targets = []
    for face in bm.faces:
        corners = list(face.verts)
        if len(corners) < 4:
            continue
        members = set(corners)
        for vertex in corners:
            position = positions.get(vertex)
            if position is None:
                continue
            previous = ring[position - 1]
            following = ring[(position + 1) % count]
            if previous not in members or following not in members:
                continue
            here = corners.index(vertex)
            # Prefer an interior corner: connecting the kink to another
            # BOUNDARY corner creates a fresh shortcut chord, which the
            # chord dissolve then removes again - a livelock that left the
            # all-boundary quads at one site untriangulated (measured as
            # "4 local rim overlaps" at 2 mm wall / 6 segment settings).
            candidates = sorted(
                (
                    (positions.get(corner) is not None, corner.index, corner)
                    for offset, corner in enumerate(corners)
                    if corner not in (vertex, previous, following)
                    and abs(offset - here) not in (1, len(corners) - 1)
                ),
            )
            if candidates:
                targets.append((face, vertex, candidates[0][2]))
            break
    for face, middle, opposite in targets:
        if face.is_valid:
            bmesh.ops.connect_verts(bm, verts=[middle, opposite])


def _dissolve_shortcut_chords(bm):
    """Remove wall geometry that shortcuts across a trimline kink.

    Collapsing the boundary can leave "ears": faces whose corners are
    consecutive boundary vertices, held by an interior chord edge joining
    boundary vertices 2-4 ring steps apart. The chord's triangles protrude
    past the boundary polyline and the rim strip cuts through them (measured:
    every one of the 16 wall-vs-rim penetrations sat on such a chord, most as
    the invisible DIAGONAL of a quad). Dissolving the chord merges the ear
    into its neighbour face, and `_split_boundary_ear_quads` then picks the
    safe diagonal through the kink vertex. Iterated, because resolving a
    gap-3 chord exposes a gap-2 one.
    """
    for _pass in range(6):
        ring = _bm_boundary_ring(bm)
        if not ring:
            return
        positions = {vertex: index for index, vertex in enumerate(ring)}
        count = len(ring)
        bm.verts.index_update()
        chords = []
        for edge in sorted(
            bm.edges,
            key=lambda edge: min(vertex.index for vertex in edge.verts),
        ):
            if edge.is_boundary:
                continue
            first = positions.get(edge.verts[0])
            second = positions.get(edge.verts[1])
            if first is None or second is None:
                continue
            gap = min(
                (first - second) % count, (second - first) % count
            )
            if 2 <= gap <= 4:
                chords.append(edge)
        if not chords:
            return
        bmesh.ops.dissolve_edges(bm, edges=chords, use_verts=False)
        _split_boundary_ear_quads(bm)


def _boundary_spacing_stats(bm):
    lengths = sorted(
        edge.calc_length() for edge in bm.edges if edge.is_boundary
    )
    if not lengths:
        return 0.0, 0.0, 0.0
    return lengths[0], lengths[len(lengths) // 2], lengths[-1]


def _resample_cut_boundary(surface, settings, source_surface):
    """Uniform arc-length boundary before the rim exists to consume it.

    The Exact intersect scatters boundary vertices wherever cutter quads cross
    surface edges; measured spacing on the reference brace varied 51x
    (0.10-5.10 mm). Because the rim ceiling is 0.35 x local spacing, the
    fillet amplitude then swung 8.6x vertex to vertex, which is the serrated,
    rippled rim. Post-processing the radius field was measured twice to make
    it worse; the spacing itself is the defect, so it is fixed here, upstream
    of everything that reads the boundary.
    """
    spacing = _rim_target_spacing_m(settings)
    bm = bmesh.new()
    bm.from_mesh(surface.data)
    before = _boundary_spacing_stats(bm)
    _collapse_boundary_band_slivers(bm, spacing)
    _split_long_boundary_edges(bm, spacing)
    ring = _bm_boundary_ring(bm)
    if not ring:
        bm.free()
        raise design_ops.TrimRimQualityError(nonmanifold_edges=1)
    anchors = _boundary_corner_anchors(
        ring, spacing * _RIM_CORNER_WINDOW
    )
    _collapse_short_boundary_edges(bm, spacing, anchors)
    ring = _bm_boundary_ring(bm)
    if not ring:
        bm.free()
        raise design_ops.TrimRimQualityError(nonmanifold_edges=1)
    originals = _relax_boundary_spacing(bm, ring, anchors, source_surface)
    _revert_folding_relaxation(bm, originals)
    ring = _bm_boundary_ring(bm)
    if ring:
        cusps = _soften_boundary_cusps(bm, ring, source_surface, spacing)
        _revert_folding_relaxation(bm, cusps)
    _repair_boundary_sliver_crossings(bm, spacing)
    _split_boundary_ear_quads(bm)
    _dissolve_shortcut_chords(bm)
    # A midpoint collapse can leave a vertex exactly on a neighbouring edge -
    # a collinear, zero-area triangle the final validator rejects outright
    # (measured: 1 on the reference brace). One micrometre catches it without
    # perceptibly moving anything.
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1.0e-6)
    _triangulate_boundary_ngons(bm)
    _split_collinear_quad_corners(bm)
    _rotate_zero_area_triangles(bm)
    loose = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    after = _boundary_spacing_stats(bm)
    bm.to_mesh(surface.data)
    bm.free()
    surface.data.update()
    surface["rigo_rim_spacing_target_mm"] = spacing * 1000.0
    surface["rigo_rim_spacing_before_mm"] = [
        value * 1000.0 for value in before
    ]
    surface["rigo_rim_spacing_after_mm"] = [value * 1000.0 for value in after]
    surface["rigo_rim_corner_anchors"] = len(anchors)


def _cut_surface(context, surface, projected, retained_region, settings):
    source_surface = design_ops._source_surface(surface.data)
    cutter = None
    try:
        cutter = _new_cutter(context, surface, projected)
        _intersect_curve_cutter(context, surface, cutter)
    finally:
        if design_ops._object_is_registered(cutter):
            design_ops._remove_object_and_orphan_mesh(cutter)
    _keep_curve_interior(surface, retained_region)
    _weld_exact_cut_tolerance(surface)
    if _boundary_loop_count(surface.data) != 1:
        raise design_ops.TrimRimQualityError(nonmanifold_edges=1)
    _resample_cut_boundary(surface, settings, source_surface)
    if _boundary_loop_count(surface.data) != 1:
        raise design_ops.TrimRimQualityError(nonmanifold_edges=1)
    design_ops._store_full_surface_normals(surface.data, source_surface)


def _boundary_neighbours(boundary):
    neighbours = {}
    for first, second in boundary:
        neighbours.setdefault(first, set()).add(second)
        neighbours.setdefault(second, set()).add(first)
    return neighbours


def _ordered_boundary_ring(boundary):
    """The boundary as one consistently ordered cycle.

    Orientation must come from traversal order, never from iterating a set:
    `previous, following = neighbours` over a Python set assigns the two
    neighbours arbitrarily, which flips the tangent - and therefore the outward
    direction - at unpredictable vertices. Measured 2 such reversals on the
    reference brace (neighbour dot -0.42), each of which is a visible spike.
    """
    linked = _boundary_neighbours(boundary)
    if not linked:
        return []
    start = min(linked)
    ring = [start]
    visited = {start}
    previous, current = None, start
    while True:
        following = [
            neighbour
            for neighbour in sorted(linked[current])
            if neighbour != previous
        ]
        if not following:
            break
        step = following[0]
        if step == start or step in visited:
            break
        ring.append(step)
        visited.add(step)
        previous, current = current, step
    return ring if len(ring) == len(linked) else []


def _stable_outward_directions(coordinates, triangles, boundary, vertex_count):
    """Outward rim frames oriented once for the whole loop.

    Builds the tangent from ring order so its sign is consistent by
    construction, then decides inside/outside ONCE by majority vote against the
    surface interior instead of per vertex. A single ambiguous vertex can then
    no longer invert its own frame.
    """
    ring = _ordered_boundary_ring(boundary)
    if not ring:
        return design_ops._rim_outward_directions(
            coordinates, triangles, boundary, vertex_count
        )
    inner = coordinates[:vertex_count]
    outer = coordinates[vertex_count : vertex_count * 2]
    adjacency = design_ops._vertex_adjacency(vertex_count, triangles)
    count = len(ring)
    frames = {}
    votes = 0.0
    for position, index in enumerate(ring):
        normal = (outer[index] - inner[index]).normalized()
        tangent = inner[ring[(position + 1) % count]] - inner[
            ring[position - 1]
        ]
        tangent -= normal * tangent.dot(normal)
        if tangent.length_squared <= 1.0e-24:
            continue
        tangent.normalize()
        outward = tangent.cross(normal)
        if outward.length_squared <= 1.0e-24:
            continue
        outward.normalize()
        interior = sum(
            (inner[neighbour] - inner[index] for neighbour in adjacency[index]),
            Vector(),
        )
        interior -= normal * interior.dot(normal)
        votes += outward.dot(interior)
        frames[index] = outward
    # One decision for the whole rim: outward must point AWAY from the surface.
    if votes > 0.0:
        for index in frames:
            frames[index] = -frames[index]
    return frames


def _local_turn_radius(coordinates, ring, position):
    count = len(ring)
    previous = coordinates[ring[position - 1]]
    current = coordinates[ring[position]]
    following = coordinates[ring[(position + 1) % count]]
    first = (current - previous).length
    second = (following - current).length
    third = (following - previous).length
    if min(first, second, third) <= 1.0e-12:
        return math.inf
    half = (first + second + third) * 0.5
    area_squared = max(
        half * (half - first) * (half - second) * (half - third), 0.0
    )
    if area_squared <= 1.0e-24:
        return math.inf
    return (first * second * third) / (4.0 * math.sqrt(area_squared))


def _safe_rim_radii(coordinates, boundary, requested):
    """A rim radius that varies SMOOTHLY along the boundary.

    Clamping each vertex only by its own neighbour spacing made the radius track
    the boundary's 51x spacing variation, so the fillet amplitude swung 8.6x
    from vertex to vertex - which is the serrated, rippled rim. The per-vertex
    ceiling still bounds what is geometrically safe (now including local
    curvature), but the delivered radius is then smoothed along the loop as a
    running minimum, so neighbouring profiles differ gradually instead of
    abruptly.
    """
    linked = _boundary_neighbours(boundary)
    ceilings = {}
    for index, neighbours in linked.items():
        spacing = min(
            (coordinates[index] - coordinates[neighbour]).length
            for neighbour in neighbours
        )
        ceilings[index] = min(requested, _RIM_SPACING_RADIUS_CEILING * spacing)
    ring = _ordered_boundary_ring(boundary)
    if not ring:
        return ceilings
    for position, index in enumerate(ring):
        turn = _local_turn_radius(coordinates, ring, position)
        if turn < math.inf:
            ceilings[index] = min(ceilings[index], 0.5 * turn)
    # NOTE: post-processing this radius field cannot fix a serrated rim, and
    # two attempts measurably made it worse (running minimum: median radius
    # 0.138 -> 0.060 mm; clamped averaging: 366 -> 1024 abrupt jumps). The
    # ceiling is 0.35 x local spacing by construction, so radius uniformity is
    # delivered upstream instead, by `_resample_cut_boundary` making the
    # spacing itself uniform before the rim is built.
    return ceilings


def _corner_spike_limits(directions, radii, boundary):
    """Shrink the fillet where the outward frame genuinely turns hard.

    At a pinned clinical corner the adjacent outward directions can differ by
    more than 90 degrees (measured dot -0.42 on the reference brace). The two
    rim quads there fold across each other with the full fillet amplitude,
    which is the vertex spike. The frames are correct - the trimline really
    turns - so the amplitude, not the orientation, is reduced: linearly below
    a neighbour dot of 0.5, to zero at a full reversal.
    """
    ring = _ordered_boundary_ring(boundary)
    count = len(ring)
    for position, index in enumerate(ring):
        current = directions.get(index)
        if current is None or index not in radii:
            continue
        worst = 1.0
        for other in (ring[position - 1], ring[(position + 1) % count]):
            neighbour = directions.get(other)
            if neighbour is not None:
                worst = min(worst, current.dot(neighbour))
        if worst < _RIM_FRAME_DOT_SAFE:
            radii[index] *= max(
                0.0, (1.0 + worst) / (1.0 + _RIM_FRAME_DOT_SAFE)
            )


def _rim_profiles(coordinates, topology, radius):
    directions = _stable_outward_directions(
        coordinates,
        topology.triangles,
        topology.boundary,
        topology.vertex_count,
    )
    radii = _safe_rim_radii(coordinates, topology.boundary, radius)
    _corner_spike_limits(directions, radii, topology.boundary)
    if directions.keys() != radii.keys():
        raise design_ops.TrimRimQualityError(nonmanifold_edges=1)
    profiles = {
        index: _rim_profile(
            coordinates,
            topology,
            _RimVertex(index, directions[index], radii[index]),
        )
        for index in directions
    }
    return profiles, radii


def _cap_chord_budget(segments, has_flat):
    """Split the profile's chords between the two arcs and the closing run.

    The junction dihedral this whole change exists to remove is exactly
    45 degrees / (chords on the arc), so chords are worth far more on the
    arcs than on the closing run - which is straight and needs only one.
    Sampling the cap uniformly by arc length instead spends the budget on
    the flat (3.3 mm against each arc's 0.55 mm on the reference brace),
    leaves one chord per arc, and lands at 45 degrees. The split is kept
    symmetric so the inner and outer transitions match.
    """
    if not has_flat:
        first = segments // 2
        return first, 0, segments - first
    spare = segments - 3
    if spare < 0:
        return 0, segments, 0
    each = spare // 2
    return each + 1, segments - 2 * (each + 1), each + 1


def _cap_offsets(thickness, radius, segments):
    """(depth, bulge) for the profile's interior points, arcs resolved first.

    depth runs along the inner->outer wall normal, bulge along `outward`.
    """
    flat = thickness - 2.0 * radius
    has_flat = flat > 1.0e-9
    first, middle, last = _cap_chord_budget(segments, has_flat)
    quarter = 0.5 * math.pi
    points = []
    for step in range(1, first + 1):
        angle = math.pi - quarter * step / first
        points.append(
            (radius + radius * math.cos(angle), radius * math.sin(angle))
        )
    for step in range(1, middle + 1):
        points.append((radius + flat * step / middle, radius))
    for step in range(1, last + 1):
        angle = quarter * (1.0 - step / last)
        points.append(
            (
                thickness - radius + radius * math.cos(angle),
                radius * math.sin(angle),
            )
        )
    return points[: segments - 1]


def _rim_profile(coordinates, topology, vertex):
    """Tangent bullnose cap: quarter arc, closing run, quarter arc.

    The previous profile placed points at LINEAR fractions across the wall
    with a sin(pi*f) outward bulge - substituting f = u/t that is a sine
    arch, w(u) = r*sin(pi*u/t), whose slope where it meets the wall is
    pi*r/t. It therefore left a crease of atan(t / (pi*r)) against BOTH
    walls at every radius: 74.7 degrees predicted for this fixture's 4.0 mm
    wall and 0.349 mm delivered radius, against 75.2/75.1 measured. Because
    that slope is finite for any finite radius, a sine arch can never be
    tangent - which is why density grading (0.03 degrees), three bevel
    settings and six cut-back arcs all failed to remove the seam.

    Each quarter arc now leaves its wall along +/- `outward`, which
    `_stable_outward_directions` builds as tangent x normal and orients away
    from the mesh interior, so it lies in that wall's tangent plane by
    construction - the cap is tangent at both ends. Outward extent stays
    exactly `radius`, the same envelope the sine arch occupied, though the
    bullnose fills more of it (the flat sits at full radius rather than only
    the apex), so concave overlap is left for the exact validator to judge.
    """
    inner = coordinates[vertex.index]
    outer = coordinates[vertex.index + topology.vertex_count]
    segments = topology.segments
    across = outer - inner
    thickness = across.length
    profile = [vertex.index]
    # 2r > t has no room for two quarter arcs; r = t/2 is the semicircle,
    # which is still exactly tangent and leaves a zero-length closing run.
    radius = min(vertex.radius, 0.5 * thickness)
    if radius <= 1.0e-9 or thickness <= 1.0e-12:
        # No room to round at all: a straight closing run stays watertight
        # and keeps the point count `_rounded_shell_faces` expects.
        for step in range(1, segments):
            profile.append(len(coordinates))
            coordinates.append(inner.lerp(outer, step / segments))
        profile.append(vertex.index + topology.vertex_count)
        return profile
    along = across / thickness
    for depth, bulge in _cap_offsets(thickness, radius, segments):
        profile.append(len(coordinates))
        coordinates.append(inner + along * depth + vertex.outward * bulge)
    profile.append(vertex.index + topology.vertex_count)
    return profile


def _rounded_shell_faces(topology, profiles):
    faces = [
        (face[0], *reversed(face[1:])) for face in topology.surface_faces
    ]
    faces.extend(
        tuple(index + topology.vertex_count for index in face)
        for face in topology.surface_faces
    )
    for first, second in topology.boundary:
        for step in range(topology.segments):
            lower_first = profiles[first][step]
            lower_second = profiles[second][step]
            upper_second = profiles[second][step + 1]
            upper_first = profiles[first][step + 1]
            faces.append(
                (lower_first, lower_second, upper_second, upper_first)
            )
    return faces


def _shell_topology(source, settings):
    source.calc_loop_triangles()
    triangles = tuple(
        tuple(triangle.vertices) for triangle in source.loop_triangles
    )
    return _ShellTopology(
        triangles=triangles,
        surface_faces=tuple(
            tuple(polygon.vertices) for polygon in source.polygons
        ),
        boundary=tuple(design_ops._boundary_edges(triangles)),
        vertex_count=len(source.vertices),
        segments=max(2, int(settings.trim_fillet_segments)),
    )


def _shell_geometry(source, settings, topology):
    thickness = settings.corset_thickness * 0.001
    coordinates, repair = design_ops._paired_coordinates(
        source, topology.triangles, thickness
    )
    requested = settings.trim_fillet_radius * 0.001
    radius = min(requested, thickness * 0.45)
    profiles, radii = _rim_profiles(coordinates, topology, radius)
    faces = _rounded_shell_faces(topology, profiles)
    return coordinates, faces, radii, repair


def _mark_rim_fillet_points(corset, first_index, end_index):
    """Add the rounded rim's intermediate profile points to the rim group.

    Everything from the end of the paired inner/outer block onward was created
    by `_rim_profile`, so the range is exactly the fillet.
    """
    group = corset.vertex_groups.get(design_ops._RIM_BOUNDARY_GROUP)
    if group is None or end_index <= first_index:
        return 0
    indices = list(range(first_index, min(end_index, len(corset.data.vertices))))
    if indices:
        group.add(indices, 1.0, "REPLACE")
    return len(indices)


def _build_strict_shell(corset, settings):
    source = corset.data
    topology = _shell_topology(source, settings)
    coordinates, faces, radii, repair = _shell_geometry(
        source, settings, topology
    )
    design_ops._replace_corset_mesh(corset, coordinates, faces)
    corset["rigo_paired_source_vertices"] = topology.vertex_count
    design_ops._mark_rim_boundary(
        corset, topology.boundary, topology.vertex_count
    )
    # `_mark_rim_boundary` marks only the inner and outer rim rings. The rounded
    # fillet's intermediate profile points sit beyond the paired block and were
    # left unmarked, so manufacturing QA sampled opposing-wall distance ACROSS
    # the fillet and reported ~0.38 mm no matter what wall was requested
    # (measured 0.394/0.382/0.371 mm for 2/4/6 mm, while the true median was the
    # request). That spurious minimum blocked export on every curve-built brace.
    _mark_rim_fillet_points(corset, 2 * topology.vertex_count, len(coordinates))
    # The finishing band cannot be recovered later: this shell is closed, so
    # `trim_ops._edge_band_weights` finds no open boundary and returns nothing.
    # Without the band, Smooth Trim Edge refuses to run and Vents cannot keep
    # clear of the rim. Derive it from the rim marker, as the paired shell is
    # the only moment the rim is still identifiable.
    from .trim_ops import _bake_band_from_vertex_group

    _bake_band_from_vertex_group(
        corset, design_ops._RIM_BOUNDARY_GROUP, settings.edge_band
    )
    _store_shell_properties(corset, settings, topology.boundary, radii)
    _store_outer_repair(corset, repair)


def _store_outer_repair(corset, repair):
    corset["rigo_outer_collision_initial"] = repair.initial_pairs
    corset["rigo_outer_collision_remaining"] = repair.remaining_pairs
    corset["rigo_outer_collision_iterations"] = repair.iterations
    corset["rigo_outer_collision_vertices"] = repair.modified_vertices
    corset["rigo_outer_collision_max_angle_deg"] = (
        repair.max_direction_change_deg
    )


def _store_shell_properties(corset, settings, boundary, radii):
    thickness = float(settings.corset_thickness)
    corset["rigo_pair_min_thickness_mm"] = thickness
    corset["rigo_pair_max_thickness_mm"] = thickness
    corset["rigo_paired_rim_edges"] = len(boundary)
    corset["rigo_rounded_rim_edges"] = len(boundary)
    corset["rigo_trim_fillet_requested_mm"] = float(settings.trim_fillet_radius)
    values = tuple(radii.values())
    corset["rigo_trim_fillet_radius_mm"] = max(values, default=0.0) * 1000.0
    corset["rigo_trim_fillet_min_radius_mm"] = min(values, default=0.0) * 1000.0
    corset["rigo_trim_fillet_mean_radius_mm"] = (
        sum(values) / max(1, len(values)) * 1000.0
    )
    corset["rigo_trim_fillet_segments"] = int(settings.trim_fillet_segments)


def _distance_to_polyline_m(point, samples, nearest_index):
    """Distance to the sampled trimline POLYLINE, not to its samples.

    Nearest-sample distance over-reports by up to half the ~0.6 mm sample
    spacing for a vertex that merely sits BETWEEN samples - exactly what
    boundary resampling produces by sliding vertices along the trimline.
    Projecting onto the two segments around the nearest sample measures the
    real deviation.
    """
    best = (point - samples[nearest_index]).length
    count = len(samples)
    for start in (nearest_index - 1, nearest_index):
        first = samples[start % count]
        second = samples[(start + 1) % count]
        if (second - first).length_squared <= 1.0e-24:
            continue
        location, fraction = intersect_point_line(point, first, second)
        if 0.0 <= fraction <= 1.0:
            best = min(best, (point - location).length)
    return best


def _curve_boundary_errors_mm(surface, projected):
    tree = KDTree(len(projected.coordinates))
    for index, coordinate in enumerate(projected.coordinates):
        tree.insert(coordinate, index)
    tree.balance()
    bm = bmesh.new()
    bm.from_mesh(surface.data)
    errors = sorted(
        _distance_to_polyline_m(
            vertex.co, projected.coordinates, tree.find(vertex.co)[1]
        )
        * 1000.0
        for vertex in bm.verts
        if any(edge.is_boundary for edge in vertex.link_edges)
    )
    bm.free()
    if not errors:
        return math.inf, math.inf
    return errors[-1], errors[int(0.95 * (len(errors) - 1))]


def _new_brace_candidate(context, base):
    stale = bpy.data.objects.get(design_ops._CORSET_CANDIDATE_NAME)
    design_ops._remove_object_and_orphan_mesh(stale)
    corset = base.copy()
    corset.data = base.data.copy()
    corset.name = design_ops._CORSET_CANDIDATE_NAME
    corset.data.name = design_ops._CORSET_CANDIDATE_NAME
    context.scene.collection.objects.link(corset)
    return corset


def _build_curve_corset(context, settings, base, perimeter):
    corset = _new_brace_candidate(context, base)
    complete = False
    try:
        projected = _projected_perimeter(corset, perimeter)
        retained_region = _retained_region(settings, perimeter, projected)
        _cut_surface(context, corset, projected, retained_region, settings)
        maximum, p95 = _curve_boundary_errors_mm(corset, projected)
        _build_strict_shell(corset, settings)
        design_ops._validate_finished_rim(corset)
        corset["rigo_build_method"] = "CURVE_EXACT"
        corset["rigo_trim_curve_max_error_mm"] = maximum
        corset["rigo_trim_curve_p95_error_mm"] = p95
        design_ops._bake_generation_metadata(context, corset, settings)
        complete = True
        return corset
    finally:
        if not complete and design_ops._object_is_registered(corset):
            design_ops._remove_object_and_orphan_mesh(corset)


def _preview_curve(context, perimeter, base):
    design_ops._discard_after_commit(bpy.data.objects.get(_BUILD_CURVE_CANDIDATE))
    preview = perimeter.copy()
    preview.data = perimeter.data.copy()
    preview.name = _BUILD_CURVE_CANDIDATE
    preview.data.name = _BUILD_CURVE_CANDIDATE
    preview.data.bevel_depth = _PREVIEW_BEVEL_M
    preview.modifiers.clear()
    modifier = preview.modifiers.new(name="Follow Offset Mold", type="SHRINKWRAP")
    modifier.target = base
    # ON_SURFACE keeps the offset on the side the point CAME from - the source
    # perimeter sits below the base (body side), so the old preview was held
    # 0.2 mm under the inner wall, buried in the wall material. ABOVE_SURFACE
    # forces the positive-normal side, so the line floats above the outer wall.
    modifier.wrap_method = "NEAREST_SURFACEPOINT"
    modifier.wrap_mode = "ABOVE_SURFACE"
    modifier.offset = (
        context.scene.rigo_brace.corset_thickness * 0.001 + _PREVIEW_CLEARANCE_M
    )
    context.scene.collection.objects.link(preview)
    return preview


def _commit_preview(context, preview):
    design_ops._discard_after_commit(bpy.data.objects.get(BUILD_TRIM_PERIMETER_NAME))
    preview.name = BUILD_TRIM_PERIMETER_NAME
    preview.data.name = BUILD_TRIM_PERIMETER_NAME
    preview.show_in_front = False
    design_ops._set_design_view(context, "BRACE")


class RIGO_OT_generate_curve_corset(Operator):
    """Build one deterministic shell from the offset-mold trim curve."""

    bl_idname = "rigo.generate_curve_corset"
    bl_label = "Generate Curve Brace"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scan = design_ops._scan(context)
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        if scan is None or perimeter is None:
            self.report({"ERROR"}, "Prepare a scan and one trim perimeter first")
            return {"CANCELLED"}
        if not design_ops._perimeter_belongs_to_scan(perimeter, scan):
            self.report({"ERROR"}, "Recreate the trimline for the current scan")
            return {"CANCELLED"}
        if scan.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        from .deform_ops import DEFORM_MODIFIER

        if scan.modifiers.get(DEFORM_MODIFIER) is not None:
            self.report(
                {"ERROR"},
                "Apply or Reset the active Bend/Twist/Stretch before generating",
            )
            return {"CANCELLED"}
        if context.scene.rigo_brace.scan_object is None:
            context.scene.rigo_brace.scan_object = scan
        return self._build(context, scan, perimeter)

    def _build(self, context, scan, perimeter):
        settings = context.scene.rigo_brace
        snapshot = design_ops._capture_generation_snapshot(settings)
        candidates = design_ops._GenerationCandidates()
        preview = None
        try:
            candidates.base = design_ops._prepare_candidate_base(context, scan, settings)
            preview = _preview_curve(context, perimeter, candidates.base)
            candidates.brace = _build_curve_corset(
                context, settings, candidates.base, perimeter
            )
            design_ops._commit_generation(context, snapshot, candidates, settings)
        except (
            CustomTrimMaskError,
            design_ops.OuterWallIntersectionError,
            design_ops.TrimRimQualityError,
            design_ops.TrimPerimeterWindingError,
        ) as error:
            design_ops._restore_failed_generation(context, snapshot, candidates)
            design_ops._remove_object_and_orphan_mesh(preview)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        except Exception:
            design_ops._restore_failed_generation(context, snapshot, candidates)
            design_ops._remove_object_and_orphan_mesh(preview)
            raise
        try:
            _commit_preview(context, preview)
        except Exception:
            design_ops._remove_object_and_orphan_mesh(preview)
            self.report(
                {"WARNING"},
                "Brace generated, but the offset trimline preview could not be shown",
            )
        self.report({"INFO"}, "Curve-first brace generated from the offset mold")
        return {"FINISHED"}


_CLASSES = (RIGO_OT_generate_curve_corset,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
