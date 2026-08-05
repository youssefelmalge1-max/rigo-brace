"""Pinpoint provenance of the style-import weight transfer on a flat grid.

Compares: (a) the actual imported vertex group, (b) the installed
_weights_from_style() called directly, (c) a hand-rolled reimplementation —
then dumps per-vertex disagreement examples with noff/dist/r2d and the frame.
Writes regionprovdbg_result.txt.  GUI Blender only.
"""

import math
import random
import traceback

import bpy
import bmesh
import importlib
from mathutils import Vector, kdtree

_OUT = r"C:\Projects\Blender Add-on Braces\regionprovdbg_result.txt"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _make_grid(name, size_m, divisions, jitter_frac, seed):
    rng = random.Random(seed)
    bm = bmesh.new()
    bmesh.ops.create_grid(
        bm, x_segments=divisions, y_segments=divisions, size=size_m * 0.5
    )
    bmesh.ops.triangulate(bm, faces=bm.faces)
    spacing = size_m / divisions
    for v in bm.verts:
        if len(v.link_edges) >= 6:
            v.co.x += rng.uniform(-jitter_frac, jitter_frac) * spacing
            v.co.y += rng.uniform(-jitter_frac, jitter_frac) * spacing
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.scene.rigo_brace.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    return obj


def _group_weights(obj, mask):
    vg = obj.vertex_groups.get(mask)
    gi = vg.index
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi:
                out[v.index] = g.weight
                break
    return out


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    settings = bpy.context.scene.rigo_brace
    ro = importlib.import_module(
        "bl_ext.user_default.rigo_brace.operators.region_ops"
    )
    lib = importlib.import_module(
        "bl_ext.user_default.rigo_brace.core.region_library"
    )
    style_id = None
    try:
        _mark("phase=start")
        kd = kdtree

        # source grid + circle + commit + save
        g_src = _make_grid("QA_PROV_SRC", 0.3, 100, 0.3, 1)
        tree = kd.KDTree(len(g_src.data.vertices))
        for v in g_src.data.vertices:
            tree.insert(v.co, v.index)
        tree.balance()
        _co, seed, _d = tree.find(Vector((0, 0, 0)))
        bpy.context.scene.cursor.location = g_src.data.vertices[seed].co.copy()
        settings.region_radius = 30.0
        settings.region_magnitude = 15.0
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
        bpy.ops.rigo.region_apply()
        st = bpy.ops.rigo.region_style_save(style_name="QA Prov Style")
        style_id = settings.region_style
        entry = lib.get_entry(style_id)
        max_r2d = max(math.hypot(s[0], s[1]) for s in entry["samples"])
        zs = [s for s in entry["samples"]]
        _mark(
            f"entry: n={len(zs)} sample_radius={entry['sample_radius_mm']:.2f} "
            f"normal_tol={entry['normal_tolerance_mm']:.2f} max_r2d={max_r2d:.1f}"
        )
        bpy.data.objects.remove(g_src, do_unlink=True)

        # target grid + real import
        g_t = _make_grid("QA_PROV_TGT", 0.3, 100, 0.3, 3)
        settings.region_style = style_id
        bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
        bpy.ops.rigo.region_style_import()
        region = g_t.rigo_regions[g_t.rigo_region_index]
        actual = _group_weights(g_t, region.surface_mask)
        _mark(f"actual_group: n={len(actual)}")

        # the installed function, called directly with identical inputs
        target, normal = ro._target_surface(g_t, Vector((0.0, 0.0, 0.0)))
        _mark(
            f"target={tuple(round(c, 5) for c in target)} "
            f"normal={tuple(round(c, 4) for c in normal)}"
        )
        direct = ro._weights_from_style(g_t, entry, target, normal)
        _mark(f"function_direct: n={len(direct)}")
        same = set(direct) == set(actual)
        _mark(f"function_vs_group identical_sets={same}")
        if not same:
            only_a = set(actual) - set(direct)
            only_d = set(direct) - set(actual)
            _mark(f"only_in_group={len(only_a)} only_in_function={len(only_d)}")

        # hand-rolled reimplementation with instrumentation
        side, up, outward = ro._surface_frame(normal)
        _mark(
            f"frame side={tuple(round(c, 4) for c in side)} "
            f"up={tuple(round(c, 4) for c in up)} "
            f"outward={tuple(round(c, 4) for c in outward)}"
        )
        samples = entry["samples"]
        stree = kd.KDTree(len(samples))
        for i, s in enumerate(samples):
            stree.insert((s[0], s[1], 0.0), i)
        stree.balance()
        radius = max(
            float(entry["sample_radius_mm"]), ro._mesh_spacing_mm(g_t) * 1.75
        )
        nlimit = float(entry["normal_tolerance_mm"])
        _mark(f"accept radius={radius:.3f} nlimit={nlimit:.3f} "
              f"mesh_spacing={ro._mesh_spacing_mm(g_t):.3f}")
        mine = {}
        stats = []
        for v in g_t.data.vertices:
            world = g_t.matrix_world @ v.co
            rel = world - target
            noff = abs(rel.dot(outward)) * 1000.0
            u, w2 = rel.dot(side) * 1000.0, rel.dot(up) * 1000.0
            r2d = math.hypot(u, w2)
            if noff > nlimit:
                if r2d < 40.0:
                    stats.append(("CULL_N", v.index, noff, r2d))
                continue
            _c, sidx, dist = stree.find((u, w2, 0.0))
            if dist <= radius:
                mine[v.index] = float(samples[sidx][2])
            elif r2d < 40.0:
                stats.append(("CULL_R", v.index, noff, r2d, dist))
        _mark(f"mine: n={len(mine)} culls_within_40mm={len(stats)}")
        for s in stats[:8]:
            _mark(f"  cull example: {s}")
        diff = set(actual) ^ set(mine)
        _mark(f"mine_vs_group symmetric_diff={len(diff)}")
        for idx in list(diff)[:8]:
            v = g_t.data.vertices[idx]
            world = g_t.matrix_world @ v.co
            rel = world - target
            noff = abs(rel.dot(outward)) * 1000.0
            u, w2 = rel.dot(side) * 1000.0, rel.dot(up) * 1000.0
            _c, sidx, dist = stree.find((u, w2, 0.0))
            _mark(
                f"  diff v{idx} co={tuple(round(c, 4) for c in v.co)} "
                f"noff={noff:.2f} r2d={math.hypot(u, w2):.2f} dist={dist:.2f} "
                f"in_group={idx in actual} in_mine={idx in mine}"
            )
        # weight histogram sanity of the actual group
        wj = sorted(actual.values())
        _mark(
            f"group weights: min={wj[0]:.6f} p25={wj[len(wj)//4]:.4f} "
            f"med={wj[len(wj)//2]:.4f} max={wj[-1]:.4f}"
        )
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        if style_id:
            lib.delete_entry(style_id)
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
