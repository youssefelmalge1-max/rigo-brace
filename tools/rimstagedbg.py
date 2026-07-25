"""Which resampling phase makes the cut surface self-intersect?

Replays `_resample_cut_boundary` phase by phase on the reference fixture and,
after each phase, reports:
  - self-intersecting triangle pairs of the (un-offset) cut surface,
  - the minimum distance between NON-neighbouring boundary vertices
    (a narrow retained tongue shows up here before anything moves).
"""

import sys
import traceback

import bmesh
import bpy
from mathutils.kdtree import KDTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\rimstagedbg_result.txt"
TRIES = {"n": 0}
LINES = []


def _stage_report(bm, label):
    invalid = [
        v
        for v in bm.verts
        if sum(e.is_boundary for e in v.link_edges) not in (0, 2)
    ]
    if invalid:
        for vertex in invalid[:4]:
            LINES.append(
                f"          INVALID valence vert at "
                f"({vertex.co.x:.4f},{vertex.co.y:.4f},{vertex.co.z:.4f}) "
                f"boundary_edges="
                f"{sum(e.is_boundary for e in vertex.link_edges)}"
            )
    coordinates = [tuple(v.co) for v in bm.verts]
    bm.verts.index_update()
    triangles = []
    for face in bm.faces:
        verts = [v.index for v in face.verts]
        for i in range(1, len(verts) - 1):
            triangles.append((verts[0], verts[i], verts[i + 1]))
    pairs = design_ops.triangle_intersection_pairs(coordinates, triangles)

    ring = curve_build_ops._bm_boundary_ring(bm)
    closest = None
    if ring:
        tree = KDTree(len(ring))
        for index, vertex in enumerate(ring):
            tree.insert(vertex.co, index)
        tree.balance()
        count = len(ring)
        for index, vertex in enumerate(ring):
            for _co, other, distance in tree.find_n(vertex.co, 6):
                if other == index:
                    continue
                gap = min(
                    (other - index) % count, (index - other) % count
                )
                if gap <= 2:
                    continue
                if closest is None or distance < closest[0]:
                    closest = (distance, index, other)
                break
    LINES.append(
        f"{label:9s} verts={len(coordinates)} "
        f"invalid_valence={len(invalid)} self_pairs={len(pairs)} "
        + (
            f"min_nonneighbour_boundary_mm={closest[0]*1000:.4f} "
            f"(ring {closest[1]}<->{closest[2]} of {len(ring)})"
            if closest
            else "no ring"
        )
    )
    if pairs:
        sample = list(pairs)[:3]
        for first, second in sample:
            centre = [
                sum(coordinates[i][axis] for i in triangles[first]) / 3.0
                for axis in range(3)
            ]
            LINES.append(
                f"          pair tris {first},{second} "
                f"centre=({centre[0]:.4f},{centre[1]:.4f},{centre[2]:.4f})"
            )


def _instrumented(surface, settings, source_surface):
    spacing = curve_build_ops._rim_target_spacing_m(settings)
    LINES.append(f"target_spacing_mm={spacing*1000:.3f}")
    bm = bmesh.new()
    bm.from_mesh(surface.data)
    _stage_report(bm, "pre")
    curve_build_ops._collapse_boundary_band_slivers(bm, spacing)
    _stage_report(bm, "desliver")
    curve_build_ops._split_long_boundary_edges(bm, spacing)
    _stage_report(bm, "split")
    ring = curve_build_ops._bm_boundary_ring(bm)
    anchors = curve_build_ops._boundary_corner_anchors(
        ring, spacing * curve_build_ops._RIM_CORNER_WINDOW
    )
    LINES.append(f"anchors={len(anchors)}")
    curve_build_ops._collapse_short_boundary_edges(bm, spacing, anchors)
    _stage_report(bm, "collapse")
    ring = curve_build_ops._bm_boundary_ring(bm)
    originals = curve_build_ops._relax_boundary_spacing(
        bm, ring, anchors, source_surface
    )
    _stage_report(bm, "relax")
    curve_build_ops._revert_folding_relaxation(bm, originals)
    _stage_report(bm, "revert")
    curve_build_ops._repair_boundary_sliver_crossings(bm, spacing)
    _stage_report(bm, "repair")
    curve_build_ops._split_boundary_ear_quads(bm)
    _report_ears(bm, "post-earsplit")
    curve_build_ops._dissolve_shortcut_chords(bm)
    _report_ears(bm, "post-chords")
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1.0e-6)
    _report_ears(bm, "post-dissolve")
    curve_build_ops._triangulate_boundary_ngons(bm)
    _report_ears(bm, "post-ngons")
    curve_build_ops._split_collinear_quad_corners(bm)
    curve_build_ops._rotate_zero_area_triangles(bm)
    _report_ears(bm, "final")
    bm.free()
    raise RuntimeError("rimstagedbg: measurement complete")


def _report_ears(bm, label):
    """Triangulate exactly as the validator will and find shortcut
    triangles: two boundary verts at ring gap >= 2 in one emitted triangle."""
    invalid = [
        v
        for v in bm.verts
        if sum(e.is_boundary for e in v.link_edges) not in (0, 2)
    ]
    LINES.append(f"{label}: invalid_valence={len(invalid)}")
    for vertex in invalid[:4]:
        LINES.append(
            f"  {label}: INVALID vert at ({vertex.co.x:.4f},"
            f"{vertex.co.y:.4f},{vertex.co.z:.4f}) boundary_edges="
            f"{sum(e.is_boundary for e in vertex.link_edges)}"
        )
    ring = curve_build_ops._bm_boundary_ring(bm)
    positions = {vertex.index: pos for pos, vertex in enumerate(ring)}
    count = max(1, len(ring))
    mesh = bpy.data.meshes.new(f"rimstagedbg-{label}")
    bm.verts.index_update()
    bm.to_mesh(mesh)
    mesh.calc_loop_triangles()
    found = 0
    for triangle in mesh.loop_triangles:
        indices = list(triangle.vertices)
        worst = 0
        for a in range(3):
            pa = positions.get(indices[a])
            pb = positions.get(indices[(a + 1) % 3])
            if pa is not None and pb is not None:
                gap = min((pa - pb) % count, (pb - pa) % count)
                worst = max(worst, gap)
        if worst >= 2:
            found += 1
            if found <= 8:
                polygon = mesh.polygons[triangle.polygon_index]
                corner_roles = ",".join(
                    (
                        f"B{positions[i]}"
                        if i in positions
                        else "int"
                    )
                    for i in polygon.vertices
                )
                LINES.append(
                    f"  {label}: shortcut tri={tuple(indices)} gap={worst} "
                    f"poly_size={len(polygon.vertices)} "
                    f"poly=({corner_roles})"
                )
    LINES.append(f"{label}: shortcut_triangles={found}")
    bpy.data.meshes.remove(mesh)


def _report_collinear(bm, label):
    found = 0
    for face in bm.faces:
        corners = list(face.verts)
        count = len(corners)
        for position in range(count):
            previous = corners[position - 1].co
            middle = corners[position].co
            following = corners[(position + 1) % count].co
            cross = (middle - previous).cross(following - previous)
            if 0.5 * cross.length <= 1.0e-11:
                found += 1
                if found <= 6:
                    LINES.append(
                        f"  {label}: face_size={count} "
                        f"area={face.calc_area():.3e} "
                        f"corner=({middle.x:.4f},{middle.y:.4f},{middle.z:.4f}) "
                        f"triple_area={0.5*cross.length:.3e}"
                    )
                break
    LINES.append(f"{label}: collinear_corner_faces={found}")


def _repair_verbose(bm):
    """The installed repair pass, with each collapse target logged."""
    design = design_ops
    for pass_index in range(curve_build_ops._RIM_CROSSING_REPAIR_PASSES):
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
        pairs = design.triangle_intersection_pairs(coordinates, triangles)
        LINES.append(f"repair pass {pass_index}: pairs={len(pairs)}")
        if not pairs:
            return
        ring = curve_build_ops._bm_boundary_ring(bm)
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
                    first_ring = positions.get(start)
                    second_ring = positions.get(end)
                    kind = (
                        f"{'B' if first_ring is not None else 'I'}"
                        f"{'B' if second_ring is not None else 'I'}"
                    )
                    if first_ring is not None and second_ring is not None:
                        gap = min(
                            (first_ring - second_ring) % count,
                            (second_ring - first_ring) % count,
                        )
                        if gap != 1:
                            continue
                        kind += f"gap{gap}"
                    centre = (start.co + end.co) * 0.5
                    LINES.append(
                        f"  collapse {kind} len_mm="
                        f"{edge.calc_length()*1000:.4f} at "
                        f"({centre.x:.4f},{centre.y:.4f},{centre.z:.4f}) "
                        f"edge_is_boundary={edge.is_boundary}"
                    )
                    targets.append(edge)
                    used.update((start, end))
                    break
        if not targets:
            return
        bmesh.ops.collapse(bm, edges=targets)


def _sharpen_trimline(mode):
    """Mirror of rimresampletest's hostile fixture, separable by mode:
    'notch', 'crowd', or '1' for both."""
    perimeter = bpy.data.objects["Rigo Trim Perimeter"]
    points = perimeter.data.splines[0].bezier_points
    count = len(points)
    if mode in ("1", "notch"):
        notch = count // 3
        for offset in (-1, 0, 1):
            point = points[(notch + offset) % count]
            point.handle_left_type = "AUTO"
            point.handle_right_type = "AUTO"
        points[notch].co.z -= 0.03
    if mode in ("1", "crowd"):
        crowd = (2 * count) // 3
        anchor = points[crowd].co.copy()
        for offset in (1, 2):
            point = points[(crowd + offset) % count]
            direction = point.co - anchor
            if direction.length > 1e-9:
                point.co = anchor + direction.normalized() * (0.005 * offset)
            point.handle_left_type = "AUTO"
            point.handle_right_type = "AUTO"
    perimeter.data.update_tag()


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.ops.rigo, "generate_curve_corset") and TRIES["n"] < 30:
        return 0.1
    try:
        curve_build_ops._resample_cut_boundary = _instrumented
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8
        mode = __import__("os").environ.get("RIGO_DBG_SHARPEN")
        if mode:
            _sharpen_trimline(mode)
            LINES.append(f"fixture=SHARPENED mode={mode}")
        try:
            generated = bpy.ops.rigo.generate_curve_corset()
            LINES.append(f"generate={generated}")
        except RuntimeError as exc:
            LINES.append(f"generate=CANCELLED error={str(exc).strip()!r}")
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
