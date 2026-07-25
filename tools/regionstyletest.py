"""End-to-end test for save/reload/import of a committed correction style."""

import bpy
import bmesh
import importlib
from mathutils import Vector


region_library = importlib.import_module(
    "bl_ext.user_default.rigo_brace.core.region_library"
)


_OUTPUT = r"C:\Projects\Blender Add-on Braces\regionstyletest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"count": 0}
_LOG = []
_STYLE_ID = {"value": None}


def _mark(message):
    _LOG.append(str(message))
    with open(_OUTPUT, "w", encoding="utf-8") as stream:
        stream.write("\n".join(_LOG))


def _paint_patch(scan):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    edit_mesh = bmesh.from_edit_mesh(scan.data)
    edit_mesh.faces.ensure_lookup_table()
    frontier = [edit_mesh.faces[5000]]
    selected = set(frontier)
    while len(selected) < 300 and frontier:
        next_frontier = []
        for face in frontier:
            for edge in face.edges:
                for linked_face in edge.link_faces:
                    if linked_face not in selected:
                        selected.add(linked_face)
                        next_frontier.append(linked_face)
        frontier = next_frontier
    for face in selected:
        face.select = True
    bmesh.update_edit_mesh(scan.data)


def _evaluated_coordinates(scan):
    evaluated = scan.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    return coordinates


def _run():
    _TRIES["count"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["count"] < 25:
        return 0.1
    try:
        _mark("phase=start")
        settings = bpy.context.scene.rigo_brace
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        source = bpy.context.active_object
        settings.scan_object = source
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        _paint_patch(source)

        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 8.0
        settings.region_feather = 10.0
        bpy.ops.rigo.region_add()
        source_region = source.rigo_regions[source.rigo_region_index]
        source_center = source_region.center[:]
        try:
            bpy.ops.rigo.region_style_save(style_name="QA Must Not Save")
            precommit_ok = False
        except RuntimeError as error:
            precommit_ok = "Commit the region" in str(error)
        _mark(f"phase=precommit rejected={precommit_ok}")
        bpy.ops.rigo.region_apply()
        save_status = bpy.ops.rigo.region_style_save(
            style_name="QA Committed Region Style"
        )
        _STYLE_ID["value"] = settings.region_style
        entry = region_library.get_entry(_STYLE_ID["value"])
        save_ok = (
            save_status == {"FINISHED"}
            and entry is not None
            and entry["kind"] == "PRESSURE"
            and abs(entry["magnitude_mm"] - 8.0) < 1e-6
            and len(entry["samples"]) > 50
            and entry["requires_orthotist_review"]
        )
        _mark(
            f"phase=save id={_STYLE_ID['value']} samples={len(entry['samples'])} "
            f"save_ok={save_ok}"
        )

        reloaded = region_library.load_library(force=True)
        reload_ok = any(item["id"] == _STYLE_ID["value"] for item in reloaded)
        _mark(f"phase=reload reload_ok={reload_ok}")

        source.hide_set(True)
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        target = bpy.context.active_object
        settings.scan_object = target
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        target_vertex_count_before = len(target.data.vertices)
        decimate = target.modifiers.new("QA Different Topology", "DECIMATE")
        decimate.ratio = 0.65
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.modifier_apply(modifier=decimate.name)
        topology_changed = len(target.data.vertices) < target_vertex_count_before
        settings.region_style = _STYLE_ID["value"]
        bpy.context.scene.cursor.location = target.matrix_world @ Vector(source_center)
        before = [vertex.co.copy() for vertex in target.data.vertices]
        import_status = bpy.ops.rigo.region_style_import()
        imported = target.rigo_regions[target.rigo_region_index]
        preview = _evaluated_coordinates(target)
        max_preview_mm = max(
            (preview[index] - coordinate).length * 1000.0
            for index, coordinate in enumerate(before)
        )
        base_unchanged = all(
            (vertex.co - before[vertex.index]).length < 1e-12
            for vertex in target.data.vertices
        )
        import_ok = (
            import_status == {"FINISHED"}
            and imported.name == "QA Committed Region Style"
            and imported.kind == "PRESSURE"
            and abs(imported.magnitude_mm - 8.0) < 1e-6
            and abs(max_preview_mm - 8.0) < 0.05
            and base_unchanged
            and topology_changed
            and target.modifiers.get(
                f"RIGO_REGION_PREVIEW_{imported.surface_mask}"
            ) is not None
        )
        _mark(
            f"phase=import max_preview={max_preview_mm:.3f}mm "
            f"base_unchanged={base_unchanged} topology_changed={topology_changed} "
            f"import_ok={import_ok}"
        )

        edit_status = bpy.ops.rigo.region_edit()
        selected_faces = sum(
            1 for face in bmesh.from_edit_mesh(target.data).faces if face.select
        )
        update_status = bpy.ops.rigo.region_update()
        edit_ok = (
            edit_status == {"FINISHED"}
            and selected_faces > 0
            and update_status == {"FINISHED"}
        )
        _mark(f"phase=edit selected_faces={selected_faces} edit_ok={edit_ok}")

        bpy.ops.rigo.region_apply()
        committed_max_mm = max(
            (vertex.co - before[vertex.index]).length * 1000.0
            for vertex in target.data.vertices
        )
        commit_ok = (
            abs(committed_max_mm - 8.0) < 0.05
            and target.modifiers.get(
                f"RIGO_REGION_PREVIEW_{imported.surface_mask}"
            ) is None
        )
        _mark(f"phase=commit max={committed_max_mm:.3f}mm commit_ok={commit_ok}")

        settings.region_style = _STYLE_ID["value"]
        deleted = bpy.ops.rigo.region_style_delete() == {"FINISHED"}
        _STYLE_ID["value"] = None
        delete_ok = deleted and all(
            item["label"] != "QA Committed Region Style"
            for item in region_library.load_library(force=True)
        )
        _mark(f"phase=cleanup delete_ok={delete_ok}")
        _mark(
            f"PASS={precommit_ok and save_ok and reload_ok and import_ok and edit_ok and commit_ok and delete_ok}"
        )
    except Exception as exception:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exception!r}\n{traceback.format_exc()}\nPASS=False")
    finally:
        if _STYLE_ID["value"]:
            region_library.delete_entry(_STYLE_ID["value"])
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
