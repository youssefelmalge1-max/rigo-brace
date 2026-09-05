"""Time and profile one brace generation at 4 mm thickness (A-model).

Writes gentimedbg_result.txt: wall-clock time, then the hottest functions by
SELF time (where the CPU actually is) and by cumulative time, restricted to the
add-on's own files so Blender internals do not drown the signal.

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/gentimedbg.py
"""

import cProfile
import io
import os
import pstats
import sys
import time
import traceback

import bpy

_PREFIX = os.path.join(
    os.environ["APPDATA"], "Blender Foundation", "Blender", "5.0",
    "extensions", "user_default", "rigo_brace") + os.sep

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bracefixture  # noqa: E402

_OUT = r"C:\Projects\Blender Add-on Braces\gentimedbg_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    try:
        t0 = time.perf_counter()
        scan, settings = bracefixture.prepare_reference_design()
        _mark(f"prepare (import+landmarks+trimline) {time.perf_counter() - t0:.2f}s "
              f"scan_faces={len(scan.data.polygons)}")
        settings.corset_thickness = 4.0

        # Exactness check: on the surface the cut actually classifies, compare
        # the new batch mask against the old scalar per-face test, face by face.
        import importlib
        import numpy as np
        cb = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.curve_build_ops")
        real_keep = cb._keep_curve_interior
        equiv = {}

        def checked_keep(surface, retained_region):
            mesh = surface.data
            centres = np.empty(len(mesh.polygons) * 3)
            mesh.polygons.foreach_get("center", centres)
            m = np.array(surface.matrix_world)
            world = centres.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
            fast = retained_region.contains_many(world)
            import bmesh as _bm
            bm = _bm.new()
            bm.from_mesh(mesh)
            slow = np.array([
                retained_region.contains(surface.matrix_world @ f.calc_center_median())
                for f in bm.faces])
            bm.free()
            equiv["faces"] = len(slow)
            equiv["mismatch"] = int((fast != slow).sum())
            return real_keep(surface, retained_region)

        if os.environ.get("RIGO_GEN_CHECK") == "1":
            cb._keep_curve_interior = checked_keep
        prof = cProfile.Profile()
        t0 = time.perf_counter()
        prof.enable()
        result = bpy.ops.rigo.generate_curve_corset()
        prof.disable()
        wall = time.perf_counter() - t0
        brace = bpy.data.objects.get("Rigo Corset")
        cb._keep_curve_interior = real_keep
        if equiv:
            _mark(f"EQUIVALENCE batch-vs-scalar faces={equiv.get('faces')} "
                  f"mismatches={equiv.get('mismatch')}")
        else:
            _mark("EQUIVALENCE check skipped (set RIGO_GEN_CHECK=1 to run it)")
        _mark(f"generate_curve_corset -> {result}  WALL={wall:.2f}s  "
              f"brace_faces={len(brace.data.polygons) if brace else 0} "
              f"built_thickness={brace.get('rigo_requested_thickness_mm') if brace else None}")

        for key, title in (("tottime", "SELF time"), ("cumtime", "CUMULATIVE")):
            buf = io.StringIO()
            st = pstats.Stats(prof, stream=buf)
            st.sort_stats(key).print_stats("rigo_brace", 22)
            _mark("")
            _mark(f"=== top by {title} (add-on files only) ===")
            for line in buf.getvalue().splitlines():
                if "rigo_brace" in line or line.strip().startswith("ncalls"):
                    _mark(line.replace(_PREFIX, ""))
        # what fraction is bpy/bmesh C calls vs python?
        buf = io.StringIO()
        st = pstats.Stats(prof, stream=buf)
        st.sort_stats("tottime").print_stats(12)
        _mark("")
        _mark("=== top 12 by SELF time, everything ===")
        for line in buf.getvalue().splitlines()[-14:]:
            _mark(line.replace(_PREFIX, ""))
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
