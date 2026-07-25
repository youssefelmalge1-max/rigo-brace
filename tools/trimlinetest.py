"""Regression: one surface-following perimeter generates one clean A shell."""

import math
import os
import sys

import bmesh
import bpy
from bl_ext.user_default.rigo_brace.operators.qa_ops import evaluate_brace_qa
sys.path.insert(0, os.path.dirname(__file__))
from bracefixture import prepare_a_design  # noqa: E402


_OUT = r"C:\Projects\Blender Add-on Braces\trimlinetest_result.txt"
_TRIES = {"n": 0}
_LOG = []


def _mark(message):
    _LOG.append(str(message))
    with open(_OUT, "w", encoding="utf-8") as result_file:
        result_file.write("\n".join(_LOG))


def _shell_metrics(corset):
    bm = bmesh.new()
    bm.from_mesh(corset.data)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    non_manifold = sum(not edge.is_manifold for edge in bm.edges)
    pending = set(bm.faces)
    components = 0
    while pending:
        components += 1
        stack = [pending.pop()]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for linked in edge.link_faces:
                    if linked in pending:
                        pending.remove(linked)
                        stack.append(linked)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    aspects = []
    for face in bm.faces:
        area = face.calc_area()
        if area <= 1.0e-12:
            continue
        lengths = [edge.calc_length() for edge in face.edges]
        aspects.append(
            sum(length * length for length in lengths)
            / (4.0 * math.sqrt(3.0) * area)
        )
    bm.free()
    aspects.sort()
    return boundary, non_manifold, components, aspects[int(0.95 * (len(aspects) - 1))], aspects[-1]


def _call_qa():
    try:
        return bpy.ops.rigo.verify_brace_qa()
    except RuntimeError:
        return {"CANCELLED"}


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _scan, settings = prepare_a_design()

        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        spline = perimeter.data.splines[0] if perimeter is not None else None
        curve_ok = (
            perimeter is not None
            and len(perimeter.data.splines) == 1
            and spline.use_cyclic_u
            and len(spline.bezier_points) >= 36
            and perimeter.modifiers.get("Follow Corrected Mold") is not None
        )
        _mark(f"phase=perimeter points={len(spline.bezier_points)} curve_ok={curve_ok}")

        bpy.ops.rigo.generate_corset()
        corset = bpy.data.objects.get("Rigo Corset")
        boundary, non_manifold, components, aspect_p95, aspect_max = _shell_metrics(corset)
        shell_ok = (
            boundary == 0
            and non_manifold == 0
            and components == 1
            and aspect_p95 < 3.0
            and aspect_max < 100.0
            and int(corset.get("rigo_rounded_rim_edges", 0)) > 0
        )
        _mark(
            f"phase=shell boundary={boundary} nonmanifold={non_manifold} "
            f"components={components} aspect_p95={aspect_p95:.2f} "
            f"aspect_max={aspect_max:.2f} "
            f"rounded_rim_edges={int(corset.get('rigo_rounded_rim_edges', 0))} "
            f"shell_ok={shell_ok}"
        )
        qa_result = _call_qa()
        qa_report = evaluate_brace_qa(bpy.context, corset)
        qa_pass = qa_result == {"FINISHED"} and bool(corset.get("rigo_qa_pass", False))
        _mark(
            f"phase=manufacturing_qa result={qa_result} pass={qa_pass} "
            f"min_thickness_mm={float(corset.get('rigo_qa_min_thickness_mm', 0.0)):.3f} "
            f"self_intersections={int(corset.get('rigo_qa_self_intersections', -1))}"
        )
        _mark(f"phase=intersection_pairs pairs={qa_report['self_intersection_pairs']}")
        _mark(f"PASS={curve_ok and shell_ok and qa_pass}")
    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
