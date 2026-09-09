"""One unprofiled reference shell build per fresh GUI Blender process.

Run with --app-template rigo_brace --python tools/genbench.py -- RUN_LABEL.
Writes genbench_RUN_LABEL_result.txt; exits its own Blender without saving.
"""

import datetime
import importlib
import json
from pathlib import Path
import sys
import time
import traceback

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bracefixture

_ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
_LABEL = _ARGS[0] if _ARGS else "single"
if not _LABEL or not all(c.isalnum() or c in "_-" for c in _LABEL):
    raise ValueError("Run label must contain only letters, numbers, '_' or '-'")
_OUT = Path(__file__).resolve().parents[1] / f"genbench_{_LABEL}_result.txt"
_TRIES = 0
_RESULT = {"done": False, "started": datetime.datetime.now().astimezone().isoformat()}


def _write():
    _OUT.write_text(json.dumps(_RESULT, indent=2), encoding="utf-8")


def _run():
    global _TRIES
    _TRIES += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES < 40:
        return 0.5
    try:
        module = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.curve_build_ops"
        )
        _RESULT.update(blender=bpy.app.version_string, addon_path=module.__file__)
        started = time.perf_counter()
        scan, settings = bracefixture.prepare_reference_design()
        settings.corset_thickness = 4.0
        _RESULT.update(
            preparation_s=time.perf_counter() - started,
            scan_faces=len(scan.data.polygons),
            settings={name: getattr(settings, name) for name in (
                "trim_type", "opening_width", "corset_thickness", "corset_offset",
                "corset_smooth", "trim_fillet_radius", "trim_fillet_segments",
            )},
        )
        _write()
        started = time.perf_counter()
        status = bpy.ops.rigo.generate_curve_corset()
        _RESULT.update(generation_s=time.perf_counter() - started, status=sorted(status))
        brace = bpy.data.objects.get("Rigo Corset")
        if status != {"FINISHED"} or brace is None:
            raise RuntimeError(f"Generation did not finish: {status}")
        _RESULT.update(
            brace_faces=len(brace.data.polygons),
            brace_vertices=len(brace.data.vertices),
            built_thickness_mm=brace.get("rigo_requested_thickness_mm"),
            done=True,
        )
    except Exception:
        _RESULT["error"] = traceback.format_exc()
    finally:
        _write()
        bpy.ops.wm.quit_blender()
    return None


_write()
bpy.app.timers.register(_run, first_interval=0.5)
