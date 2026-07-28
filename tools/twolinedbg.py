"""Which trimline-like paths are VISIBLE at each stage of the normal workflow?

The orthotist reports seeing two boundaries. This enumerates, at every stage,
every visible object that reads as a line to the user, with the facts needed to
name it: object name, geometry type, spline types, bevel, modifier stack,
visibility flags, and who set that visibility.

It also measures the radial separation between each visible line and the
brace's own cut rim - the number that decides whether a "display lift" reads as
one line lifted for visibility or as a second, visibly separate boundary.
"""

import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\twolinedbg_result.txt"
TRIES = {"n": 0}
LINES = []


def _is_line_like(obj):
    """A curve, or a mesh that is a thin closed loop rather than a body."""
    if obj.type == "CURVE":
        return True
    return False


def _eval_points(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    try:
        mesh = evaluated.to_mesh()
    except Exception:
        return []
    if mesh is None:
        return []
    points = [evaluated.matrix_world @ v.co.copy() for v in mesh.vertices]
    evaluated.to_mesh_clear()
    return points


def _rim_points(brace):
    """World positions of the brace's open boundary - its actual visible edge."""
    import collections

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = brace.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    counts = collections.Counter()
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            counts[key] += 1
    boundary = {v for key, n in counts.items() if n == 1 for v in key}
    points = [evaluated.matrix_world @ mesh.vertices[i].co.copy()
              for i in boundary]
    evaluated.to_mesh_clear()
    return points


def _min_gap_mm(points_a, points_b):
    """For every point of A, distance to the nearest point of B (mm)."""
    if not points_a or not points_b:
        return None
    step_b = max(1, len(points_b) // 900)
    sampled_b = points_b[::step_b]
    step_a = max(1, len(points_a) // 300)
    gaps = []
    for point in points_a[::step_a]:
        gaps.append(min((point - other).length for other in sampled_b) * 1000.0)
    return min(gaps), sum(gaps) / len(gaps), max(gaps)


def _stage(tag):
    settings = bpy.context.scene.rigo_brace
    LINES.append("")
    LINES.append("=" * 74)
    LINES.append(f"STAGE: {tag}   (design_view_mode={settings.design_view_mode!r}, "
                 f"show_trim_overlay={settings.show_trim_overlay})")
    LINES.append("=" * 74)
    visible_lines = []
    for obj in sorted(bpy.data.objects, key=lambda o: o.name):
        if not _is_line_like(obj):
            continue
        drawn = obj.visible_get() and not obj.hide_viewport
        splines = [s.type for s in obj.data.splines] if obj.data.splines else []
        mods = [f"{m.type}" + (
            f"/{m.wrap_mode}+{m.offset*1000:.2f}mm"
            if m.type == "SHRINKWRAP" else ""
        ) for m in obj.modifiers]
        LINES.append(
            f"  {'VISIBLE' if drawn else '  hidden'}  {obj.name!r:<32} "
            f"type={obj.type} splines={splines} "
            f"bevel={obj.data.bevel_depth*1000:.2f}mm mods={mods}"
        )
        if drawn:
            visible_lines.append(obj)
    LINES.append(f"  --> {len(visible_lines)} VISIBLE line object(s): "
                 f"{[o.name for o in visible_lines]}")

    brace = bpy.data.objects.get("Rigo Corset")
    if brace is not None and brace.visible_get():
        rim = _rim_points(brace)
        LINES.append(f"  brace visible; rim boundary points={len(rim)}")
        for obj in visible_lines:
            gap = _min_gap_mm(_eval_points(obj), rim)
            if gap:
                LINES.append(
                    f"      {obj.name!r} vs brace rim: "
                    f"min={gap[0]:.2f} mean={gap[1]:.2f} max={gap[2]:.2f} mm"
                )
    if len(visible_lines) >= 2:
        first, second = visible_lines[0], visible_lines[1]
        gap = _min_gap_mm(_eval_points(first), _eval_points(second))
        if gap:
            LINES.append(
                f"  SEPARATION {first.name!r} vs {second.name!r}: "
                f"min={gap[0]:.2f} mean={gap[1]:.2f} max={gap[2]:.2f} mm"
            )


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    try:
        prepare_reference_design()
        _stage("after template generation")

        bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode="SMOOTH")
        _stage("after Smooth All (ordinary editing)")

        try:
            gen = bpy.ops.rigo.generate_curve_corset()
            err = ""
        except RuntimeError as exc:
            gen, err = "{'CANCELLED'}", str(exc)[:90]
        LINES.append(f"\ngenerate_curve_corset -> {gen} {err}")
        _stage("after brace generation (reviewing the accepted design)")

        bpy.ops.rigo.design_view(mode="TRIM")
        _stage("switched back to Edit Trimlines")

        bpy.ops.rigo.design_view(mode="BRACE")
        _stage("switched to Brace Preview (overlay off = default)")

        # the state the orthotist reports: the overlay switched on
        settings = bpy.context.scene.rigo_brace
        settings.show_trim_overlay = True
        _stage("Brace Preview with Trimline Overlay ON")

        bpy.ops.rigo.design_view(mode="TRIM")
        _stage("Edit Trimlines while show_trim_overlay is still ON")

        # ---- how far is the overlay from the shell edge it duplicates?
        LINES.append("")
        LINES.append("=" * 74)
        LINES.append("SEPARATION MEASUREMENTS")
        LINES.append("=" * 74)
        brace = bpy.data.objects.get("Rigo Corset")
        overlay = bpy.data.objects.get("Rigo Build Trim Perimeter")
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        settings = bpy.context.scene.rigo_brace
        LINES.append(f"corset_thickness = {settings.corset_thickness:.2f} mm; "
                     f"overlay lift = thickness + 1.50 mm clearance")
        if brace is not None and overlay is not None:
            from mathutils.bvhtree import BVHTree

            depsgraph = bpy.context.evaluated_depsgraph_get()
            bvh = BVHTree.FromObject(brace, depsgraph)
            inverse = brace.matrix_world.inverted()
            gaps = []
            for point in _eval_points(overlay)[::9]:
                location, _n, _i, _d = bvh.find_nearest(inverse @ point)
                if location is not None:
                    gaps.append(
                        (point - (brace.matrix_world @ location)).length * 1000.0
                    )
            LINES.append(
                f"  overlay line vs NEAREST BRACE SURFACE: "
                f"min={min(gaps):.2f} mean={sum(gaps)/len(gaps):.2f} "
                f"max={max(gaps):.2f} mm  (n={len(gaps)})"
            )
        # ---- does the line the orthotist sees equal the path that was cut?
        if overlay is not None and perimeter is not None:
            drawn = _eval_points(perimeter)
            cutter = _eval_points(overlay)
            gap = _min_gap_mm(drawn, cutter)
            LINES.append(
                f"  DISPLAYED perimeter vs CUTTER path (overlay, still lifted): "
                f"min={gap[0]:.2f} mean={gap[1]:.2f} max={gap[2]:.2f} mm"
            )
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
