"""Functional test for Guided Sculpt CorrectionRegions (Patch 4a).

Quantitative gates (correction_region_model.md / DEC-0014):
- Add: region entry created from a painted selection; mask vertex group exists;
  direction is unit length; radius > 0.
- Live preview leaves the base mesh unchanged and moves every selected vertex
  along its own local normal by 10 mm * weight (|err| < 0.05 mm).
- Update Preview changes the evaluated result without accumulating deformation.
- Commit bakes the preview once; vertices outside the mask remain untouched;
  vertex count and manifold state do not change.
- Mirror: coupled region created across X=0, kind flipped, opposing linked;
  applying it moves the mirrored side.
- Remove: entry + mask vertex group gone.
Writes regiontest_result.txt and self-quits. GUI only.
"""

import time

import bpy
import bmesh
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\regiontest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _nonmanifold(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    n = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    return n


def _weights(obj, mask):
    vg = obj.vertex_groups.get(mask)
    gi = vg.index
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi:
                out[v.index] = g.weight
                break
    return out


def _evaluated_coords(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    return {vertex.index: vertex.co.copy() for vertex in evaluated.data.vertices}


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()

        # ---- paint a region (300-face patch on one side) ---- #
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(scan.data)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        # Clean-zone patch (around vertex 9000).  The face-5000 armpit zone is
        # creased scan noise: committing there now correctly REFUSES (folds) —
        # that behaviour is gated by regionqualtest.py, not this flow test.
        seed = bm.verts[9000].link_faces[0]
        patch = {seed}
        frontier = [seed]
        while len(patch) < 300 and frontier:
            nxt = []
            for f in frontier:
                for e in f.edges:
                    for lf in e.link_faces:
                        if lf not in patch:
                            patch.add(lf)
                            nxt.append(lf)
            frontier = nxt
        for f in patch:
            f.select = True
        bmesh.update_edit_mesh(scan.data)

        # ---- Add ---- #
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = 10.0
        settings.region_feather = 10.0
        bpy.ops.rigo.region_add()
        region = scan.rigo_regions[scan.rigo_region_index]
        direction = Vector(region.direction)
        add_ok = (
            len(scan.rigo_regions) == 1
            and scan.vertex_groups.get(region.surface_mask) is not None
            and abs(direction.length - 1.0) < 1e-4
            and region.radius_mm > 0.0
            and region.kind == "PRESSURE"
        )
        _mark(
            f"phase=add mask={region.surface_mask} radius={region.radius_mm:.0f}mm "
            f"dirlen={direction.length:.4f} add_ok={add_ok}"
        )

        # ---- Live preview: local normals, reversible, non-cumulative ---- #
        weights = _weights(scan, region.surface_mask)
        before = {v.index: v.co.copy() for v in scan.data.vertices}
        normals = {v.index: v.normal.copy() for v in scan.data.vertices}
        nverts0 = len(scan.data.vertices)
        nonman0 = _nonmanifold(scan)
        preview = _evaluated_coords(scan)
        max_err_mm = 0.0
        max_disp_mm = 0.0
        outside_moved = 0
        for v in scan.data.vertices:
            disp = preview[v.index] - before[v.index]
            w = weights.get(v.index, 0.0)
            expected = -normals[v.index] * 0.010 * w
            err = (disp - expected).length * 1000.0
            max_err_mm = max(max_err_mm, err)
            max_disp_mm = max(max_disp_mm, disp.length * 1000.0)
            if w == 0.0 and disp.length > 0.0:
                outside_moved += 1
        base_unchanged = all(
            (v.co - before[v.index]).length < 1e-12 for v in scan.data.vertices
        )
        preview_ok = (
            max_err_mm < 0.05
            and abs(max_disp_mm - 10.0) < 0.05
            and outside_moved == 0
            and base_unchanged
            and len(scan.data.vertices) == nverts0
            and _nonmanifold(scan) == nonman0
        )
        _mark(
            f"phase=preview max_err={max_err_mm:.4f}mm max_disp={max_disp_mm:.3f}mm "
            f"outside_moved={outside_moved} base_unchanged={base_unchanged} "
            f"preview_ok={preview_ok}"
        )

        # The actual UI edit path must restore the mask as a face selection.
        bpy.ops.rigo.region_edit()
        edit_mode_ok = bpy.context.mode == "EDIT_MESH"
        selected_faces = sum(
            1 for face in bmesh.from_edit_mesh(scan.data).faces if face.select
        )
        bpy.ops.rigo.region_update()
        edit_ok = (
            edit_mode_ok
            and selected_faces > 0
            and bpy.context.mode == "OBJECT"
            and scan.modifiers.get(f"RIGO_REGION_PREVIEW_{region.surface_mask}")
            is not None
        )
        _mark(
            f"phase=edit selected_faces={selected_faces} edit_ok={edit_ok}"
        )

        # Updating the amount must replace the preview, not add another 7 mm.
        region.magnitude_mm = 7.0
        bpy.ops.rigo.region_update()
        updated = _evaluated_coords(scan)
        updated_max_mm = max(
            (updated[i] - before[i]).length * 1000.0 for i in updated
        )
        update_ok = abs(updated_max_mm - 7.0) < 0.05 and all(
            (v.co - before[v.index]).length < 1e-12 for v in scan.data.vertices
        )
        _mark(f"phase=update max_disp={updated_max_mm:.3f}mm update_ok={update_ok}")

        t0 = time.perf_counter()
        bpy.ops.rigo.region_apply()
        dt = time.perf_counter() - t0
        committed_max_mm = max(
            (v.co - before[v.index]).length * 1000.0 for v in scan.data.vertices
        )
        apply_ok = (
            abs(committed_max_mm - 7.0) < 0.05
            and scan.modifiers.get(f"RIGO_REGION_PREVIEW_{region.surface_mask}") is None
            and len(scan.data.vertices) == nverts0
            and _nonmanifold(scan) == nonman0
            and dt < 2.0
        )
        _mark(
            f"phase=commit max_disp={committed_max_mm:.3f}mm time={dt:.2f}s "
            f"apply_ok={apply_ok}"
        )

        # ---- Mirror: coupled opposite region ---- #
        bpy.ops.rigo.region_mirror()
        mir = scan.rigo_regions[scan.rigo_region_index]
        src = scan.rigo_regions[0]
        mirror_ok = (
            len(scan.rigo_regions) == 2
            and mir.kind == "EXPANSION"
            and abs(mir.center[0] + src.center[0]) < 1e-6
            and mir.opposing_region == 0
            and src.opposing_region == 1
            and scan.vertex_groups.get(mir.surface_mask) is not None
        )
        before2 = {v.index: v.co.copy() for v in scan.data.vertices}
        bpy.ops.rigo.region_apply()
        moved2 = sum(
            1 for v in scan.data.vertices if (v.co - before2[v.index]).length > 0
        )
        mirror_ok = mirror_ok and moved2 > 0
        _mark(
            f"phase=mirror kind={mir.kind} cx={mir.center[0]:.3f} vs "
            f"{src.center[0]:.3f} moved={moved2} mirror_ok={mirror_ok}"
        )

        # ---- Remove ---- #
        mask2 = mir.surface_mask
        bpy.ops.rigo.region_remove()
        remove_ok = (
            len(scan.rigo_regions) == 1
            and scan.vertex_groups.get(mask2) is None
            and scan.rigo_regions[0].opposing_region == -1
        )
        _mark(f"phase=remove regions={len(scan.rigo_regions)} remove_ok={remove_ok}")

        # ---- Circle at cursor: geodesic quick-region ---- #
        # NB: hold only the int index across the operator call — RNA vertex
        # references go stale when an operator touches the mesh (ERR-0009).
        seed_idx = 9000
        bpy.context.scene.cursor.location = (
            scan.matrix_world @ scan.data.vertices[seed_idx].co
        )
        settings.region_radius = 30.0
        settings.region_kind = "EXPANSION"
        bpy.ops.rigo.region_add_circle()
        circ = scan.rigo_regions[scan.rigo_region_index]
        cw = _weights(scan, circ.surface_mask)
        verts = scan.data.vertices  # fresh lookups post-operator
        seed_co = verts[seed_idx].co.copy()
        # seed weight 1; every member within 30 mm euclidean (<= geodesic);
        # weights fade with distance (spot-check: farthest member < seed)
        seed_w = cw.get(seed_idx, 0.0)
        max_d_mm = max(
            (verts[i].co - seed_co).length * 1000.0 for i in cw
        )
        far_i = max(cw, key=lambda i: (verts[i].co - seed_co).length)
        circle_ok = (
            circ.name.startswith("Circle")
            and abs(seed_w - 1.0) < 1e-4
            and max_d_mm <= 30.0 + 0.01
            and cw[far_i] < 0.5
            and len(cw) > 10
        )
        _mark(
            f"phase=circle verts={len(cw)} seed_w={seed_w:.3f} "
            f"max_d={max_d_mm:.1f}mm far_w={cw[far_i]:.3f} circle_ok={circle_ok}"
        )

        _mark(
            f"PASS={add_ok and preview_ok and edit_ok and update_ok and apply_ok and mirror_ok and remove_ok and circle_ok}"
        )

    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
