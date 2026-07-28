"""Does Candidate A change anything? Same cells, clean build vs patched build.

Every result in this session was measured with the uncommitted Candidate A
offset-mold repair in the installed add-on. This runs a representative
acceptance matrix and reports, per cell, the quantities that would reveal an
influence:

  * which arcs build (Apply verdict, Generate verdict)
  * rim-overlap count  (rigo_generation_rim_intersections)
  * first clean-to-invalid stage (named by the acceptance contract)
  * rollback behaviour (bit-exact restore, brace untouched)
  * delivered fillet radius (rigo_trim_fillet_* - the brace records what the
    rim ACTUALLY delivered against what was requested)
  * boundary spacing, which sets the rim ceiling

Usage: blender --python candacompare.py -- <case> <label>
  case: control | sa17 | sa24 | st18 | st24 | bl18 | bl24 | painted
  label: clean | canda        (only used to name the result file)
"""

import math
import sys
import traceback

import bmesh
import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import trimverify_ops  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\candacompare"
CASES = {
    "control": (None, None),
    "sa17": ("SMOOTH_ARC", (17, 21)),
    "sa24": ("SMOOTH_ARC", (24, 30)),
    "st18": ("STRAIGHTEN", (18, 20)),
    "st24": ("STRAIGHTEN", (24, 30)),
    "bl18": ("BLEND", (18, 20)),
    "bl24": ("BLEND", (24, 30)),
    "painted": ("PAINTED", None),
}
TRIES = {"n": 0}
LINES = []


def _perimeter():
    return bpy.data.objects["Rigo Trim Perimeter"]


def _fingerprint(curve):
    spline = curve.data.splines[0]
    return repr([
        (
            tuple(round(v, 9) for v in p.co),
            tuple(round(v, 9) for v in p.handle_left),
            tuple(round(v, 9) for v in p.handle_right),
            p.handle_left_type, p.handle_right_type,
            bool(p.select_control_point),
        )
        for p in spline.bezier_points
    ] + [
        {k: str(curve.get(k, "")) for k in trimverify_ops._TRACKED_METADATA}
    ])


def _brace_stats():
    brace = bpy.data.objects.get("Rigo Corset")
    if brace is None:
        return "NO BRACE", {}
    stats = {
        "verts": len(brace.data.vertices),
        "faces": len(brace.data.polygons),
        "rim_overlaps": brace.get("rigo_generation_rim_intersections", "?"),
        "fillet_requested_mm": brace.get("rigo_trim_fillet_requested_mm", 0.0),
        "fillet_max_mm": brace.get("rigo_trim_fillet_radius_mm", 0.0),
        "fillet_mean_mm": brace.get("rigo_trim_fillet_mean_radius_mm", 0.0),
        "fillet_min_mm": brace.get("rigo_trim_fillet_min_radius_mm", 0.0),
    }
    return f"{stats['verts']}v/{stats['faces']}f", stats


def _boundary_spacing_mm(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    lengths = [
        e.calc_length() * 1000.0 for e in bm.edges if len(e.link_faces) == 1
    ]
    bm.free()
    if not lengths:
        return None
    ordered = sorted(lengths)
    return (
        ordered[0],
        ordered[len(ordered) // 2],
        ordered[-1],
        len(ordered),
    )


def _generate():
    try:
        return bpy.ops.rigo.generate_curve_corset() == {"FINISHED"}, ""
    except RuntimeError as exc:
        return False, str(exc).strip().splitlines()[0][:80]


def _apply():
    try:
        return bpy.ops.rigo.apply_trimline_edit(), ""
    except RuntimeError as exc:
        return {"CANCELLED"}, str(exc).strip().splitlines()[0][:110]


def _make_painted():
    from bl_ext.user_default.rigo_brace.operators import design_ops
    from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (
        _ensure_mask,
    )
    from bl_ext.user_default.rigo_brace.operators.design_ops import (
        _inside_unwrapped_polygon,
        _theta_of,
    )

    settings = bpy.context.scene.rigo_brace
    scan = settings.scan_object
    polygon, ax, ay, fx, fy = design_ops._trim_perimeter_uv(bpy.context)
    angles = [angle for angle, _height in polygon]
    lo, hi = min(angles), max(angles)
    attribute = _ensure_mask(scan)
    painted = 0
    for vertex, color in zip(scan.data.vertices, attribute.data):
        world = scan.matrix_world @ vertex.co
        angle = _theta_of(world.x, world.y, ax, ay, fx, fy) % math.tau
        inside = _inside_unwrapped_polygon((angle, world.z), polygon, lo, hi)
        color.color = (0.0, 0.0, 0.0, 1.0) if inside else (1.0, 1.0, 1.0, 1.0)
        painted += int(inside)
    scan.data.update()
    settings.trim_source_mode = "CUSTOM_PAINT"
    bpy.ops.rigo.clear_trimlines()
    settings.trim_custom_spacing = 6.0
    result = bpy.ops.rigo.custom_trim_from_paint()
    return painted, result


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    case = sys.argv[-2] if len(sys.argv) >= 2 else "control"
    label = sys.argv[-1]
    mode, arc = CASES.get(case, (None, None))
    try:
        prepare_reference_design()
        settings = bpy.context.scene.rigo_brace
        LINES.append(
            f"CASE {case} [{label}]  requested fillet="
            f"{settings.trim_fillet_radius:.2f}mm segments="
            f"{settings.trim_fillet_segments} thickness="
            f"{settings.corset_thickness:.2f}mm"
        )
        candidate_a = hasattr(
            __import__(
                "bl_ext.user_default.rigo_brace.operators.design_ops",
                fromlist=["design_ops"],
            ),
            "InnerSurfaceFoldError",
        )
        LINES.append(f"  Candidate A present in build: {candidate_a}")

        if mode == "PAINTED":
            painted, made = _make_painted()
            LINES.append(f"  painted vertices={painted} create={made} "
                         f"controls={len(_perimeter().data.splines[0].bezier_points)}")
            built, error = _generate()
            fingerprint, stats = _brace_stats()
            LINES.append(f"  GENERATE built={built} error={error!r}")
            LINES.append(f"  brace={fingerprint} stats={stats}")
            applied, message = _apply()
            LINES.append(f"  APPLY -> {applied} {message!r}")
        else:
            bpy.ops.rigo.auto_trimline()
            built, error = _generate()
            baseline_fingerprint, baseline_stats = _brace_stats()
            LINES.append(f"  BASELINE generate built={built} error={error!r}")
            LINES.append(f"  BASELINE brace={baseline_fingerprint}")
            LINES.append(f"  BASELINE fillet requested="
                         f"{baseline_stats.get('fillet_requested_mm', 0):.3f}mm "
                         f"delivered max={baseline_stats.get('fillet_max_mm', 0):.3f} "
                         f"mean={baseline_stats.get('fillet_mean_mm', 0):.3f} "
                         f"min={baseline_stats.get('fillet_min_mm', 0):.3f}mm")
            LINES.append(f"  BASELINE rim_overlaps="
                         f"{baseline_stats.get('rim_overlaps')}")
            brace = bpy.data.objects.get("Rigo Corset")
            if brace is not None:
                spacing = _boundary_spacing_mm(brace)
                LINES.append(f"  BASELINE brace boundary spacing={spacing}")

            if mode is not None:
                bpy.ops.rigo.auto_trimline()
                curve = _perimeter()
                for index, point in enumerate(
                    curve.data.splines[0].bezier_points
                ):
                    point.select_control_point = arc[0] <= index <= arc[1]
                before = _fingerprint(curve)
                try:
                    bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode=mode)
                    edit_error = ""
                except RuntimeError as exc:
                    edit_error = str(exc).strip().splitlines()[0][:80]
                LINES.append(f"  EDIT {mode} {arc} error={edit_error!r}")
                applied, message = _apply()
                curve = _perimeter()
                state = trimverify_ops.verification_state(bpy.context, curve)
                LINES.append(f"  APPLY -> {applied} state={state}")
                LINES.append(f"  APPLY message={message!r}")
                LINES.append(
                    f"  ROLLBACK bit-exact={_fingerprint(curve) == before}"
                )
                after_fingerprint, after_stats = _brace_stats()
                LINES.append(
                    f"  brace after={after_fingerprint} "
                    f"untouched={after_fingerprint == baseline_fingerprint}"
                )
                if applied == {"FINISHED"}:
                    built2, error2 = _generate()
                    _f, stats2 = _brace_stats()
                    LINES.append(f"  GENERATE after accept built={built2} "
                                 f"error={error2!r}")
                    LINES.append(
                        f"  fillet delivered max={stats2.get('fillet_max_mm', 0):.3f} "
                        f"mean={stats2.get('fillet_mean_mm', 0):.3f}mm "
                        f"rim_overlaps={stats2.get('rim_overlaps')}"
                    )
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(f"{OUT}_{label}_{case}.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
