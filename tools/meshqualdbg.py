"""Evidence probe: triangle-quality degradation of committed Pressure regions.

User report (#49): committing a pressure stretches wall triangles ("mesh
angles count bigger"); a later sculpt-smooth produces spikes.  Measures, on
the painted clean-zone 15 mm case and a 30 mm-radius circle case:

  - edge-length stretch (post/pre) inside the footprint and in the wall zone
  - triangle aspect ratios (longest edge / height) pre/post
  - dihedral spikes pre/post
  - the same metrics AFTER a Laplacian smooth of the footprint (reproducing
    the user's sculpt-smooth step)

Writes meshqualdbg_result.txt.  GUI Blender only.
"""

import math
import traceback

import bpy
import bmesh
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\meshqualdbg_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _import_scan():
    bpy.ops.wm.stl_import(filepath=_SAMPLE)
    obj = bpy.context.active_object
    settings = bpy.context.scene.rigo_brace
    settings.scan_object = obj
    bpy.context.view_layer.objects.active = obj
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    return obj


def _weights(obj, mask):
    vg = obj.vertex_groups.get(mask)
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == vg.index:
                out[v.index] = g.weight
                break
    return out


def _quality(me, faces, edge_pre=None):
    """Aspect ratios, edge lengths and (optional) stretch vs pre lengths."""
    aspects = []
    lengths = {}
    for p in faces:
        vs = [me.vertices[i].co for i in p.vertices]
        n = len(vs)
        el = []
        for k in range(n):
            key = tuple(sorted((p.vertices[k], p.vertices[(k + 1) % n])))
            length = (vs[k] - vs[(k + 1) % n]).length
            lengths[key] = length
            el.append(length)
        if p.area > 1e-14:
            longest = max(el)
            aspects.append(longest * longest / (2.0 * p.area))
    stretch = []
    if edge_pre:
        stretch = [
            lengths[k] / edge_pre[k] for k in lengths
            if k in edge_pre and edge_pre[k] > 1e-9
        ]
    aspects.sort()
    return {
        "lengths": lengths,
        "aspect_med": aspects[len(aspects) // 2] if aspects else 0.0,
        "aspect_p95": aspects[int(len(aspects) * 0.95)] if aspects else 0.0,
        "aspect_max": aspects[-1] if aspects else 0.0,
        "aspect_gt4": sum(1 for a in aspects if a > 4.0),
        "aspect_gt8": sum(1 for a in aspects if a > 8.0),
        "len_max_mm": max(lengths.values()) * 1000.0 if lengths else 0.0,
        "len_mean_mm": (sum(lengths.values()) / len(lengths) * 1000.0)
        if lengths else 0.0,
        "stretch_max": max(stretch) if stretch else 0.0,
        "stretch_p95": sorted(stretch)[int(len(stretch) * 0.95)]
        if stretch else 0.0,
        "stretch_gt15": sum(1 for s in stretch if s > 1.5),
        "stretch_gt2": sum(1 for s in stretch if s > 2.0),
    }


def _spikes(obj, fp, ref=None):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    out = {}
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        if not any(v.index in fp for v in e.verts):
            continue
        key = (e.verts[0].index, e.verts[1].index)
        try:
            out[key] = math.degrees(abs(e.calc_face_angle()))
        except ValueError:
            out[key] = 180.0
    bm.free()
    if ref is None:
        return out, sum(1 for a in out.values() if a > 60.0)
    # Split honestly: sharpening of PRE-EXISTING edges is commit damage;
    # >60° on edges born from refinement may simply be the wrinkled scan
    # sampled finer — report both, never conflate.
    worsened = sum(
        1 for k, a in out.items()
        if a > 60.0 and k in ref and ref[k] <= 45.0
    )
    born_sharp = sum(
        1 for k, a in out.items() if a > 60.0 and k not in ref
    )
    return out, (worsened, born_sharp)


def _report(tag, q):
    _mark(
        f"[{tag}] aspect med={q['aspect_med']:.2f} p95={q['aspect_p95']:.2f} "
        f"max={q['aspect_max']:.1f} >4:{q['aspect_gt4']} >8:{q['aspect_gt8']} "
        f"edge mean={q['len_mean_mm']:.2f}mm max={q['len_max_mm']:.2f}mm "
        f"stretch max={q['stretch_max']:.2f} p95={q['stretch_p95']:.2f} "
        f">1.5x:{q['stretch_gt15']} >2x:{q['stretch_gt2']}"
    )


def _case(tag, painted, amount, radius=30.0, feather=10.0, smooth_iters=5):
    settings = bpy.context.scene.rigo_brace
    obj = _import_scan()
    me = obj.data
    if painted:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        frontier = [bm.verts[9000].link_faces[0]]
        selected = set(frontier)
        while len(selected) < 300 and frontier:
            nxt = []
            for f in frontier:
                for e in f.edges:
                    for lf in e.link_faces:
                        if lf not in selected:
                            selected.add(lf)
                            nxt.append(lf)
            frontier = nxt
        for f in selected:
            f.select = True
        bmesh.update_edit_mesh(me)
        settings.region_kind = "PRESSURE"
        settings.region_magnitude = amount
        settings.region_feather = feather
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add()
    else:
        bpy.context.scene.cursor.location = (
            obj.matrix_world @ me.vertices[9000].co
        )
        settings.region_radius = radius
        settings.region_magnitude = amount
        settings.region_kind = "PRESSURE"
        settings.region_falloff = "SMOOTH"
        bpy.ops.rigo.region_add_circle()
    region = obj.rigo_regions[obj.rigo_region_index]
    w = _weights(obj, region.surface_mask)
    fp = {i for i, wt in w.items() if wt > 1e-5}
    wall = {i for i, wt in w.items() if 0.15 < wt < 0.85}
    faces = [p for p in me.polygons if any(i in fp for i in p.vertices)]
    wall_faces = [p for p in me.polygons if any(i in wall for i in p.vertices)]
    q_pre = _quality(me, faces)
    qw_pre = _quality(me, wall_faces)
    dih_pre, spikes_pre = _spikes(obj, fp)
    _report(f"{tag}.pre.footprint", q_pre)
    _report(f"{tag}.pre.wall", qw_pre)

    st = bpy.ops.rigo.region_apply()
    if st != {"FINISHED"}:
        _mark(f"[{tag}] commit refused — case void")
        bpy.data.objects.remove(obj, do_unlink=True)
        return
    q_post = _quality(me, faces, q_pre["lengths"])
    qw_post = _quality(me, wall_faces, qw_pre["lengths"])
    _dih, new_spikes = _spikes(obj, fp, dih_pre)
    _report(f"{tag}.post.footprint", q_post)
    _report(f"{tag}.post.wall", qw_post)
    _mark(
        f"[{tag}] spikes: worsened_preexisting={new_spikes[0]} "
        f"born_sharp_new_edges={new_spikes[1]}"
    )

    # The user's follow-up: smooth the region (Laplacian, like sculpt
    # Smooth) and see whether the stretched wall spikes instead of relaxing.
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="VERT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(me)
    bm.verts.ensure_lookup_table()
    for i in fp:
        bm.verts[i].select = True
    bmesh.update_edit_mesh(me)
    bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=smooth_iters)
    bpy.ops.object.mode_set(mode="OBJECT")
    q_sm = _quality(me, faces, q_pre["lengths"])
    _dih, spikes_sm = _spikes(obj, fp, dih_pre)
    _report(f"{tag}.smoothed.footprint", q_sm)
    _mark(
        f"[{tag}] after smooth x{smooth_iters}: "
        f"worsened_preexisting={spikes_sm[0]} born_sharp={spikes_sm[1]}"
    )
    bpy.data.objects.remove(obj, do_unlink=True)


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.25
    try:
        _mark("phase=start")
        _case("paint15", painted=True, amount=15.0)
        _case("circle15", painted=False, amount=15.0)
        _case("circle25", painted=False, amount=25.0, radius=40.0)
        _mark("DONE")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}")
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
