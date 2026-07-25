"""Localize the pre-existing non-reproducibility of the curve brace build.

Hashes the candidate mesh after each stage of `_build_curve_corset` across two
consecutive generates in one session, so the first stage whose hash differs
identifies where reproducibility is lost.
"""

import hashlib
import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import curve_build_ops  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\curvestagedbg_result.txt"
TRIES = {"count": 0}
STAGES = []


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _mesh_hash(mesh):
    ordered = [tuple(round(c, 9) for c in v.co) for v in mesh.vertices]
    positional = hashlib.sha256(repr(ordered).encode()).hexdigest()[:12]
    unordered = hashlib.sha256(repr(sorted(ordered)).encode()).hexdigest()[:12]
    return positional, unordered, len(mesh.vertices)


def _record(name, mesh):
    positional, unordered, count = _mesh_hash(mesh)
    STAGES.append((name, positional, unordered, count))


_intersect = curve_build_ops._intersect_curve_cutter
_keep = curve_build_ops._keep_curve_interior
_weld = curve_build_ops._weld_exact_cut_tolerance
_shell = curve_build_ops._build_strict_shell


def _w_intersect(context, surface, cutter):
    _record("00_before_intersect", surface.data)
    result = _intersect(context, surface, cutter)
    _record("01_after_exact_intersect", surface.data)
    return result


def _w_keep(surface, region):
    result = _keep(surface, region)
    _record("02_after_keep_interior", surface.data)
    return result


def _w_weld(surface):
    result = _weld(surface)
    _record("03_after_weld_slivers", surface.data)
    return result


def _w_shell(corset, settings):
    result = _shell(corset, settings)
    _record("04_after_paired_shell", corset.data)
    return result


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "generate_curve_corset") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        curve_build_ops._intersect_curve_cutter = _w_intersect
        curve_build_ops._keep_curve_interior = _w_keep
        curve_build_ops._weld_exact_cut_tolerance = _w_weld
        curve_build_ops._build_strict_shell = _w_shell

        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.corset_smooth = 5
        settings.trim_fillet_radius = 0.3
        settings.trim_fillet_segments = 8

        bpy.ops.rigo.generate_curve_corset()
        half = len(STAGES)
        bpy.ops.rigo.generate_curve_corset()

        first, second = STAGES[:half], STAGES[half:]
        lines.append(f"stages_per_build={half}")
        lines.append(f"{'stage':<28}{'pos_same':>10}{'set_same':>10}{'nverts':>10}")
        for a, b in zip(first, second):
            name = a[0]
            lines.append(
                f"{name:<28}{str(a[1] == b[1]):>10}{str(a[2] == b[2]):>10}"
                f"{a[3]:>10}"
                + ("" if a[3] == b[3] else f"  (second={b[3]})")
            )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
