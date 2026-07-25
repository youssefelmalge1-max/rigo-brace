"""Installed-copy regression for rounded, surface-normal strap slots.

Gates:
- The marker is the same closed capsule shape used by the cutter.
- A front-surface marker removes volume through the wall and adds one handle.
- The entrance/exit loops receive a measured multi-segment fillet.
- The finished brace remains closed and manifold and previous QA is invalidated.
- A marker that misses the brace cancels transactionally and remains editable.
"""

import os

import bpy
import bmesh
from mathutils import Vector


OUT = r"C:\Projects\Blender Add-on Braces\slottest_result.txt"
TRIES = {"count": 0}
LINES = []


def _write(message):
    LINES.append(str(message))
    with open(OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(LINES))


def _source_record(brace):
    from bl_ext.user_default.rigo_brace.core.signatures import geometry_signature

    bpy.ops.mesh.primitive_cube_add(location=(2.0, 0.0, 0.0))
    scan = bpy.context.object
    scan.name = "Slot Source Scan"
    curve = bpy.data.curves.new("Slot Source Perimeter", type="CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(3)
    for point, coordinate in zip(
        spline.points,
        (
            (-0.1, -0.1, 0.0, 1.0),
            (0.1, -0.1, 0.0, 1.0),
            (0.1, 0.1, 0.0, 1.0),
            (-0.1, 0.1, 0.0, 1.0),
        ),
    ):
        point.co = coordinate
    spline.use_cyclic_u = True
    perimeter = bpy.data.objects.new("Rigo Trim Perimeter", curve)
    bpy.context.collection.objects.link(perimeter)
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = scan
    settings.brace_dirty = False
    settings.design_view_mode = "BRACE"
    brace["rigo_source_scan_signature"] = geometry_signature(bpy.context, scan)
    brace["rigo_source_trim_signature"] = geometry_signature(bpy.context, perimeter)
    brace["rigo_brace_dirty"] = False
    brace["rigo_brace_dirty_reason"] = ""


def _topology(obj):
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        used_edges = {edge for face in bm.faces for edge in face.edges}
        used_vertices = {vertex for face in bm.faces for vertex in face.verts}
        chi = len(used_vertices) - len(used_edges) + len(bm.faces)
        boundary = sum(edge.is_boundary for edge in bm.edges)
        nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
        volume = abs(bm.calc_volume(signed=True))
    finally:
        bm.free()
    return chi, boundary, nonmanifold, volume


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["count"] < 30:
        return 0.1
    try:
        try:
            from bl_ext.user_default.rigo_brace.operators.design_ops import (
                _SlotPlacement,
                _new_slot_marker,
            )
        except ImportError:
            from rigo_brace.operators.design_ops import _SlotPlacement, _new_slot_marker

        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        bpy.ops.mesh.primitive_cube_add()
        brace = bpy.context.object
        brace.name = "Rigo Corset"
        brace.dimensions = (0.16, 0.004, 0.20)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        settings = bpy.context.scene.rigo_brace
        settings.slot_width = 40.0
        settings.slot_height = 12.0
        settings.slot_edge_radius = 0.8
        settings.corset_thickness = 4.0
        settings.symmetrical = False
        _source_record(brace)
        brace.hide_set(False)
        brace["rigo_qa_pass"] = True
        brace["rigo_qa_signature"] = "stale-before-slot"

        _new_slot_marker(
            bpy.context,
            _SlotPlacement(
                "SLOT_0",
                Vector((0.0, -0.002, 0.0)),
                Vector((0.0, -1.0, 0.0)),
                settings.slot_width,
                settings.slot_height,
            ),
        )
        marker = next(obj for obj in bpy.data.objects if obj.name.startswith("SLOT_"))
        bpy.context.view_layer.update()
        world_corners = [marker.matrix_world @ Vector(corner) for corner in marker.bound_box]
        world_span_x = max(point.x for point in world_corners) - min(
            point.x for point in world_corners
        )
        world_span_z = max(point.z for point in world_corners) - min(
            point.z for point in world_corners
        )
        preview_ok = (
            marker.type == "MESH"
            and len(marker.data.vertices) >= 32
            and marker.show_in_front
            and marker.display_type == "WIRE"
            and world_span_z > world_span_x * 2.0
        )
        chi0, boundary0, nonmanifold0, volume0 = _topology(brace)
        result = bpy.ops.rigo.cut_slots()
        chi1, boundary1, nonmanifold1, volume1 = _topology(brace)
        markers_removed = not any(
            obj.name.startswith("SLOT_") for obj in bpy.data.objects
        )
        qa_invalidated = (
            not bool(brace.get("rigo_qa_pass", True))
            and "rigo_qa_signature" not in brace
            and "Strap slots changed" in str(brace.get("rigo_qa_report", ""))
        )
        cut_ok = (
            result == {"FINISHED"}
            and volume1 < volume0
            and chi0 - chi1 == 2
            and boundary0 == boundary1 == 0
            and nonmanifold0 == nonmanifold1 == 0
            and int(brace.get("rigo_slot_rounded_edges", 0)) >= 2
            and abs(float(brace.get("rigo_slot_fillet_radius_mm", 0.0)) - 0.8)
            < 1.0e-6
            and markers_removed
            and qa_invalidated
        )
        _write(
            f"cut={result} preview={preview_ok} "
            f"marker_span_xz={world_span_x:.6f},{world_span_z:.6f} "
            f"chi={chi0}->{chi1} "
            f"boundary={boundary0}->{boundary1} "
            f"nonmanifold={nonmanifold0}->{nonmanifold1} "
            f"volume={volume0:.9f}->{volume1:.9f} "
            f"rounded_edges={brace.get('rigo_slot_rounded_edges', 0)} "
            f"qa_invalidated={qa_invalidated} ok={cut_ok}"
        )

        # A missed marker must keep both the last good mesh and the marker.
        signature_before = (len(brace.data.vertices), len(brace.data.polygons), volume1)
        _new_slot_marker(
            bpy.context,
            _SlotPlacement(
                "SLOT_MISS",
                Vector((1.0, -0.002, 0.0)),
                Vector((0.0, -1.0, 0.0)),
                settings.slot_width,
                settings.slot_height,
            ),
        )
        failed = False
        try:
            miss_result = bpy.ops.rigo.cut_slots()
        except RuntimeError:
            miss_result = {"CANCELLED"}
            failed = True
        _, boundary2, nonmanifold2, volume2 = _topology(brace)
        signature_after = (len(brace.data.vertices), len(brace.data.polygons), volume2)
        miss_marker_kept = any(
            obj.name.startswith("SLOT_") for obj in bpy.data.objects
        )
        rollback_ok = (
            failed
            and miss_result == {"CANCELLED"}
            and signature_before == signature_after
            and boundary2 == 0
            and nonmanifold2 == 0
            and miss_marker_kept
        )
        _write(
            f"miss={miss_result} signature={signature_before}->{signature_after} "
            f"marker_kept={miss_marker_kept} rollback_ok={rollback_ok}"
        )
        clear_result = bpy.ops.rigo.clear_slots()
        orphan_slot_meshes = [
            mesh.name
            for mesh in bpy.data.meshes
            if mesh.users == 0
            and (mesh.name.startswith("SLOT_") or mesh.name.startswith("Rigo Slot Cutter"))
        ]
        cleanup_ok = clear_result == {"FINISHED"} and not orphan_slot_meshes
        _write(
            f"clear={clear_result} orphan_slot_meshes={orphan_slot_meshes} "
            f"cleanup_ok={cleanup_ok}"
        )
        _write(f"PASS={preview_ok and cut_ok and rollback_ok and cleanup_ok}")
    except Exception as error:  # noqa: BLE001
        import traceback

        _write(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


if bpy.app.background:
    _run()
else:
    bpy.app.timers.register(_run, first_interval=0.5)
