"""Stable geometry fingerprints for detecting stale generated braces."""

import hashlib
import struct


_SOURCE_SIGNATURE_KEYS = (
    "rigo_source_scan_signature",
    "rigo_source_trim_signature",
)


def brace_has_source_record(brace):
    """Return whether a brace records both geometry sources used to build it."""
    return brace is not None and all(
        bool(str(brace.get(key, ""))) for key in _SOURCE_SIGNATURE_KEYS
    )


def _pack_number(digest, value):
    digest.update(struct.pack("<q", round(float(value) * 1.0e9)))


def _pack_matrix(digest, matrix):
    for row in matrix:
        for value in row:
            _pack_number(digest, value)


def _mesh_signature(digest, evaluated, depsgraph):
    mesh = evaluated.to_mesh(
        preserve_all_data_layers=False, depsgraph=depsgraph
    )
    try:
        mesh.calc_loop_triangles()
        digest.update(struct.pack("<II", len(mesh.vertices), len(mesh.loop_triangles)))
        for vertex in mesh.vertices:
            for value in vertex.co:
                _pack_number(digest, value)
        for triangle in mesh.loop_triangles:
            digest.update(struct.pack("<3I", *triangle.vertices))
    finally:
        evaluated.to_mesh_clear()


def _curve_signature(digest, evaluated):
    splines = evaluated.data.splines
    digest.update(struct.pack("<I", len(splines)))
    for spline in splines:
        digest.update(spline.type.encode("ascii"))
        digest.update(struct.pack("<?", bool(spline.use_cyclic_u)))
        if spline.type == "BEZIER":
            digest.update(struct.pack("<I", len(spline.bezier_points)))
            for point in spline.bezier_points:
                for coordinate in (point.co, point.handle_left, point.handle_right):
                    for value in coordinate:
                        _pack_number(digest, value)
        else:
            digest.update(struct.pack("<I", len(spline.points)))
            for point in spline.points:
                for value in point.co:
                    _pack_number(digest, value)


def geometry_signature(context, obj):
    """Hash evaluated geometry and world placement, excluding display state."""
    if obj is None:
        return ""
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    digest = hashlib.sha256()
    digest.update(obj.type.encode("ascii"))
    _pack_matrix(digest, evaluated.matrix_world)
    if obj.type == "MESH":
        _mesh_signature(digest, evaluated, depsgraph)
    elif obj.type == "CURVE":
        _curve_signature(digest, evaluated)
    else:
        digest.update(obj.name_full.encode("utf-8"))
    return digest.hexdigest()
