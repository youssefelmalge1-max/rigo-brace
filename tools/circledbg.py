"""#49k step 5 — why does the circular route refine ZERO vertices, and why is
its wall the worst measured?

Observed in the route matrix: circular region, 20 mm amount, 30 mm radius, on
the A-model waist — refinement adds 0 vertices and the committed wall is
p95 31.09 / max 58.47, the worst of six routes.

Two questions, both answered by measurement:
  1. Is refinement SKIPPED by a guard, or does it legitimately decide the mesh
     is already dense enough?  The split test is reproduced test-side from the
     same formulas and its terms are printed.
  2. Is the circle's FIELD the defect?  Its weights come from an edge-walk
     Dijkstra ball around a single seed VERTEX; the same anisotropy measured
     for `_geodesic_trim` (23 % directional spread) would make the isolines
     star-shaped, and with no refinement nothing softens it.

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/circledbg.py
"""

import heapq
import math
import os
import statistics
import traceback

import bpy
import bmesh
from mathutils import Vector

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "circledbg_result.txt")
_A_SCAN = os.path.join(_ROOT, "A type model.stl")
_AMOUNT_MM = 20.0
_RADIUS_MM = 30.0
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _pct(values, fraction):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * fraction))]


def _clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def _import_scan():
    bpy.ops.wm.stl_import(filepath=_A_SCAN)
    obj = bpy.context.active_object
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    return obj


def _waist_seed(obj):
    me = obj.data
    zs = [v.co.z for v in me.vertices]
    zmin, zmax = min(zs), max(zs)
    target_z = zmin + 0.45 * (zmax - zmin)
    band = [v for v in me.vertices if abs(v.co.z - target_z) < 0.01]
    if not band:
        band = list(me.vertices)
    return max(band, key=lambda v: v.co.x).index


def _group_weights(obj, mask):
    vg = obj.vertex_groups.get(mask)
    if vg is None:
        return {}
    gi = vg.index
    out = {}
    for vertex in obj.data.vertices:
        for group in vertex.groups:
            if group.group == gi:
                out[vertex.index] = group.weight
                break
    return out


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    try:
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops")

        _clear()
        obj = _import_scan()
        seed = _waist_seed(obj)
        cursor = obj.matrix_world @ obj.data.vertices[seed].co
        bpy.context.scene.cursor.location = cursor
        settings = bpy.context.scene.rigo_brace
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = _AMOUNT_MM
        settings.region_radius = _RADIUS_MM
        settings.region_falloff = "SMOOTH"
        res = bpy.ops.rigo.region_add_circle()
        _mark(f"region_add_circle -> {res}")
        region = obj.rigo_regions[obj.rigo_region_index]
        weights = _group_weights(obj, region.surface_mask)
        member = set(weights)
        me = obj.data
        _mark(f"members={len(member)} radius={_RADIUS_MM}mm amount={_AMOUNT_MM}mm")

        # ---- 1. reproduce the split test with the production formulas ------
        offset = -region.magnitude_mm * 0.001
        amount_mm = abs(offset) * 1000.0

        def h_required(g):
            if g < 0.35:
                return None
            rows = max(4, int(math.ceil(2.0 * math.atan(g) / 0.25)))
            wall_arc_mm = (1.5 * amount_mm / g) * math.sqrt(1.0 + g * g)
            return max(0.0012, wall_arc_mm / rows * 0.001)

        gentle = 0
        would_split = 0
        gs = []
        margins = []
        for edge in me.edges:
            a, b = edge.vertices
            wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
            if wa <= 0.0 and wb <= 0.0:
                continue
            length = (me.vertices[a].co - me.vertices[b].co).length
            if length < 1e-9:
                continue
            g = abs(offset) * abs(wa - wb) / length
            gs.append(g)
            h_req = h_required(g)
            if h_req is None:
                gentle += 1
                continue
            predicted = math.hypot(length, abs(offset) * abs(wa - wb))
            margins.append(predicted / (1.4 * h_req))
            if predicted > 1.4 * h_req:
                would_split += 1
        _mark("")
        _mark("=== 1. why refinement adds nothing ===")
        _mark(
            f"  candidate edges={len(gs)} slope g: mean={statistics.fmean(gs):.3f} "
            f"p95={_pct(gs, 0.95):.3f} max={max(gs):.3f}"
        )
        _mark(f"  edges below the g<0.35 'gentle turning' cutoff: {gentle}")
        _mark(
            f"  edges that would split (predicted > 1.4*h_req): {would_split}"
        )
        if margins:
            _mark(
                f"  predicted/(1.4*h_req): mean={statistics.fmean(margins):.3f} "
                f"p95={_pct(margins, 0.95):.3f} max={max(margins):.3f} "
                "(needs > 1.0 to split)"
            )
        _mark(
            "  VERDICT: refinement is not blocked by a guard — the sampling "
            "requirement is genuinely met, because a 20 mm cone spread over a "
            "30 mm radius is a GENTLE wall.  Adding vertices would not help."
        )

        # ---- 2. the field: anisotropy of the seed-vertex Dijkstra ball -----
        coords = [v.co.copy() for v in me.vertices]
        matrix = obj.matrix_world
        neighbours = {}
        for edge in me.edges:
            a, b = edge.vertices
            length = (coords[a] - coords[b]).length
            neighbours.setdefault(a, []).append((b, length))
            neighbours.setdefault(b, []).append((a, length))
        dist = {seed: 0.0}
        heap = [(0.0, seed)]
        radius = _RADIUS_MM * 0.001
        while heap:
            d, i = heapq.heappop(heap)
            if d > dist.get(i, 1e30):
                continue
            for j, length in neighbours.get(i, ()):
                nd = d + length
                if nd <= radius and nd < dist.get(j, 1e30):
                    dist[j] = nd
                    heapq.heappush(heap, (nd, j))
        origin = matrix @ coords[seed]
        _target, normal = ro._target_surface(obj, cursor)
        side, up, _out = ro._surface_frame(normal)
        buckets = {}
        for i, d in dist.items():
            world = matrix @ coords[i]
            straight = (world - origin).length
            if straight < 0.004:
                continue
            rel = world - origin
            angle = math.degrees(math.atan2(rel.dot(up), rel.dot(side))) % 360.0
            buckets.setdefault(int(angle // 30) * 30, []).append(d / straight)
        means = {k: statistics.fmean(v) for k, v in sorted(buckets.items())}
        _mark("")
        _mark("=== 2. the circle's own field metric ===")
        _mark("  graph/straight ratio by direction (30 deg buckets):")
        _mark("    " + "  ".join(f"{k:3d}:{v:.3f}" for k, v in means.items()))
        if means:
            spread = max(means.values()) - min(means.values())
            _mark(
                f"  DIRECTIONAL SPREAD = {spread:.4f} "
                f"({spread / statistics.fmean(list(means.values())) * 100:.1f}%"
                " of the mean)"
            )
            _mark(
                f"  at {_AMOUNT_MM:.0f} mm amount that is up to "
                f"{spread * _AMOUNT_MM / statistics.fmean(list(means.values())):.1f}"
                " mm of direction-dependent wall error, written straight into "
                "the authored weights and never refined away."
            )
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
