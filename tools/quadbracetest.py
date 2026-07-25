"""Regression: a quad-remeshed scan keeps quad topology in the curve brace."""

import sys
import traceback

import bmesh
import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import A_SCAN, _fixture_landmarks, _place  # noqa: E402


OUT = r"C:\Projects\Blender Add-on Braces\quadbracetest_result.txt"
TRIES = {"count": 0}


def _quad_ratio(mesh):
    return sum(len(face.vertices) == 4 for face in mesh.polygons) / max(
        1, len(mesh.polygons)
    )


def _topology(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
    bm.free()
    return boundary, nonmanifold


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "generate_curve_corset") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        bpy.ops.wm.stl_import(filepath=A_SCAN)
        scan = bpy.context.object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        settings.quad_remesh_engine = "BLENDER"
        settings.quad_target_faces = 8000
        bpy.ops.rigo.fill_holes()
        remesh_result = bpy.ops.rigo.quad_remesh()
        scan_ratio = _quad_ratio(scan.data)

        for landmark, location in _fixture_landmarks(scan).items():
            _place(settings, landmark, location)
        settings.trim_type = "RIGO_CHENEAU"
        settings.opening_width = 25.0
        settings.trim_fillet_radius = 1.0
        settings.trim_fillet_segments = 8
        bpy.ops.rigo.auto_trimline()

        build_result = bpy.ops.rigo.generate_curve_corset()
        brace = bpy.data.objects.get("Rigo Corset")
        brace_ratio = _quad_ratio(brace.data)
        boundary, nonmanifold = _topology(brace.data)
        passed = (
            remesh_result == {"FINISHED"}
            and build_result == {"FINISHED"}
            and scan_ratio >= 0.95
            and brace_ratio >= 0.80
            and boundary == 0
            and nonmanifold == 0
        )
        lines.extend(
            (
                f"remesh={remesh_result} scan_quad_ratio={scan_ratio:.4f}",
                f"build={build_result} brace_quad_ratio={brace_ratio:.4f}",
                f"boundary={boundary} nonmanifold={nonmanifold}",
                f"PASS={passed}",
            )
        )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
