"""Straighten Arc alone makes the brace unbuildable. Find the first
clean-to-invalid stage.

Standalone only - no stacked edits. Two runs of the identical pipeline from a
freshly generated template trimline: a CONTROL run with no edit, and a
STRAIGHTEN run. Every stage of `_build_curve_corset` is walked by hand so the
first stage that differs materially can be named:

  1 authoritative curve BEFORE Straighten
  2 curve immediately AFTER Straighten
  3 projected cutter samples      (_projected_perimeter)
  4 exact cut                     (_cut_surface)
  5 boundary extraction + resample(_resample_cut_boundary)
  6 rim construction              (_build_strict_shell)
  7 wall join and validation      (_validate_finished_rim)

Measured at the curve stages: endpoint and protected-landmark movement,
control spacing, tangent/curvature discontinuity, self-approach, chord ratio.
At the mesh stages: boundary loop count and ordering, non-manifold edge
locations with incident-face provenance.
"""

import math
import sys
import traceback

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
    trimline_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\straightendbg_result.txt"
ARC = (20, 28)
TRIES = {"n": 0}
LINES = []


def _say(text=""):
    LINES.append(text)


# ---------------------------------------------------------------- curve stage

def _controls(curve):
    return [
        curve.matrix_world @ p.co.copy()
        for p in curve.data.splines[0].bezier_points
    ]


def _dense(curve):
    samples, _per = curve_build_ops._curve_world_samples(curve), None
    return samples


def _spacing_mm(points):
    count = len(points)
    return [
        (points[(i + 1) % count] - points[i]).length * 1000.0
        for i in range(count)
    ]


def _turn_angles_deg(points):
    """Angle between consecutive chords - a cusp shows up as a large value."""
    count = len(points)
    out = []
    for index in range(count):
        before = points[index] - points[(index - 1) % count]
        after = points[(index + 1) % count] - points[index]
        if before.length <= 1e-12 or after.length <= 1e-12:
            out.append(0.0)
            continue
        cosine = max(-1.0, min(1.0, before.normalized().dot(after.normalized())))
        out.append(math.degrees(math.acos(cosine)))
    return out


def _min_self_gap_mm(points, skip):
    count = len(points)
    best, where = math.inf, None
    for first in range(count):
        for second in range(first + skip, count):
            if count - (second - first) < skip:
                continue
            distance = (points[first] - points[second]).length
            if distance < best:
                best, where = distance, (first, second)
    return best * 1000.0, where


def _chord_ratio(points, run):
    arc = sum(
        (points[run[i + 1]] - points[run[i]]).length for i in range(len(run) - 1)
    )
    chord = (points[run[-1]] - points[run[0]]).length
    return arc / chord if chord > 1e-12 else math.inf


def _curve_report(tag, curve, scan, baseline=None):
    _say(f"  -- {tag}")
    controls = _controls(curve)
    dense = _curve_world_samples(curve)
    spacing = _spacing_mm(controls)
    turns = _turn_angles_deg(dense)
    gap_mm, where = _min_self_gap_mm(dense[::4], 6)
    protected = trimline_ops._opening_locked_indices(curve, controls)
    _say(f"     controls={len(controls)} spacing mm min={min(spacing):.2f} "
         f"max={max(spacing):.2f} ratio={max(spacing)/min(spacing):.1f}x")
    _say(f"     dense turn angle deg: p99={sorted(turns)[int(0.99*(len(turns)-1))]:.2f} "
         f"max={max(turns):.2f}")
    _say(f"     min non-adjacent self-gap={gap_mm:.2f}mm at dense pair {where}")
    _say(f"     protected/opening stations={sorted(protected)}")
    if baseline is not None:
        moved = [(a - b).length * 1000.0 for a, b in zip(controls, baseline)]
        pinned = [ARC[0], ARC[1]]
        _say(f"     control movement mm: max={max(moved):.3f} "
             f"mean={sum(moved)/len(moved):.3f}")
        _say(f"     PINNED endpoints {pinned}: "
             + ", ".join(f"{i}->{moved[i]:.4f}mm" for i in pinned))
        _say("     PROTECTED landmarks: "
             + ", ".join(f"{i}->{moved[i]:.3f}mm" for i in sorted(protected)))
        run = list(range(ARC[0], ARC[1] + 1))
        _say(f"     arc chord ratio (arc/chord) before-vs-after: "
             f"{_chord_ratio(baseline, run):.4f} -> {_chord_ratio(controls, run):.4f}")
    return controls


def _curve_world_samples(curve):
    return curve_build_ops._curve_world_samples(curve)


# ----------------------------------------------------------------- mesh stage

def _loops_of(bm):
    """Ordered boundary loops: count, lengths, and whether any is degenerate."""
    boundary = [e for e in bm.edges if len(e.link_faces) == 1]
    remaining = set(boundary)
    loops = []
    while remaining:
        edge = remaining.pop()
        loop = [edge]
        vertex = edge.verts[1]
        while True:
            nxt = None
            for candidate in vertex.link_edges:
                if candidate in remaining:
                    nxt = candidate
                    break
            if nxt is None:
                break
            remaining.discard(nxt)
            loop.append(nxt)
            vertex = nxt.other_vert(vertex)
        loops.append(loop)
    return loops


def _mesh_report(tag, mesh_obj):
    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    bm.normal_update()
    nonmanifold = [e for e in bm.edges if len(e.link_faces) > 2]
    boundary = [e for e in bm.edges if len(e.link_faces) == 1]
    loops = _loops_of(bm)
    _say(f"  -- {tag}")
    _say(f"     verts={len(bm.verts)} faces={len(bm.faces)} "
         f"boundary_edges={len(boundary)} nonmanifold_edges={len(nonmanifold)}")
    _say(f"     boundary loops={len(loops)} lengths={[len(l) for l in loops]}")
    for edge in nonmanifold[:6]:
        centre = mesh_obj.matrix_world @ (
            (edge.verts[0].co + edge.verts[1].co) * 0.5
        )
        faces = edge.link_faces
        areas = [f.calc_area() * 1e6 for f in faces]
        normals = [f.normal.copy() for f in faces]
        spread = max(
            (normals[i].angle(normals[j]) for i in range(len(normals))
             for j in range(i + 1, len(normals))),
            default=0.0,
        )
        _say(f"     NONMANIFOLD at ({centre.x:.4f},{centre.y:.4f},{centre.z:.4f}) "
             f"faces={len(faces)} areas_mm2={[f'{a:.4f}' for a in areas]} "
             f"normal_spread={math.degrees(spread):.1f}deg "
             f"len={edge.calc_length()*1000:.4f}mm")
    bm.free()
    return len(nonmanifold), len(boundary)


# ----------------------------------------------------------------------- run

def _pipeline(label, do_straighten):
    _say("")
    _say("=" * 74)
    _say(f"RUN: {label}")
    _say("=" * 74)
    bpy.ops.rigo.auto_trimline()
    curve = bpy.data.objects["Rigo Trim Perimeter"]
    scan = bpy.context.scene.rigo_brace.scan_object
    _say(" STAGE 1  authoritative curve BEFORE any edit")
    baseline = _curve_report("before", curve, scan)

    if do_straighten:
        for index, point in enumerate(curve.data.splines[0].bezier_points):
            point.select_control_point = ARC[0] <= index <= ARC[1]
        result = bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode="STRAIGHTEN")
        _say(f" STAGE 2  after Straighten Arc {ARC} -> {result}")
        _curve_report("after", curve, scan, baseline=baseline)
    else:
        _say(" STAGE 2  (control run: no edit)")

    settings = bpy.context.scene.rigo_brace
    base = design_ops._prepare_candidate_base(bpy.context, scan, settings)
    corset = curve_build_ops._new_brace_candidate(bpy.context, base)
    try:
        projected = curve_build_ops._projected_perimeter(corset, curve)
        coords = [corset.matrix_world @ c for c in projected.coordinates]
        turns = _turn_angles_deg(coords)
        gap_mm, where = _min_self_gap_mm(coords[::4], 6)
        _say(" STAGE 3  projected cutter samples")
        _say(f"     n={len(coords)} min non-adjacent gap={gap_mm:.3f}mm at {where}")
        _say(f"     turn angle deg p99="
             f"{sorted(turns)[int(0.99*(len(turns)-1))]:.2f} max={max(turns):.2f}")
        spacing = _spacing_mm(coords)
        _say(f"     sample spacing mm min={min(spacing):.4f} max={max(spacing):.4f}")

        retained = curve_build_ops._retained_region(settings, curve, projected)
        curve_build_ops._cut_surface(
            bpy.context, corset, projected, retained, settings
        )
        _say(" STAGE 4-5  exact cut, boundary extraction and resample")
        _mesh_report("after _cut_surface", corset)

        curve_build_ops._build_strict_shell(corset, settings)
        _say(" STAGE 6  rim construction / wall join")
        nonmanifold, boundary = _mesh_report("after _build_strict_shell", corset)

        _say(" STAGE 7  final validation")
        try:
            design_ops._validate_finished_rim(corset)
            _say("     _validate_finished_rim: OK")
        except Exception as error:  # noqa: BLE001
            _say(f"     _validate_finished_rim RAISED: {str(error)[:150]}")
    except Exception as error:  # noqa: BLE001
        _say(f"  PIPELINE RAISED at an earlier stage: {error!r}")
        _say(traceback.format_exc())
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
        _pipeline("CONTROL - no edit", False)
        _pipeline("STRAIGHTEN ARC alone", True)
    except Exception as error:  # noqa: BLE001
        _say(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
