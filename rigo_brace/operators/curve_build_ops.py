"""Curve-first brace construction from one immutable trim perimeter."""

import math
from dataclasses import dataclass

import bmesh
import bpy
from bpy.types import Operator
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import interpolate_bezier
from mathutils.kdtree import KDTree

from ..core import (
    BUILD_TRIM_PERIMETER_NAME,
)
from . import design_ops
from .custom_trim_ops import CustomTrimMaskError, _mask_values

_BUILD_CURVE_CANDIDATE = "Rigo Build Trim Perimeter Candidate"
_CUTTER_TAG_ATTRIBUTE = "rigo_curve_cutter_face"
_CUTTER_HALF_DEPTH_M = 0.0015
_EXACT_CUT_WELD_M = 0.000005
_RIM_MIN_EDGE_M = 0.0001
_CUT_SLIVER_AREA_M2 = 5.0e-9


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


def _projected_samples(base, perimeter):
    inverse, bvh, source_surface = _projection_target(base)
    coordinates = []
    normals = []
    for world_coordinate in _curve_world_samples(perimeter):
        hit = bvh.find_nearest(inverse @ world_coordinate)
        if hit[0] is None:
            raise RuntimeError(
                "The trimline could not be projected onto the offset mold"
            )
        coordinates.append(hit[0].copy())
        normals.append(design_ops._surface_normal_at(source_surface, hit[0]))
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


def _cut_surface(context, surface, projected, retained_region):
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
        ceilings[index] = min(requested, 0.35 * spacing)
    ring = _ordered_boundary_ring(boundary)
    if not ring:
        return ceilings
    for position, index in enumerate(ring):
        turn = _local_turn_radius(coordinates, ring, position)
        if turn < math.inf:
            ceilings[index] = min(ceilings[index], 0.5 * turn)
    # NOTE: post-processing this radius field cannot fix the serrated rim, and
    # two attempts measurably made it worse. A running minimum over the
    # neighbourhood smoothed the field but dragged the median radius 0.138 ->
    # 0.060 mm, sharpening the very edge the fillet exists to round. Clamped
    # averaging kept the size (0.124 mm) but pushed abrupt neighbour-to-
    # neighbour changes UP (366 -> 1024 jumps over 25 %), because each vertex's
    # ceiling still tracks the boundary's 51x spacing variation.
    # The ceiling is 0.35 x local spacing by construction, so while the cut
    # boundary is non-uniform the fillet must be non-uniform too. The fix
    # belongs upstream - resample the boundary uniformly by arc length before
    # the rim is built - not here.
    return ceilings


def _rim_profiles(coordinates, topology, radius):
    directions = _stable_outward_directions(
        coordinates,
        topology.triangles,
        topology.boundary,
        topology.vertex_count,
    )
    radii = _safe_rim_radii(coordinates, topology.boundary, radius)
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


def _rim_profile(coordinates, topology, vertex):
    inner = coordinates[vertex.index]
    outer = coordinates[vertex.index + topology.vertex_count]
    profile = [vertex.index]
    for step in range(1, topology.segments):
        fraction = step / topology.segments
        profile.append(len(coordinates))
        center = inner.lerp(outer, fraction)
        coordinates.append(
            center
            + vertex.outward * vertex.radius * math.sin(math.pi * fraction)
        )
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


def _curve_boundary_errors_mm(surface, projected):
    tree = KDTree(len(projected.coordinates))
    for index, coordinate in enumerate(projected.coordinates):
        tree.insert(coordinate, index)
    tree.balance()
    bm = bmesh.new()
    bm.from_mesh(surface.data)
    errors = sorted(
        tree.find(vertex.co)[2] * 1000.0
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
        _cut_surface(context, corset, projected, retained_region)
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
    preview.modifiers.clear()
    modifier = preview.modifiers.new(name="Follow Offset Mold", type="SHRINKWRAP")
    modifier.target = base
    modifier.wrap_method = "TARGET_PROJECT"
    modifier.wrap_mode = "ON_SURFACE"
    modifier.offset = 0.0002
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
