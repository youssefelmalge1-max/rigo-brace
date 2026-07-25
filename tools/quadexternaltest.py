"""Installed-copy integration test for the Exoside Quad Remesher bridge."""

import bpy


OUT = r"C:\Projects\Blender Add-on Braces\quadexternaltest_result.txt"
TRIES = {"count": 0}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(lines))


def _run():
    TRIES["count"] += 1
    ready = (
        hasattr(bpy.ops.rigo, "use_quad_remesh_result")
        and hasattr(bpy.context.scene, "qremesher")
    )
    if not ready and TRIES["count"] < 30:
        return 0.1

    lines = []
    try:
        from bl_ext.user_default.rigo_brace.operators.mesh_ops import _configure_exoside

        bridge_ready = (
            hasattr(bpy.types, "QREMESHER_OT_remesh")
            and hasattr(bpy.context.scene, "qremesher")
            and hasattr(bpy.ops.export_scene, "fbx")
            and hasattr(bpy.ops.import_scene, "fbx")
        )
        settings = bpy.context.scene.rigo_brace
        settings.quad_remesh_engine = "EXOSIDE"
        settings.quad_target_faces = 12345
        settings.quad_adaptive_size = 67.0
        _configure_exoside(settings, bpy.context.scene.qremesher)
        exoside = bpy.context.scene.qremesher
        preset_ok = (
            exoside.target_count == 12345
            and exoside.adaptive_size == 67.0
            and not exoside.adapt_quad_count
            and not exoside.autodetect_hard_edges
            and exoside.hide_input
        )

        bpy.ops.mesh.primitive_cube_add()
        source_scan = bpy.context.object
        source_scan.name = "Patient Scan"
        settings.scan_object = source_scan
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2)
        remeshed_scan = bpy.context.object
        adoption = bpy.ops.rigo.use_quad_remesh_result()
        adoption_ok = (
            adoption == {"FINISHED"}
            and settings.scan_object == remeshed_scan
            and remeshed_scan.name == "Patient Scan"
            and source_scan.hide_viewport
        )
        passed = bridge_ready and preset_ok and adoption_ok
        lines.extend(
            (
                f"bridge_ready={bridge_ready}",
                f"preset_ok={preset_ok}",
                f"adoption_ok={adoption_ok}",
                f"PASS={passed}",
            )
        )
    except Exception as error:  # noqa: BLE001
        import traceback

        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        lines.append("PASS=False")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
