"""Regression test for the Bend/Twist deform tools (rigo.deform_*).

The bug: BEND used deform_axis='Z', wrapping the torso around its own vertical
axis (model destroyed).  Correct behaviour is a coronal side-bend: the top of
the scan tips sideways in X, the base stays planted, nothing wraps.
Writes bendtest_result.txt and self-quits.
"""

import bpy

_OUT    = r"C:\Projects\Blender Add-on Braces\bendtest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES  = {"n": 0}
_log    = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _top_bot_indices(obj):
    verts = obj.data.vertices
    idx_top = max(range(len(verts)), key=lambda i: verts[i].co.z)
    idx_bot = min(range(len(verts)), key=lambda i: verts[i].co.z)
    return idx_top, idx_bot


def _evaluated_co(obj, index):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mesh = ev.to_mesh()
    co = mesh.vertices[index].co.copy()
    ev.to_mesh_clear()
    return co


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        bpy.context.scene.rigo_brace.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        bpy.context.scene.rigo_brace.scan_units = "mm"
        bpy.ops.rigo.apply_units()
        height = scan.dimensions.z
        _mark(f"phase=imported height={height:.3f}")

        idx_top, idx_bot = _top_bot_indices(scan)
        top0 = scan.data.vertices[idx_top].co.copy()
        bot0 = scan.data.vertices[idx_bot].co.copy()

        # ---- Bend 30 deg: coronal side-bend ---- #
        bpy.ops.rigo.deform_start(method="BEND")
        mod = scan.modifiers.get("Rigo Deform")
        axis = mod.deform_axis if mod else None
        bpy.context.scene.rigo_brace.bend_angle = 30.0
        top = _evaluated_co(scan, idx_top)
        bot = _evaluated_co(scan, idx_bot)
        dx, dy = abs(top.x - top0.x), abs(top.y - top0.y)
        d_bot = (bot - bot0).length
        # Coronal: top tips sideways (X), no front-back drift, base planted.
        bend_ok = axis == "Y" and dx > height * 0.05 and dy < 0.005 and d_bot < 1e-5
        _mark(
            f"phase=bend axis={axis} dx={dx:.4f} dy={dy:.4f} d_bot={d_bot:.6f} "
            f"bend_ok={bend_ok}"
        )

        # ---- Apply: bake into the mesh, modifier + origin gone ---- #
        bpy.ops.rigo.deform_apply()
        baked_dx = abs(scan.data.vertices[idx_top].co.x - top0.x)
        apply_ok = (
            scan.modifiers.get("Rigo Deform") is None
            and bpy.data.objects.get("Rigo Deform Origin") is None
            and baked_dx > height * 0.05
        )
        _mark(f"phase=apply baked_dx={baked_dx:.4f} apply_ok={apply_ok}")

        # ---- Twist 20 deg: transverse rotation, height preserved ---- #
        top1 = scan.data.vertices[idx_top].co.copy()
        bpy.ops.rigo.deform_start(method="TWIST")
        bpy.context.scene.rigo_brace.twist_angle = 20.0
        top = _evaluated_co(scan, idx_top)
        moved_xy = (top.xy - top1.xy).length
        dz = abs(top.z - top1.z)
        twist_ok = moved_xy > 0.005 and dz < 1e-4
        _mark(f"phase=twist moved_xy={moved_xy:.4f} dz={dz:.6f} twist_ok={twist_ok}")

        # ---- Reset: modifier discarded ---- #
        bpy.ops.rigo.deform_reset()
        reset_ok = scan.modifiers.get("Rigo Deform") is None
        _mark(f"phase=reset reset_ok={reset_ok}")

        _mark(f"PASS={bend_ok and apply_ok and twist_ok and reset_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
