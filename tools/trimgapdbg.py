"""#49k step 4 — is `_geodesic_trim` responsible for the library-vs-painted gap?

After the step-2 fix the library route commits at wall p95 20.73 against the
painted route's 17.57.  `_geodesic_trim` multiplies a smoothstep of an
edge-walk Dijkstra distance onto the placed weights, and edge-walk Dijkstra is
the anisotropic metric #49e removed from the painted path — so it is the prime
suspect.  Suspicion is not evidence.  This probe:

  1. MEASURES the anisotropy of the trim distance directly (Dijkstra from the
     anchor vs straight-line distance, binned by direction around the pad);
  2. MEASURES how much of the transition wall the fade band even touches;
  3. A/B/C/Ds the committed wall with the fade active, removed, and computed
     from a graph-smoothed distance.

If the fade barely touches the wall, or removing it does not move the wall,
then Dijkstra is not the cause however anisotropic it is.

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/trimgapdbg.py
"""

import heapq
import json
import math
import os
import statistics
import traceback

import bpy
import bmesh
from mathutils import Vector

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "trimgapdbg_result.txt")
_A_SCAN = os.path.join(_ROOT, "A type model.stl")
_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "style_v2_golden.json")
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


def _wall(obj, weights):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    angles = []
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            continue
        a, b = edge.verts[0].index, edge.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        try:
            angles.append(math.degrees(abs(edge.calc_face_angle())))
        except ValueError:
            continue
    bm.free()
    return {
        "p95": _pct(angles, 0.95),
        "max": max(angles) if angles else 0.0,
        "over30": sum(1 for a in angles if a > 30.0),
        "n": len(angles),
    }


def _dijkstra(obj, member, anchor_world):
    me = obj.data
    matrix = obj.matrix_world
    coords = [v.co.copy() for v in me.vertices]
    seed = min(member,
               key=lambda i: (matrix @ coords[i] - anchor_world).length_squared)
    neighbours = {}
    for edge in me.edges:
        a, b = edge.vertices
        if a in member and b in member:
            length = (coords[a] - coords[b]).length
            neighbours.setdefault(a, []).append((b, length))
            neighbours.setdefault(b, []).append((a, length))
    dist = {seed: 0.0}
    heap = [(0.0, seed)]
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist.get(i, 1e30):
            continue
        for j, length in neighbours.get(i, ()):
            nd = d + length
            if nd < dist.get(j, 1e30):
                dist[j] = nd
                heapq.heappush(heap, (nd, j))
    return dist, seed, coords, neighbours


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    lib = None
    try:
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops")
        lib = importlib.import_module(
            "bl_ext.user_default.rigo_brace.core.region_library")
        with open(_FIXTURE, "r", encoding="utf-8") as fh:
            entry = json.load(fh)
        lib.upsert_entry(dict(entry))
        real_trim = ro._geodesic_trim

        def place():
            _clear()
            obj = _import_scan()
            seed = _waist_seed(obj)
            cursor = obj.matrix_world @ obj.data.vertices[seed].co
            bpy.context.scene.cursor.location = cursor
            settings = bpy.context.scene.rigo_brace
            settings.region_kind = "PRESSURE"
            settings.region_magnitude = 20.0
            settings.region_feather = 15.0
            settings.region_falloff = "SMOOTH"
            settings.region_style = entry["id"]
            if "FINISHED" not in bpy.ops.rigo.region_style_import():
                return None
            return obj, obj.rigo_regions[obj.rigo_region_index], cursor

        # ---------------- 1. anisotropy of the trim distance ----------------
        _mark("=== 1. is the trim distance anisotropic? ===")
        obj, region, cursor = place()
        weights = _group_weights(obj, region.surface_mask)
        member = set(weights)
        dist, seed, coords, _nb = _dijkstra(obj, member, cursor)
        matrix = obj.matrix_world
        origin = matrix @ coords[seed]
        _target, normal = ro._target_surface(obj, cursor)
        side, up, _out = ro._surface_frame(normal)
        # ratio of graph distance to straight-line distance, by direction:
        # an ISOTROPIC metric gives the same ratio in every direction, an
        # anisotropic one has the ratio swing with the triangulation's grain.
        buckets = {}
        ratios = []
        for i in member:
            world = matrix @ coords[i]
            straight = (world - origin).length
            if straight < 0.004:
                continue
            ratio = dist[i] / straight
            ratios.append(ratio)
            rel = world - origin
            angle = math.degrees(math.atan2(rel.dot(up), rel.dot(side))) % 360.0
            buckets.setdefault(int(angle // 30) * 30, []).append(ratio)
        _mark(
            f"  graph/straight ratio over {len(ratios)} verts: "
            f"mean={statistics.fmean(ratios):.4f} p95={_pct(ratios, 0.95):.4f} "
            f"max={max(ratios):.4f}"
        )
        means = {}
        for key in sorted(buckets):
            means[key] = statistics.fmean(buckets[key])
        _mark("  mean ratio by direction (30 deg buckets):")
        _mark("    " + "  ".join(f"{k:3d}:{v:.3f}" for k, v in means.items()))
        if means:
            spread = max(means.values()) - min(means.values())
            _mark(
                f"  DIRECTIONAL SPREAD = {spread:.4f} "
                f"({spread / statistics.fmean(list(means.values())) * 100:.1f}% "
                f"of the mean) — this is the anisotropy, in the metric itself"
            )

        # ------------- 2. does the fade band touch the wall at all? ---------
        _mark("")
        _mark("=== 2. does the fade band overlap the transition wall? ===")
        limit = float(entry.get("max_geodesic_mm") or 0.0) * 1.15 * 0.001
        fade_start = limit * 0.8
        wall = {i for i, w in weights.items() if 0.05 < w < 0.95}
        faded = {i for i in member if dist.get(i, 0.0) > fade_start}
        _mark(
            f"  limit={limit * 1000:.1f}mm fade_start={fade_start * 1000:.1f}mm "
            f"members={len(member)} wall={len(wall)} faded={len(faded)} "
            f"faded_and_wall={len(faded & wall)} "
            f"({len(faded & wall) / max(1, len(wall)) * 100:.1f}% of the wall)"
        )

        # ------------------------- 3. A/B/C/D arms -------------------------
        _mark("")
        _mark("=== 3. committed wall with the fade active / removed / smoothed ===")

        def arm(tag, patch):
            # The mask is written at PLACEMENT, so the patch must be active
            # for the import as well as the commit.
            if patch is not None:
                ro._geodesic_trim = patch
            try:
                state = place()
                if state is None:
                    _mark(f"  {tag}: placement refused")
                    return
                obj, region, cursor = state
                res = bpy.ops.rigo.region_apply()
            finally:
                ro._geodesic_trim = real_trim
            if "FINISHED" not in res:
                _mark(f"  {tag}: commit refused {res}")
                return
            w = _group_weights(obj, region.surface_mask)
            stats = _wall(obj, w)
            _mark(
                f"  ARM {tag:32s} members={len(w):4d} p95={stats['p95']:6.2f} "
                f"max={stats['max']:6.2f} over30={stats['over30']:3d} "
                f"n={stats['n']}"
            )

        def no_fade(scan, weights_in, coords_in, target_world, samples,
                    max_geodesic_mm=None):
            """Keep the trim's CUTOFF (the far-side safety property) but drop
            the smoothstep taper."""
            trimmed, realized = real_trim(scan, weights_in, coords_in,
                                          target_world, samples,
                                          max_geodesic_mm)
            # undo the taper by re-reading the untapered weights for kept verts
            return ({i: weights_in[i] for i in trimmed}, realized)

        def no_trim(scan, weights_in, coords_in, target_world, samples,
                    max_geodesic_mm=None):
            """Trim removed entirely — upper bound of 'the trim is the cause'."""
            _t, realized = real_trim(scan, weights_in, coords_in, target_world,
                                     samples, max_geodesic_mm)
            return dict(weights_in), realized

        arm("A production (fade active)", None)
        arm("B cutoff kept, fade removed", no_fade)
        arm("C trim removed entirely", no_trim)

        # ---- 4. if not the trim, is it the grid's own C0 cell seams? -------
        # Bilinear is C0: its gradient jumps across every cell boundary.  Now
        # that refinement SAMPLES the grid at sub-cell resolution (step 2),
        # those seams are resolved for the first time.  Catmull-Rom is C1 —
        # same data, same cells, continuous gradient.
        _mark("")
        _mark("=== 4. if not the trim: does a C1 grid sample close the gap? ===")
        real_field_weight = ro._field_weight

        def _catmull(p0, p1, p2, p3, t):
            return 0.5 * (
                2.0 * p1
                + (-p0 + p2) * t
                + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t * t
                + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t * t * t
            )

        def bicubic(field, u, v):
            cell = field["cell_mm"]
            gx = (u - field["x0"]) / cell
            gy = (v - field["y0"]) / cell
            i0 = int(math.floor(gx))
            j0 = int(math.floor(gy))
            fx = gx - i0
            fy = gy - j0
            nx, ny = field["nx"], field["ny"]
            values = field["values"]

            def cv(i, j):
                if i < 0 or j < 0 or i >= nx or j >= ny:
                    return 0.0
                return values[j * nx + i]

            cols = []
            for dj in (-1, 0, 1, 2):
                row = [cv(i0 + di, j0 + dj) for di in (-1, 0, 1, 2)]
                cols.append(_catmull(row[0], row[1], row[2], row[3], fx))
            return min(1.0, max(0.0,
                                _catmull(cols[0], cols[1], cols[2], cols[3], fy)))

        try:
            ro._field_weight = bicubic
            state = place()
            if state is None:
                _mark("  D: placement refused")
            else:
                obj, region, cursor = state
                res = bpy.ops.rigo.region_apply()
                if "FINISHED" in res:
                    w = _group_weights(obj, region.surface_mask)
                    stats = _wall(obj, w)
                    _mark(
                        f"  ARM D C1 (Catmull-Rom) grid sample     "
                        f"members={len(w):4d} p95={stats['p95']:6.2f} "
                        f"max={stats['max']:6.2f} over30={stats['over30']:3d} "
                        f"n={stats['n']}"
                    )
                else:
                    _mark(f"  D: commit refused {res}")
        finally:
            ro._field_weight = real_field_weight
        _mark("")
        _mark("  painted-route reference for the same body/amount: p95 17.57")
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        if lib is not None:
            try:
                for candidate in list(lib.load_library(force=True)):
                    if candidate.get("id") == "GOLDEN_USER_PRESSURE":
                        lib.delete_entry(candidate["id"])
            except Exception:  # noqa: BLE001
                pass
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
