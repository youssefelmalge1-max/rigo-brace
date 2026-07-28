"""#46 independently: WHAT is thin about the rim/offset stability margin?

Not "which mode breaks it" - that is already answered (all of them, chaotically).
This asks what the rim construction is actually short of when a ~1mm trimline
edit flips a good brace to overlapping.

For each of a few arcs, edited with SMOOTH_ARC (the mode whose battery is
green and which nonetheless breaks at (17,21)), measure along the cut boundary:

  * local boundary spacing, and the rim ceiling it implies (0.35 x spacing)
  * the requested fillet radius against that ceiling - the headroom
  * boundary curvature: the radius of the turn the rim has to negotiate
  * whether the rim radius exceeds the local concave curvature radius, which
    is the classic self-overlap condition for an offset curve

If the failures sit where headroom or curvature radius goes negative/small,
the margin is a measurable quantity and the architectural fix has a target.
"""

import math
import sys
import traceback

import bmesh
import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\rimmargindbg_result.txt"
# One arc per launch: two concurrent Blender instances exhausted this
# machine's memory ("Calloc returns null"), and each cell builds an offset
# mold plus a cut candidate.
ARCS = {
    "none": None,
    "a17": (17, 21),
    "a18": (18, 20),
    "a24": (24, 30),
}
TRIES = {"n": 0}
LINES = []


def _boundary_loop(mesh_obj):
    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    edges = [e for e in bm.edges if len(e.link_faces) == 1]
    if not edges:
        bm.free()
        return []
    adjacency = {}
    for edge in edges:
        for vertex in edge.verts:
            adjacency.setdefault(vertex, []).append(edge)
    start = edges[0].verts[0]
    loop = [start]
    previous, current = None, start
    while True:
        nxt = None
        for edge in adjacency.get(current, ()):
            other = edge.other_vert(current)
            if other is not previous:
                nxt = other
                break
        if nxt is None or nxt is start:
            break
        loop.append(nxt)
        previous, current = current, nxt
        if len(loop) > 20000:
            break
    points = [mesh_obj.matrix_world @ v.co.copy() for v in loop]
    bm.free()
    return points


def _menger_radius(a, b, c):
    """Circumradius of three consecutive boundary points, in metres."""
    ab, bc, ca = (b - a).length, (c - b).length, (a - c).length
    if min(ab, bc, ca) <= 1.0e-9:
        return math.inf
    s = (ab + bc + ca) * 0.5
    area_sq = s * (s - ab) * (s - bc) * (s - ca)
    if area_sq <= 1.0e-18:
        return math.inf
    return (ab * bc * ca) / (4.0 * math.sqrt(area_sq))


def _percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * (len(ordered) - 1)))]


def _analyse(label, arc):
    bpy.ops.rigo.auto_trimline()
    curve = bpy.data.objects["Rigo Trim Perimeter"]
    if arc is not None:
        for index, point in enumerate(curve.data.splines[0].bezier_points):
            point.select_control_point = arc[0] <= index <= arc[1]
        bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode="SMOOTH_ARC")
    settings = bpy.context.scene.rigo_brace
    scan = settings.scan_object
    radius_mm = settings.trim_fillet_radius
    base = design_ops._prepare_candidate_base(bpy.context, scan, settings)
    corset = curve_build_ops._new_brace_candidate(bpy.context, base)
    verdict = "OK"
    try:
        projected = curve_build_ops._projected_perimeter(corset, curve)
        retained = curve_build_ops._retained_region(settings, curve, projected)
        curve_build_ops._cut_surface(
            bpy.context, corset, projected, retained, settings
        )
        loop = _boundary_loop(corset)
        count = len(loop)
        spacing = [
            (loop[(i + 1) % count] - loop[i]).length * 1000.0
            for i in range(count)
        ]
        ceiling = [0.35 * s for s in spacing]
        headroom = [c - radius_mm for c in ceiling]
        radii = [
            _menger_radius(
                loop[(i - 1) % count], loop[i], loop[(i + 1) % count]
            ) * 1000.0
            for i in range(count)
        ]
        finite = [r for r in radii if math.isfinite(r)]
        tight = sum(1 for r in finite if r < radius_mm)
        LINES.append(f"  {label}")
        LINES.append(
            f"     boundary n={count}  spacing mm "
            f"min={min(spacing):.3f} p05={_percentile(spacing,0.05):.3f} "
            f"median={_percentile(spacing,0.5):.3f} max={max(spacing):.3f}"
        )
        LINES.append(
            f"     rim ceiling (0.35 x spacing) vs requested {radius_mm:.2f}mm: "
            f"headroom min={min(headroom):+.3f}mm "
            f"p05={_percentile(headroom,0.05):+.3f}mm; "
            f"stations BELOW the request={sum(1 for h in headroom if h < 0)}"
            f"/{count}"
        )
        LINES.append(
            f"     boundary curvature radius mm: min={min(finite):.3f} "
            f"p01={_percentile(finite,0.01):.3f} p05={_percentile(finite,0.05):.3f}; "
            f"stations tighter than the fillet radius={tight}/{count}"
        )
        try:
            curve_build_ops._build_strict_shell(corset, settings)
            design_ops._validate_finished_rim(corset)
        except Exception as error:  # noqa: BLE001
            verdict = "FAIL " + str(error).strip().splitlines()[0][:60]
        LINES.append(f"     build verdict: {verdict}")
    except Exception as error:  # noqa: BLE001
        LINES.append(f"  {label}: raised early: {str(error)[:110]}")
    finally:
        for obj in (corset, base):
            if obj is not None and design_ops._object_is_registered(obj):
                design_ops._remove_object_and_orphan_mesh(obj)


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    try:
        prepare_reference_design()
        settings = bpy.context.scene.rigo_brace
        LINES.append(
            f"requested fillet radius={settings.trim_fillet_radius:.2f}mm "
            f"segments={settings.trim_fillet_segments} "
            f"thickness={settings.corset_thickness:.2f}mm"
        )
        key = sys.argv[-1] if sys.argv[-1] in ARCS else "none"
        arc = ARCS[key]
        _analyse(
            "unedited template" if arc is None else f"SMOOTH_ARC {arc}", arc,
        )
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    key = sys.argv[-1] if sys.argv[-1] in ARCS else "none"
    with open(OUT.replace(".txt", f"_{key}.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
