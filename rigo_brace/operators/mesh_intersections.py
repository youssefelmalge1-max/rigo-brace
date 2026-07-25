"""Exact triangle-intersection checks shared by shell generation and QA.

``BVHTree.overlap`` is only used as a broad phase.  Its axis-aligned bounding
boxes can overlap when the triangles themselves do not, so every candidate is
confirmed geometrically before it is reported or used to alter the shell.
"""

from mathutils import Vector
from mathutils.bvhtree import BVHTree


_INTERSECTION_EPSILON_M = 1.0e-7
_BARYCENTRIC_EPSILON = 1.0e-7


def _project_2d(point, dropped_axis):
    return tuple(point[index] for index in range(3) if index != dropped_axis)


def _orient_2d(first, second, third):
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _orientation_tolerance(first, second, third, epsilon):
    first_length = (
        (second[0] - first[0]) ** 2 + (second[1] - first[1]) ** 2
    ) ** 0.5
    second_length = (
        (third[0] - first[0]) ** 2 + (third[1] - first[1]) ** 2
    ) ** 0.5
    return epsilon * max(first_length, second_length, epsilon)


def _point_on_segment_2d(point, first, second, epsilon):
    if abs(_orient_2d(first, second, point)) > _orientation_tolerance(
        first, second, point, epsilon
    ):
        return False
    return (
        min(first[0], second[0]) - epsilon
        <= point[0]
        <= max(first[0], second[0]) + epsilon
        and min(first[1], second[1]) - epsilon
        <= point[1]
        <= max(first[1], second[1]) + epsilon
    )


def _segments_intersect_2d(first_a, first_b, second_a, second_b, epsilon):
    orientations = (
        _orient_2d(first_a, first_b, second_a),
        _orient_2d(first_a, first_b, second_b),
        _orient_2d(second_a, second_b, first_a),
        _orient_2d(second_a, second_b, first_b),
    )
    tolerances = (
        _orientation_tolerance(first_a, first_b, second_a, epsilon),
        _orientation_tolerance(first_a, first_b, second_b, epsilon),
        _orientation_tolerance(second_a, second_b, first_a, epsilon),
        _orientation_tolerance(second_a, second_b, first_b, epsilon),
    )
    signs = tuple(
        0 if abs(value) <= tolerance else (1 if value > 0.0 else -1)
        for value, tolerance in zip(orientations, tolerances)
    )
    if signs[0] * signs[1] < 0 and signs[2] * signs[3] < 0:
        return True
    candidates = (
        (signs[0], second_a, first_a, first_b),
        (signs[1], second_b, first_a, first_b),
        (signs[2], first_a, second_a, second_b),
        (signs[3], first_b, second_a, second_b),
    )
    return any(
        sign == 0 and _point_on_segment_2d(point, start, end, epsilon)
        for sign, point, start, end in candidates
    )


def _point_in_triangle_2d(point, triangle, epsilon):
    orientations = [
        _orient_2d(triangle[index], triangle[(index + 1) % 3], point)
        for index in range(3)
    ]
    tolerances = [
        _orientation_tolerance(
            triangle[index], triangle[(index + 1) % 3], point, epsilon
        )
        for index in range(3)
    ]
    has_positive = any(
        value > tolerance for value, tolerance in zip(orientations, tolerances)
    )
    has_negative = any(
        value < -tolerance for value, tolerance in zip(orientations, tolerances)
    )
    return not (has_positive and has_negative)


def _coplanar_triangles_intersect(first, second, normal, epsilon):
    dropped_axis = max(range(3), key=lambda index: abs(normal[index]))
    first_2d = [_project_2d(point, dropped_axis) for point in first]
    second_2d = [_project_2d(point, dropped_axis) for point in second]
    for first_index in range(3):
        first_a = first_2d[first_index]
        first_b = first_2d[(first_index + 1) % 3]
        for second_index in range(3):
            if _segments_intersect_2d(
                first_a,
                first_b,
                second_2d[second_index],
                second_2d[(second_index + 1) % 3],
                epsilon,
            ):
                return True
    return _point_in_triangle_2d(first_2d[0], second_2d, epsilon) or (
        _point_in_triangle_2d(second_2d[0], first_2d, epsilon)
    )


def _point_in_triangle_3d(point, triangle):
    first_edge = triangle[1] - triangle[0]
    second_edge = triangle[2] - triangle[0]
    relative = point - triangle[0]
    first_dot = first_edge.dot(first_edge)
    cross_dot = first_edge.dot(second_edge)
    second_dot = second_edge.dot(second_edge)
    first_relative = relative.dot(first_edge)
    second_relative = relative.dot(second_edge)
    denominator = first_dot * second_dot - cross_dot * cross_dot
    if abs(denominator) <= 1.0e-20:
        return False
    second_weight = (
        second_dot * first_relative - cross_dot * second_relative
    ) / denominator
    third_weight = (
        first_dot * second_relative - cross_dot * first_relative
    ) / denominator
    return (
        second_weight >= -_BARYCENTRIC_EPSILON
        and third_weight >= -_BARYCENTRIC_EPSILON
        and second_weight + third_weight <= 1.0 + _BARYCENTRIC_EPSILON
    )


def _segment_intersects_triangle(first, second, triangle, normal, epsilon):
    first_distance = normal.dot(first - triangle[0])
    second_distance = normal.dot(second - triangle[0])
    if first_distance > epsilon and second_distance > epsilon:
        return False
    if first_distance < -epsilon and second_distance < -epsilon:
        return False
    if abs(first_distance) <= epsilon and _point_in_triangle_3d(first, triangle):
        return True
    if abs(second_distance) <= epsilon and _point_in_triangle_3d(second, triangle):
        return True
    denominator = first_distance - second_distance
    if abs(denominator) <= 1.0e-15:
        return False
    parameter = first_distance / denominator
    segment_length = (second - first).length
    parameter_epsilon = epsilon / max(segment_length, epsilon)
    if parameter < -parameter_epsilon or parameter > 1.0 + parameter_epsilon:
        return False
    intersection = first.lerp(second, parameter)
    return _point_in_triangle_3d(intersection, triangle)


def triangles_intersect(first, second, epsilon=_INTERSECTION_EPSILON_M):
    """Return whether two non-topological triangles touch or cross."""
    first = tuple(Vector(point) for point in first)
    second = tuple(Vector(point) for point in second)
    first_cross = (first[1] - first[0]).cross(first[2] - first[0])
    second_cross = (second[1] - second[0]).cross(second[2] - second[0])
    if first_cross.length_squared <= 1.0e-24:
        return False
    if second_cross.length_squared <= 1.0e-24:
        return False
    first_normal = first_cross.normalized()
    second_normal = second_cross.normalized()
    second_distances = [first_normal.dot(point - first[0]) for point in second]
    first_distances = [second_normal.dot(point - second[0]) for point in first]
    if all(distance > epsilon for distance in second_distances) or all(
        distance < -epsilon for distance in second_distances
    ):
        return False
    if all(distance > epsilon for distance in first_distances) or all(
        distance < -epsilon for distance in first_distances
    ):
        return False
    if all(abs(distance) <= epsilon for distance in second_distances) and all(
        abs(distance) <= epsilon for distance in first_distances
    ):
        return _coplanar_triangles_intersect(
            first, second, first_normal, epsilon
        )
    for triangle, normal, edges in (
        (second, second_normal, first),
        (first, first_normal, second),
    ):
        for index in range(3):
            if _segment_intersects_triangle(
                edges[index], edges[(index + 1) % 3], triangle, normal, epsilon
            ):
                return True
    return False


def _triangle_without_shared_contact(vertices, triangle, shared_indices, epsilon):
    """Move only shared vertices inward so expected mesh adjacency is excluded."""
    coordinates = [Vector(vertices[index]) for index in triangle]
    centroid = sum(coordinates, Vector()) / 3.0
    edge_scale = max(
        (coordinates[index] - coordinates[(index + 1) % 3]).length
        for index in range(3)
    )
    nudge_distance = max(epsilon * 8.0, edge_scale * 1.0e-8)
    for index, vertex_index in enumerate(triangle):
        if vertex_index not in shared_indices:
            continue
        toward_centroid = centroid - coordinates[index]
        if toward_centroid.length <= 1.0e-20:
            continue
        fraction = min(0.01, nudge_distance / toward_centroid.length)
        coordinates[index] = coordinates[index].lerp(centroid, fraction)
    return coordinates


def triangle_intersection_pairs(vertices, triangles, bvh=None):
    """Return exact intersections after BVH broad-phase candidate filtering."""
    if not vertices or not triangles:
        return []
    tree = bvh or BVHTree.FromPolygons(
        vertices, triangles, all_triangles=True, epsilon=0.0
    )
    triangle_vertices = [set(triangle) for triangle in triangles]
    tested = set()
    intersections = []
    for first_index, second_index in tree.overlap(tree):
        if first_index == second_index:
            continue
        pair = tuple(sorted((first_index, second_index)))
        if pair in tested:
            continue
        tested.add(pair)
        shared_indices = triangle_vertices[pair[0]].intersection(
            triangle_vertices[pair[1]]
        )
        first = _triangle_without_shared_contact(
            vertices, triangles[pair[0]], shared_indices, _INTERSECTION_EPSILON_M
        )
        second = _triangle_without_shared_contact(
            vertices, triangles[pair[1]], shared_indices, _INTERSECTION_EPSILON_M
        )
        if triangles_intersect(first, second):
            intersections.append(pair)
    return sorted(intersections)
