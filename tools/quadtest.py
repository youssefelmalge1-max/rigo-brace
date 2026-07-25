"""Functional test for Quad Remesh (QuadriFlow) in the Clean stage.

Gates:
- Guard: a mesh with a hole is REFUSED (CANCELLED) with no exception — the
  operator enforces the Fill-Holes-first clinical order.
- On the watertight scan: result is 100% quads, watertight (boundary 0),
  manifold (non-manifold 0), and face count within 0.5x-2x of the target.
Writes quadtest_result.txt and self-quits. GUI only.
"""

import bpy
import bmesh

_OUT = r"C:\Projects\Blender Add-on Braces\quadtest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _counts(obj):
    quads = sum(1 for p in obj.data.polygons if len(p.vertices) == 4)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    nonman = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    return len(obj.data.polygons), quads, boundary, nonman


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
        settings.quad_remesh_engine = "BLENDER"
        bpy.context.view_layer.objects.active = scan
        settings.scan_units = "mm"
        bpy.ops.rigo.apply_units()

        # ---- Guard: poke a hole -> operator must refuse ---- #
        # NB: a scripted bpy.ops call turns report({'ERROR'})+CANCELLED into a
        # RuntimeError carrying the message (ERR-0009 family) — expect that.
        bm = bmesh.new()
        bm.from_mesh(scan.data)
        bm.faces.ensure_lookup_table()
        bm.faces.remove(bm.faces[0])
        bm.to_mesh(scan.data)
        bm.free()
        scan.data.update()
        guard_ok = False
        guard_msg = ""
        try:
            result = bpy.ops.rigo.quad_remesh()
            guard_ok = "CANCELLED" in result
            guard_msg = str(sorted(result))
        except RuntimeError as exc:
            guard_ok = "Fill Holes" in str(exc)
            guard_msg = str(exc).strip()[:80]
        _mark(f"phase=guard msg={guard_msg!r} guard_ok={guard_ok}")

        # ---- Repair, then quad remesh ---- #
        bpy.ops.rigo.fill_holes()
        settings.quad_target_faces = 8000
        result = bpy.ops.rigo.quad_remesh()
        faces, quads, boundary, nonman = _counts(scan)
        quad_ok = (
            "FINISHED" in result
            and faces == quads          # 100% quads
            and boundary == 0           # watertight
            and nonman == 0             # manifold
            and 4000 <= faces <= 16000  # near target
        )
        _mark(
            f"phase=quad faces={faces} quads={quads} boundary={boundary} "
            f"nonmanifold={nonman} quad_ok={quad_ok}"
        )

        _mark(f"PASS={guard_ok and quad_ok}")

    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
