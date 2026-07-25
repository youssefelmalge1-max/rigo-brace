"""Installed-copy regression proving the trim fillet changes safe geometry."""

import sys

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402


OUT = r"C:\Projects\Blender Add-on Braces\rimfilletest_result.txt"


def _mesh_state(brace):
    brace.data.calc_loop_triangles()
    bm = bmesh.new()
    bm.from_mesh(brace.data)
    try:
        boundary = sum(edge.is_boundary for edge in bm.edges)
        nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
        zero_faces = sum(face.calc_area() <= 1.0e-12 for face in bm.faces)
    finally:
        bm.free()
    return {
        "coordinates": [vertex.co.copy() for vertex in brace.data.vertices],
        "triangles": [
            tuple(triangle.vertices) for triangle in brace.data.loop_triangles
        ],
        "vertices": len(brace.data.vertices),
        "faces": len(brace.data.polygons),
        "boundary": boundary,
        "nonmanifold": nonmanifold,
        "zero_faces": zero_faces,
        "requested": float(brace.get("rigo_trim_fillet_requested_mm", -1.0)),
        "effective": float(brace.get("rigo_trim_fillet_radius_mm", -1.0)),
        "minimum": float(brace.get("rigo_trim_fillet_min_radius_mm", -1.0)),
        "mean": float(brace.get("rigo_trim_fillet_mean_radius_mm", -1.0)),
        "segments": int(brace.get("rigo_trim_fillet_segments", 0)),
    }


def _generate(settings, radius):
    settings.trim_fillet_radius = radius
    settings.trim_fillet_segments = 8
    result = bpy.ops.rigo.generate_corset()
    brace = bpy.data.objects.get("Rigo Corset")
    if result != {"FINISHED"} or brace is None:
        raise RuntimeError(f"brace generation failed at radius {radius}: {result}")
    return _mesh_state(brace)


def _run():
    lines = []
    passed = False
    try:
        _scan, settings = prepare_reference_design()
        small = _generate(settings, 0.2)
        large = _generate(settings, 1.0)
        same_topology = (
            small["vertices"] == large["vertices"]
            and small["faces"] == large["faces"]
        )
        movements = []
        if same_topology:
            small_tree = BVHTree.FromPolygons(
                small["coordinates"], small["triangles"], all_triangles=True
            )
            large_tree = BVHTree.FromPolygons(
                large["coordinates"], large["triangles"], all_triangles=True
            )
            movements.extend(
                small_tree.find_nearest(coordinate)[3] * 1000.0
                for coordinate in large["coordinates"]
            )
            movements.extend(
                large_tree.find_nearest(coordinate)[3] * 1000.0
                for coordinate in small["coordinates"]
            )
        moved_vertices = sum(distance > 0.01 for distance in movements)
        maximum_movement = max(movements, default=0.0)
        passed = (
            same_topology
            and small["boundary"] == large["boundary"] == 0
            and small["nonmanifold"] == large["nonmanifold"] == 0
            and small["zero_faces"] == large["zero_faces"] == 0
            and abs(small["requested"] - 0.2) < 1.0e-6
            and abs(large["requested"] - 1.0) < 1.0e-6
            and large["mean"] > small["mean"] + 0.15
            and moved_vertices > 100
            and maximum_movement > 0.25
            and small["segments"] == large["segments"] == 8
        )
        lines.extend(
            (
                f"topology_same={same_topology} vertices={small['vertices']} "
                f"faces={small['faces']}",
                f"small requested/effective/min/mean={small['requested']:.3f}/"
                f"{small['effective']:.3f}/{small['minimum']:.3f}/"
                f"{small['mean']:.3f}",
                f"large requested/effective/min/mean={large['requested']:.3f}/"
                f"{large['effective']:.3f}/{large['minimum']:.3f}/"
                f"{large['mean']:.3f}",
                f"moved_vertices={moved_vertices} "
                f"maximum_movement_mm={maximum_movement:.3f}",
                f"small_topology={small['boundary']},{small['nonmanifold']},"
                f"{small['zero_faces']} large_topology={large['boundary']},"
                f"{large['nonmanifold']},{large['zero_faces']}",
            )
        )
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    lines.append(f"PASS={passed}")
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))
    bpy.ops.wm.quit_blender()


if bpy.app.background:
    _run()
