"""Real-flow GUI test for paint-select.

Replicates EXACTLY what the orthotist does:
  1. click "Paint Area"  -> rigo.paint_select (enters SCULPT, mask brush)
  2. paint on the mesh    -> we write .sculpt_mask while IN SCULPT MODE
  3. click an action      -> rigo.push_selection / thicken / delete
                             WHILE STILL IN SCULPT MODE (the real situation)

Writes selectflow_result.txt and self-quits.
"""

import bpy
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\selectflow_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _paint_mask(obj, center, radius):
    """Simulate a brush stroke: write a soft circular mask on surface verts."""
    me = obj.data
    attr = me.attributes.get(".sculpt_mask")
    if attr is None:
        attr = me.attributes.new(".sculpt_mask", "FLOAT", "POINT")
    n = 0
    for i, v in enumerate(me.vertices):
        d = (v.co - center).length
        if d < radius:
            w = max(0.0, 1.0 - d / radius)
            attr.data[i].value = w
            if w > 1e-4:
                n += 1
    me.update()
    return n


def _max_mask(obj):
    a = obj.data.attributes.get(".sculpt_mask")
    if a is None:
        return -1.0
    return max((a.data[i].value for i in range(len(obj.data.vertices))), default=-1.0)


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")
        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        st = bpy.context.scene.rigo_brace
        st.scan_object = scan
        st.select_depth = 8.0
        st.select_thickness = 6.0
        bpy.context.view_layer.objects.active = scan

        bb = [Vector(c) for c in scan.bound_box]
        radius = (bb[6] - bb[0]).length * 0.12
        sidx = max(range(len(scan.data.vertices)),
                   key=lambda i: scan.data.vertices[i].co.x)
        center = scan.data.vertices[sidx].co.copy()

        # --- Step 1: click "Paint Area" -------------------------------------
        r = bpy.ops.rigo.paint_select()
        _mark(f"phase=paint_select result={r} mode={bpy.context.mode}")

        # --- Step 2: paint (while in sculpt mode) ---------------------------
        painted = _paint_mask(scan, center, radius)
        _mark(f"phase=painted verts={painted} maxmask={_max_mask(scan):.3f} "
              f"mode={bpy.context.mode}")

        # --- Step 3a: PUSH OUT while still in SCULPT mode -------------------
        before = scan.data.vertices[sidx].co.copy()
        r = bpy.ops.rigo.push_selection(direction="OUT")
        after = scan.data.vertices[sidx].co.copy()
        moved = (after - before).length
        vg = scan.vertex_groups.get("Rigo Selection") is not None
        _mark(f"phase=push result={r} moved={moved:.5f} vgroup={vg} "
              f"mode={bpy.context.mode}")

        # --- Step 3b: re-enter sculpt, paint, THICKEN ----------------------
        bpy.ops.rigo.paint_select()
        _paint_mask(scan, center, radius)
        fb = len(scan.data.polygons)
        r = bpy.ops.rigo.thicken_selection()
        fa = len(scan.data.polygons)
        _mark(f"phase=thicken result={r} before={fb} after={fa} "
              f"mode={bpy.context.mode}")

        # --- Step 3c: re-enter sculpt, paint, DELETE -----------------------
        bpy.ops.rigo.paint_select()
        rp = _paint_mask(scan, center, radius)
        fb2 = len(scan.data.polygons)
        r = bpy.ops.rigo.delete_selection()
        fa2 = len(scan.data.polygons)
        _mark(f"phase=delete result={r} repaint={rp} before={fb2} after={fa2} "
              f"mode={bpy.context.mode}")

        ok = (painted > 0 and moved > 1e-4 and vg and fa > fb and fa2 < fb2)
        _mark(f"PASS={ok}")
    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
