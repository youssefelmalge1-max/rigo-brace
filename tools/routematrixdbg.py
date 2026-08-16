"""#49k Phase C/F — route matrix + ablation, on the A-model at 20 mm / 15 mm.

Phase C: run EVERY user workflow that can produce a correction and record, at
runtime, which field kernel and which refinement kernel each one reaches.

Phase F: on the user's own route (library style import), ablate the commit
stage — production, refinement disabled, and refinement fed a closed-form
chart field — to find what actually moves the final wall.

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/routematrixdbg.py
"""

import math
import os
import statistics
import subprocess
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

_OUT = r"C:\Projects\Blender Add-on Braces\routematrixdbg_result.txt"
_A_SCAN = r"C:\Projects\Blender Add-on Braces\A type model.stl"
_TMP_BLEND = os.path.join(
    r"C:\Users\youss\AppData\Local\Temp\claude"
    r"\c--Projects-Blender-Add-on-Braces"
    r"\46890c85-6fd9-484d-89f5-f065bbec0b43\scratchpad",
    "routematrix_reopen.blend",
)
_STYLE_V2 = "AUDIT 49k V2"
_STYLE_V1 = "AUDIT 49k V1"
_AMOUNT_MM = 20.0
_FEATHER_MM = 15.0
_TRIES = {"n": 0}
_log = []
_ROWS = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


# --------------------------------------------------------------------------- #
# observation
# --------------------------------------------------------------------------- #
_OBS = {}


def _install_probes(ro):
    def wrap(name, note):
        orig = getattr(ro, name)

        def wrapper(*a, **k):
            out = orig(*a, **k)
            try:
                note(a, k, out)
            except Exception:  # noqa: BLE001
                pass
            return out

        wrapper.__name__ = name
        setattr(ro, name, wrapper)

    wrap("_authored_rim_field",
         lambda a, k, out: _OBS.__setitem__(
             "rim_field", "FIELD" if out is not None else "REJECTED"))
    wrap("_refine_footprint",
         lambda a, k, out: _OBS.update({
             "refine": ("FIELD(#49e)"
                        if (k.get("field", a[5] if len(a) > 5 else None)
                            is not None) else "IDW+HARMONIC"),
             "refine_added": out[0] if isinstance(out, tuple) else out,
         }))
    wrap("_weights_from_style",
         lambda a, k, out: _OBS.__setitem__(
             "field_kernel",
             "BILINEAR GRID v2" if (a[1].get("field")) else "IDW SAMPLES v1"))
    wrap("_region_weights_from_selection",
         lambda a, k, out: _OBS.__setitem__(
             "field_kernel", "RIM-CURVE DISTANCE (#49e)"))
    wrap("_geodesic_trim",
         lambda a, k, out: _OBS.__setitem__("geodesic_fade", "YES"))


# --------------------------------------------------------------------------- #
# measurement
# --------------------------------------------------------------------------- #
def _group_weights(obj, mask):
    vg = obj.vertex_groups.get(mask)
    if vg is None:
        return {}
    gi = vg.index
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi:
                out[v.index] = g.weight
                break
    return out


def _pct(values, fraction):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * fraction))]


def _wall(obj, weights):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    angles = []
    ridge10 = 0
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        a, b = e.verts[0].index, e.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        try:
            angles.append(math.degrees(abs(e.calc_face_angle())))
            if math.degrees(e.calc_face_angle_signed()) > 10.0:
                ridge10 += 1
        except ValueError:
            continue
    bm.free()
    if not angles:
        return {"n": 0, "mean": 0.0, "p95": 0.0, "max": 0.0,
                "over30": 0, "ridge10": 0}
    return {
        "n": len(angles),
        "mean": statistics.fmean(angles),
        "p95": _pct(angles, 0.95),
        "max": max(angles),
        "over30": sum(1 for a in angles if a > 30.0),
        "ridge10": ridge10,
    }


def _row(route, stats, note=""):
    _ROWS.append((route, dict(_OBS), stats, note))
    _mark(
        f"ROUTE {route:26s} field={_OBS.get('field_kernel', '-'):26s} "
        f"rim={_OBS.get('rim_field', '-'):9s} "
        f"refine={_OBS.get('refine', '-'):14s} "
        f"(+{_OBS.get('refine_added', 0):3d}) "
        f"fade={_OBS.get('geodesic_fade', 'no'):3s} | "
        f"p95={stats['p95']:6.2f} max={stats['max']:6.2f} "
        f"over30={stats['over30']:3d} ridge10={stats['ridge10']:3d} {note}"
    )


# --------------------------------------------------------------------------- #
# fixture
# --------------------------------------------------------------------------- #
def _clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


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


def _paint_radius(obj, seed_index, radius_m):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    origin = bm.verts[seed_index].co.copy()
    for f in bm.faces:
        if (f.calc_center_median() - origin).length <= radius_m:
            f.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


def _settings():
    s = bpy.context.scene.rigo_brace
    s.region_kind = "PRESSURE"
    s.region_magnitude = _AMOUNT_MM
    s.region_feather = _FEATHER_MM
    s.region_falloff = "SMOOTH"
    return s


def _entry_by_label(lib, label):
    for entry in lib.load_library(force=True):
        if entry.get("label") == label:
            return entry
    return None


def _paint_region(obj):
    """Author a painted region at the waist; leaves OBJECT mode."""
    seed = _waist_seed(obj)
    _settings()
    _paint_radius(obj, seed, 0.030)
    bpy.ops.rigo.region_add()
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj.rigo_regions[obj.rigo_region_index], seed


# --------------------------------------------------------------------------- #
# chart field (Phase F arm C) — the closed form a library style DOES have
# --------------------------------------------------------------------------- #
def _chart_field(ro, scan, entry, target_world, normal):
    side, up, outward = ro._surface_frame(normal)
    grid = entry.get("field")
    samples = entry["samples"]
    tolerance = max(5.0, float(entry.get("normal_tolerance_mm", 15.0)))
    matrix = scan.matrix_world
    tree = None
    support = eps2 = 0.0
    if grid is None:
        spacing = max(0.5, float(entry.get("sample_radius_mm", 3.0)) / 1.75)
        support = spacing * 2.5
        eps2 = (spacing * 0.35) ** 2
        tree = kdtree.KDTree(len(samples))
        for i, s in enumerate(samples):
            tree.insert((s[0], s[1], 0.0), i)
        tree.balance()

    field_weight = getattr(ro._field_weight, "__wrapped__", ro._field_weight)
    idw_weight = getattr(ro._idw_weight, "__wrapped__", ro._idw_weight)

    def sample(co_local):
        relative = matrix @ co_local - target_world
        offset = abs(relative.dot(outward)) * 1000.0
        if offset >= tolerance * 2.0:
            return 0.0
        u = relative.dot(side) * 1000.0
        v = relative.dot(up) * 1000.0
        if grid is not None:
            w = field_weight(grid, u, v)
        else:
            w = idw_weight(samples, tree, u, v, support, eps2)
        if offset > tolerance:
            t = 1.0 - (offset - tolerance) / tolerance
            w *= t * t * (3.0 - 2.0 * t)
        return max(0.0, min(1.0, w))

    return sample


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
def _author_styles(lib):
    """Author one v2 style (grid) and one v1 style (samples only, grid
    stripped — exactly what an entry saved by an older build looks like)."""
    _clear()
    obj = _import_scan()
    region, _seed = _paint_region(obj)
    bpy.ops.rigo.region_apply()
    bpy.ops.rigo.region_style_save(style_name=_STYLE_V2)
    v2 = _entry_by_label(lib, _STYLE_V2)
    if v2 is None:
        _mark("  style save FAILED")
        return None, None
    legacy = {k: v for k, v in v2.items() if k != "field"}
    legacy["id"] = "AUDIT_49K_V1"
    legacy["label"] = _STYLE_V1
    legacy["schema_version"] = 1
    legacy.pop("max_geodesic_mm", None)
    lib.upsert_entry(legacy)
    _mark(
        f"  authored v2 grid_cell={v2['field']['cell_mm']}mm "
        f"{v2['field']['nx']}x{v2['field']['ny']}; v1 = same entry, grid and "
        f"max_geodesic_mm stripped ({len(legacy['samples'])} samples)"
    )
    _clear()
    return v2, _entry_by_label(lib, _STYLE_V1)


def _import_route(lib, label, tag):
    _clear()
    obj = _import_scan()
    seed = _waist_seed(obj)
    bpy.context.scene.cursor.location = obj.matrix_world @ obj.data.vertices[seed].co
    entry = _entry_by_label(lib, label)
    _settings().region_style = entry["id"]
    _OBS.clear()
    if "FINISHED" not in bpy.ops.rigo.region_style_import():
        _mark(f"  {tag}: import refused")
        return None
    region = obj.rigo_regions[obj.rigo_region_index]
    bpy.ops.rigo.region_apply()
    _row(tag, _wall(obj, _group_weights(obj, region.surface_mask)))
    return obj, region


def _route_painted():
    _clear()
    obj = _import_scan()
    _OBS.clear()
    region, _seed = _paint_region(obj)
    bpy.ops.rigo.region_apply()
    _row("painted new region", _wall(obj, _group_weights(obj, region.surface_mask)))


def _route_circle():
    _clear()
    obj = _import_scan()
    seed = _waist_seed(obj)
    settings = _settings()
    settings.region_radius = 30.0
    bpy.context.scene.cursor.location = obj.matrix_world @ obj.data.vertices[seed].co
    _OBS.clear()
    _OBS["field_kernel"] = "SEED-VERTEX DIJKSTRA"
    bpy.ops.rigo.region_add_circle()
    region = obj.rigo_regions[obj.rigo_region_index]
    bpy.ops.rigo.region_apply()
    _row("circular new region", _wall(obj, _group_weights(obj, region.surface_mask)))


def _route_mirror(lib):
    result = _import_route(lib, _STYLE_V2, "mirrored style (import)")
    if result is None:
        return
    obj, region = result
    _OBS.clear()
    _OBS["field_kernel"] = "(mirror of imported)"
    res = bpy.ops.rigo.region_mirror()
    if "FINISHED" not in res:
        _mark(f"  mirror refused: {res}")
        return
    mirrored = obj.rigo_regions[obj.rigo_region_index]
    res = bpy.ops.rigo.region_apply()
    if "FINISHED" not in res:
        _mark(f"  mirror commit refused: {res}")
        return
    _row("mirrored style (commit)",
         _wall(obj, _group_weights(obj, mirrored.surface_mask)))


def _route_reopen(lib):
    """Author a region, save the .blend, reopen it in this session and commit —
    the 'reopened .blend with an existing region' row.  NOT cross-version
    evidence (same build authored and read it); that gap stays open."""
    _clear()
    obj = _import_scan()
    region, _seed = _paint_region(obj)
    mask = region.surface_mask
    bpy.ops.wm.save_as_mainfile(filepath=_TMP_BLEND)
    bpy.ops.wm.open_mainfile(filepath=_TMP_BLEND)
    obj = bpy.context.scene.rigo_brace.scan_object
    if obj is None:
        _mark("  reopen: scan_object lost")
        return
    region = obj.rigo_regions[obj.rigo_region_index]
    _OBS.clear()
    _OBS["field_kernel"] = "(reopened, weights from file)"
    bpy.ops.rigo.region_apply()
    _row("reopened .blend region", _wall(obj, _group_weights(obj, mask)))


# --------------------------------------------------------------------------- #
# Phase F ablation on the user's own route
# --------------------------------------------------------------------------- #
def _ablate(ro, lib):
    _mark("")
    _mark("=== PHASE F — ablation on the USER'S route (library v2 import) ===")
    entry = _entry_by_label(lib, _STYLE_V2)
    real_refine = ro._refine_footprint

    def arm(tag, patch):
        _clear()
        obj = _import_scan()
        seed = _waist_seed(obj)
        cursor = obj.matrix_world @ obj.data.vertices[seed].co
        bpy.context.scene.cursor.location = cursor
        _settings().region_style = entry["id"]
        _OBS.clear()
        if "FINISHED" not in bpy.ops.rigo.region_style_import():
            _mark(f"  {tag}: import refused")
            return
        region = obj.rigo_regions[obj.rigo_region_index]
        _target, normal = ro._target_surface(obj, cursor)
        restore = patch(ro, obj, entry, cursor, normal)
        try:
            bpy.ops.rigo.region_apply()
        finally:
            if restore is not None:
                ro._refine_footprint = restore
        stats = _wall(obj, _group_weights(obj, region.surface_mask))
        _mark(
            f"  ABLATION {tag:34s} p95={stats['p95']:6.2f} "
            f"max={stats['max']:6.2f} over30={stats['over30']:3d} "
            f"ridge10={stats['ridge10']:3d} n={stats['n']}"
        )

    def production(*_a):
        return None

    def no_refinement(ro_, *_a):
        def stub(*a, **k):
            return 0, 0.0
        ro_._refine_footprint = stub
        return real_refine

    def chart_field(ro_, obj, entry_, cursor, normal):
        sampler = _chart_field(ro_, obj, entry_, cursor, normal)

        def forced(temp_me, group_index, offset, curved=True, harmonic=True,
                   field=None):
            return real_refine(temp_me, group_index, offset, curved=curved,
                               harmonic=harmonic, field=sampler)

        ro_._refine_footprint = forced
        return real_refine

    arm("production (IDW+harmonic)", production)
    arm("refinement disabled", no_refinement)
    arm("refinement fed the chart field", chart_field)


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    t_all = time.perf_counter()
    lib = None
    try:
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops")
        lib = importlib.import_module(
            "bl_ext.user_default.rigo_brace.core.region_library")
        try:
            head = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=r"C:\Projects\Blender Add-on Braces",
                capture_output=True, text=True, timeout=10,
            ).stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001
            head = "unknown"
        _mark(f"build={head} blender={bpy.app.version_string}")
        _mark("=== authoring fixture styles ===")
        _author_styles(lib)
        _install_probes(ro)
        _mark("")
        _mark("=== PHASE C — route matrix (runtime-observed kernels) ===")
        _route_painted()
        _route_circle()
        _import_route(lib, _STYLE_V2, "library style v2 (USER)")
        _import_route(lib, _STYLE_V1, "library style v1 (legacy)")
        _route_mirror(lib)
        _ablate(ro, lib)
        # LAST: open_mainfile resets the context and every bpy.ops that needs a
        # window poll fails afterwards inside a timer callback.
        _route_reopen(lib)
        _mark(f"total_time={time.perf_counter() - t_all:.1f}s")
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        if lib is not None:
            try:
                removed = []
                for entry in list(lib.load_library(force=True)):
                    if entry.get("label") in (_STYLE_V2, _STYLE_V1):
                        lib.delete_entry(entry["id"])
                        removed.append(entry["id"])
                _mark(f"audit styles removed: {removed}")
            except Exception:  # noqa: BLE001
                pass
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
