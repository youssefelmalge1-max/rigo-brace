"""#49 step 5 prep: find corset generator params that wrap the UNTOUCHED
wrinkled sample scan (control).  Evidence only."""

import collections
import time
import traceback

import bpy

_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_OUT = r"C:\Projects\Blender Add-on Braces\corsetparamdbg_result.txt"


def _import_scan():
    bpy.ops.wm.stl_import(filepath=_SAMPLE)
    obj = bpy.context.active_object
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = obj
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    return obj


def _landmarks(scan):
    settings = bpy.context.scene.rigo_brace
    cos = [scan.matrix_world @ v.co for v in scan.data.vertices]
    z_min = min(c.z for c in cos)
    z_max = max(c.z for c in cos)
    x_min, x_max = min(c.x for c in cos), max(c.x for c in cos)
    y_min, y_max = min(c.y for c in cos), max(c.y for c in cos)
    cx, cy = (x_min + x_max) * 0.5, (y_min + y_max) * 0.5
    dx, dy, dz = x_max - x_min, y_max - y_min, z_max - z_min
    slabs = collections.defaultdict(list)
    for c in cos:
        slabs[round(c.z / 0.01)].append(c)
    middle = [
        (k * 0.01, s) for k, s in slabs.items()
        if z_min + 0.25 * dz < k * 0.01 < z_min + 0.75 * dz
    ]
    waist_z = min(
        middle,
        key=lambda p: max(c.x for c in p[1]) - min(c.x for c in p[1]),
    )[0]
    marks = {
        "TROCHANTER_L": (cx - 0.35 * dx, cy, z_min + 0.06 * dz),
        "TROCHANTER_R": (cx + 0.35 * dx, cy, z_min + 0.06 * dz),
        "WAISTLINE": (cx, cy, waist_z),
        "ACROMION_L": (cx - 0.30 * dx, cy, z_max - 0.05 * dz),
        "ACROMION_R": (cx + 0.30 * dx, cy, z_max - 0.05 * dz),
        "ASIS_L": (cx - 0.18 * dx, y_min + 0.25 * dy, z_min + 0.18 * dz),
        "ASIS_R": (cx + 0.18 * dx, y_min + 0.25 * dy, z_min + 0.18 * dz),
        "PSIS_L": (cx - 0.14 * dx, y_max - 0.25 * dy, z_min + 0.24 * dz),
        "PSIS_R": (cx + 0.14 * dx, y_max - 0.25 * dy, z_min + 0.24 * dz),
    }
    for landmark, location in marks.items():
        settings.active_landmark = landmark
        bpy.context.scene.cursor.location = location
        bpy.ops.rigo.place_landmark()
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    settings = bpy.context.scene.rigo_brace
    try:
        obj = _import_scan()
        settings.design_style = "CHENEAU"
        settings.corset_thickness = 4.0
        _mark(f"smooth defaults: iters={settings.smooth_iterations} "
              f"factor={settings.smooth_factor}")
        done = False
        for smooth_passes in (1, 2, 3):
            bpy.context.view_layer.objects.active = obj
            st = bpy.ops.rigo.smooth()
            _mark(f"smooth pass {smooth_passes}: {st}")
            _landmarks(obj)
            settings.trim_type = "A"
            settings.opening_width = 40.0
            for offset, fairing in ((3.0, 5), (2.0, 10)):
                st = bpy.ops.rigo.auto_trimline()
                if st != {"FINISHED"}:
                    _mark(f"  trimline failed: {st}")
                    continue
                settings.corset_offset = offset
                settings.corset_smooth = fairing
                t0 = time.perf_counter()
                try:
                    st = bpy.ops.rigo.generate_curve_corset()
                except RuntimeError as exc:
                    _mark(f"  smooth={smooth_passes} offset={offset} "
                          f"fairing={fairing} REFUSED {exc}")
                    continue
                dt = time.perf_counter() - t0
                brace = bpy.data.objects.get("Rigo Corset")
                _mark(
                    f"  smooth={smooth_passes} offset={offset} "
                    f"fairing={fairing} st={st} dt={dt:.1f}s "
                    f"faces={0 if brace is None else len(brace.data.polygons)}"
                )
                if st == {"FINISHED"}:
                    done = True
                    break
            if done:
                break
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
