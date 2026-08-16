"""#49k step 2 design probe — what must a library-region field sampler contain?

At import the applied weight is a COMPOSITION:

    w_i = chart(u_i, v_i) * normal_fade(i) * trim_fade(d_i)

Refinement needs w(p) for arbitrary p.  chart and normal_fade are closed form;
trim_fade needs the geodesic distance d, which exists only per original vertex.
This probe measures whether the trim term matters at all before any production
code is written:

  agreement  = |sampler(co_i) - w_i| at the ORIGINAL member vertices
  wall       = committed wall quality when refinement is fed that sampler

Arms: chart only, chart*normal_fade, chart*normal_fade*trim_fade(d via IDW).

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/libfielddbg.py
"""

import heapq
import json
import math
import os
import statistics
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "libfielddbg_result.txt")
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
    ridge10 = 0
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            continue
        a, b = edge.verts[0].index, edge.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        try:
            angles.append(math.degrees(abs(edge.calc_face_angle())))
            if math.degrees(edge.calc_face_angle_signed()) > 10.0:
                ridge10 += 1
        except ValueError:
            continue
    bm.free()
    return {
        "p95": _pct(angles, 0.95),
        "max": max(angles) if angles else 0.0,
        "over30": sum(1 for a in angles if a > 30.0),
        "ridge10": ridge10,
        "n": len(angles),
    }


def _geodesic_from_seed(obj, member, target_world):
    """Same construction _geodesic_trim uses: Dijkstra over the member
    subgraph from the member vertex nearest the anchor."""
    me = obj.data
    matrix = obj.matrix_world
    coords = [v.co.copy() for v in me.vertices]
    seed = min(member,
               key=lambda i: (matrix @ coords[i] - target_world).length_squared)
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
    return dist


def _make_sampler(ro, obj, entry, target_world, normal, kind, dist=None,
                  coords=None):
    side, up, outward = ro._surface_frame(normal)
    grid = entry.get("field")
    tolerance = max(5.0, float(entry.get("normal_tolerance_mm", 15.0)))
    matrix = obj.matrix_world
    limit = float(entry.get("max_geodesic_mm") or 0.0) * 1.15 * 0.001
    fade_start = limit * 0.8

    tree = None
    dvals = None
    if kind == "trim" and dist:
        keys = sorted(dist)
        tree = kdtree.KDTree(len(keys))
        for n, i in enumerate(keys):
            tree.insert(coords[i], n)
        tree.balance()
        dvals = [dist[i] for i in keys]

    def sample(co_local):
        relative = matrix @ co_local - target_world
        offset = abs(relative.dot(outward)) * 1000.0
        if offset >= tolerance * 2.0:
            return 0.0
        u = relative.dot(side) * 1000.0
        v = relative.dot(up) * 1000.0
        w = ro._field_weight(grid, u, v)
        if kind == "chart":
            return max(0.0, min(1.0, w))
        if offset > tolerance:
            t = 1.0 - (offset - tolerance) / tolerance
            w *= t * t * (3.0 - 2.0 * t)
        if kind == "trim" and tree is not None and limit > 0.0:
            num = den = 0.0
            for _co, n, dd in tree.find_n(co_local, 6):
                kernel = 1.0 / (dd * dd + 1e-9)
                num += dvals[n] * kernel
                den += kernel
            if den:
                d = num / den
                if d > fade_start:
                    t = max(0.0, 1.0 - (d - fade_start) / (limit - fade_start))
                    w *= t * t * (3.0 - 2.0 * t)
        return max(0.0, min(1.0, w))

    return sample


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
        real_refine = ro._refine_footprint

        def setup():
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
            region = obj.rigo_regions[obj.rigo_region_index]
            return obj, region, cursor

        # ---- agreement of each candidate sampler with the AUTHORED weights ---
        _mark("=== agreement with the authored weights (original vertices) ===")
        state = setup()
        obj, region, cursor = state
        weights = _group_weights(obj, region.surface_mask)
        member = set(weights)
        coords = [v.co.copy() for v in obj.data.vertices]
        _target, normal = ro._target_surface(obj, cursor)
        dist = _geodesic_from_seed(obj, member, cursor)
        _mark(f"  members={len(member)} max_geodesic_mm={entry.get('max_geodesic_mm')}")
        for kind in ("chart", "normal", "trim"):
            sampler = _make_sampler(ro, obj, entry, cursor, normal, kind,
                                    dist, coords)
            deltas = [abs(sampler(coords[i]) - weights[i]) for i in member]
            _mark(
                f"  sampler={kind:7s} mean|d|={statistics.fmean(deltas):.4f} "
                f"p95={_pct(deltas, 0.95):.4f} max={max(deltas):.4f}"
            )

        # ---------------------------- wall per arm ---------------------------
        _mark("")
        _mark("=== committed wall per refinement arm ===")

        def arm(tag, make, force_none=False, no_refine=False):
            state = setup()
            if state is None:
                _mark(f"  {tag}: import refused")
                return
            obj, region, cursor = state
            weights = _group_weights(obj, region.surface_mask)
            coords = [v.co.copy() for v in obj.data.vertices]
            _target, normal = ro._target_surface(obj, cursor)
            dist = _geodesic_from_seed(obj, set(weights), cursor)
            sampler = None if (force_none or no_refine) else make(
                obj, cursor, normal, dist, coords)
            if no_refine:
                def stub(*a, **k):
                    return 0, 0.0
                ro._refine_footprint = stub
            elif force_none:
                # the pre-#49k library path: refinement re-interpolates the
                # coarse weights it was just handed
                def blind(temp_me, group_index, offset, curved=True,
                          harmonic=True, field=None):
                    return real_refine(temp_me, group_index, offset,
                                       curved=curved, harmonic=harmonic,
                                       field=None)
                ro._refine_footprint = blind
            elif sampler is None:
                ro._refine_footprint = real_refine
            else:
                def forced(temp_me, group_index, offset, curved=True,
                           harmonic=True, field=None):
                    return real_refine(temp_me, group_index, offset,
                                       curved=curved, harmonic=harmonic,
                                       field=sampler)
                ro._refine_footprint = forced
            try:
                res = bpy.ops.rigo.region_apply()
            finally:
                ro._refine_footprint = real_refine
            if "FINISHED" not in res:
                _mark(f"  {tag}: commit refused {res}")
                return
            stats = _wall(obj, _group_weights(obj, region.surface_mask))
            _mark(
                f"  ARM {tag:34s} p95={stats['p95']:6.2f} "
                f"max={stats['max']:6.2f} over30={stats['over30']:3d} "
                f"ridge10={stats['ridge10']:3d} n={stats['n']}"
            )

        # Step 3: the four arms the orthotist asked for, in order.
        arm("1 old library path (field=None)", lambda *a: None, force_none=True)
        arm("2 no refinement at all", lambda *a: None, no_refine=True)
        for kind in ("chart", "normal", "trim"):
            arm(
                f"3 continuous field ({kind})",
                lambda obj, cursor, normal, dist, coords, k=kind:
                    _make_sampler(ro, obj, entry, cursor, normal, k, dist,
                                  coords),
            )
        arm("4 FIXED production (untouched)", lambda *a: None)
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
