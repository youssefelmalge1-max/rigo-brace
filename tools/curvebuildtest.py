"""Installed-copy regression for the experimental curve-first brace build."""

import hashlib
import sys
import traceback

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402


OUT = r"C:\Projects\Blender Add-on Braces\curvebuildtest_result.txt"
TRIES = {"count": 0}


def _topology(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
    bm.free()
    return boundary, nonmanifold


def _component_count(obj):
    neighbours = {vertex.index: set() for vertex in obj.data.vertices}
    for edge in obj.data.edges:
        first, second = edge.vertices
        neighbours[first].add(second)
        neighbours[second].add(first)
    remaining = set(neighbours)
    components = 0
    while remaining:
        components += 1
        pending = [remaining.pop()]
        while pending:
            linked = neighbours[pending.pop()] & remaining
            remaining.difference_update(linked)
            pending.extend(linked)
    return components


def _mesh_signature(obj):
    rows = sorted(
        tuple(round(component, 8) for component in vertex.co)
        for vertex in obj.data.vertices
    )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _offset_distances(scan, base):
    bvh = BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())
    inverse = scan.matrix_world.inverted()
    distances = []
    step = max(1, len(base.data.vertices) // 1000)
    for index in range(0, len(base.data.vertices), step):
        vertex = base.data.vertices[index]
        world = base.matrix_world @ vertex.co
        hit = bvh.find_nearest(inverse @ world)
        if hit[0] is not None:
            distances.append((world - scan.matrix_world @ hit[0]).length * 1000.0)
    distances.sort()
    return distances[len(distances) // 2], max(distances)


def _preview_clearance(preview, base):
    """Median distance from the preview polyline to the offset mold, in mm."""
    if preview is None or base is None or not preview.data.splines:
        return None
    bvh = BVHTree.FromObject(base, bpy.context.evaluated_depsgraph_get())
    inverse = base.matrix_world.inverted()
    distances = []
    for point in preview.data.splines[0].points:
        world = preview.matrix_world @ point.co.to_3d()
        hit = bvh.find_nearest(inverse @ world)
        if hit[0] is not None:
            distances.append((world - base.matrix_world @ hit[0]).length * 1000.0)
    if not distances:
        return None
    distances.sort()
    return distances[len(distances) // 2]


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "generate_curve_corset") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.corset_smooth = 5
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8
        first_result = bpy.ops.rigo.generate_curve_corset()
        brace = bpy.data.objects.get("Rigo Corset")
        base = bpy.data.objects.get("Rigo Corset Base")
        preview = bpy.data.objects.get("Rigo Build Trim Perimeter")
        boundary, nonmanifold = _topology(brace)
        components = _component_count(brace)
        median_offset, maximum_offset = _offset_distances(scan, base)
        first_signature = _mesh_signature(brace)
        first_error = float(brace.get("rigo_trim_curve_max_error_mm", 999.0))
        p95_error = float(brace.get("rigo_trim_curve_p95_error_mm", 999.0))
        # The preview used to be a COPY of the source perimeter carrying its own
        # Shrinkwrap, so this asserted "it has a modifier aimed at the base" -
        # a check on the mechanism, which said nothing about whether the drawn
        # line matched the cut. The preview is now built directly from the
        # cutter's projected samples, so the honest assertion is that it holds
        # that path: a modifier-free polyline sitting one wall thickness plus a
        # clearance outside the base, i.e. just off the outer wall.
        preview_gap = _preview_clearance(preview, base)
        expected_gap = settings.corset_thickness + 1.5
        target_ok = bool(
            preview
            and not preview.modifiers
            and preview.data.splines
            and preview.data.splines[0].type == "POLY"
            and preview_gap is not None
            and abs(preview_gap - expected_gap) <= 1.0
        )
        first_ok = all(
            (
                first_result == {"FINISHED"},
                brace is not None,
                brace.get("rigo_build_method") == "CURVE_EXACT",
                boundary == 0,
                nonmanifold == 0,
                components == 1,
                abs(float(brace["rigo_pair_min_thickness_mm"]) - 4.0) < 1.0e-6,
                abs(float(brace["rigo_pair_max_thickness_mm"]) - 4.0) < 1.0e-6,
                first_error <= 5.0,
                p95_error <= 0.75,
                2.0 <= median_offset <= 4.0,
                target_ok,
            )
        )
        lines.append(
            f"first={first_result} boundary={boundary} nonmanifold={nonmanifold} "
            f"components={components} trim_max_mm={first_error:.4f} "
            f"trim_p95_mm={p95_error:.4f} "
            f"offset_median_mm={median_offset:.4f} offset_max_mm={maximum_offset:.4f} "
            f"preview_from_cut_path={target_ok} "
            f"preview_gap_mm={preview_gap if preview_gap is None else round(preview_gap, 3)} "
            f"ok={first_ok}"
        )

        second_result = bpy.ops.rigo.generate_curve_corset()
        second = bpy.data.objects.get("Rigo Corset")
        deterministic = _mesh_signature(second) == first_signature
        second_ok = second_result == {"FINISHED"} and deterministic
        lines.append(
            f"second={second_result} deterministic={deterministic} ok={second_ok}"
        )
        lines.append(f"PASS={first_ok and second_ok}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
