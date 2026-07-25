"""Debug probe for the pad apply pipeline — dumps each filter stage."""

import bpy
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\paddbg_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        from bl_ext.user_default.rigo_brace.operators import pad_ops

        bpy.ops.wm.stl_import(filepath=_SAMPLE)
        scan = bpy.context.active_object
        settings = bpy.context.scene.rigo_brace
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()

        settings.pad_type = "BLANK_OVAL"
        settings.pad_depth = 10.0
        settings.pad_size = 90.0
        mw = scan.matrix_world
        verts = [mw @ v.co for v in scan.data.vertices]
        idx = max(range(len(verts)), key=lambda i: verts[i].x)
        probe = verts[idx].copy()
        bpy.ops.rigo.add_pad(location=probe, use_location=True)
        pad = settings.active_pad
        _mark(f"pad={pad.name} id={pad.get('rigo_pad_id')} depth={pad.get('rigo_depth')}")

        deps = bpy.context.evaluated_depsgraph_get()
        B = pad_ops._sample_pad_boundary(pad, deps)
        _mark(f"n_boundary={len(B)}")
        if B:
            xs = [b.x for b in B]; ys = [b.y for b in B]; zs = [b.z for b in B]
            _mark(f"b_span=({max(xs)-min(xs):.4f},{max(ys)-min(ys):.4f},{max(zs)-min(zs):.4f})")
            center = sum(B, Vector()) / len(B)
            _mark(f"center={tuple(round(c,4) for c in center)} probe={tuple(round(c,4) for c in probe)}")
            n = pad_ops._newell_normal(B)
            _mark(f"newell={tuple(round(c,4) for c in n)}")
            r_max = max((b - center).length for b in B)
            _mark(f"r_max={r_max:.4f} probe_dist={(probe-center).length:.4f}")
            # probe vertex filters
            vn = (mw.to_3x3() @ scan.data.vertices[idx].normal).normalized()
            _mark(f"vn={tuple(round(c,3) for c in vn)} dot={vn.dot(n):.3f}")
            u, v, _w = pad_ops._surface_frame(n if vn.dot(n) > 0 else -n)
            nn = n if vn.dot(n) > 0 else -n
            off = probe - center
            _mark(f"plane_off={abs(off.dot(nn)):.4f} cap={max(r_max*0.75,0.05):.4f}")
            poly = [((b - center).dot(u), (b - center).dot(v)) for b in B]
            px, py = off.dot(u), off.dot(v)
            _mark(f"pxy=({px:.4f},{py:.4f}) inside={pad_ops._inside_2d(px, py, poly)}")
            import math
            pr = [math.hypot(x, y) for x, y in poly]
            _mark(f"poly_r min={min(pr):.4f} max={max(pr):.4f}")
        # raw handle check
        bp = pad.data.splines[0].bezier_points[0]
        _mark(f"raw_handle={tuple(round(c,4) for c in bp.handle_right)} co={tuple(round(c,4) for c in bp.co)}")
        ev = pad.evaluated_get(deps)
        bpe = ev.data.splines[0].bezier_points[0]
        _mark(f"ev_handle={tuple(round(c,4) for c in bpe.handle_right)} ev_co={tuple(round(c,4) for c in bpe.co)}")
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        import traceback
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
