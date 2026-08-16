"""#49k Phase A/B/D/E/F — execution audit of the REAL user workflow.

    Library Pressure -> Import at Cursor -> Commit -> Smooth Area

on the A-model at the user's parameters (20 mm amount, 15 mm feather), with the
INSTALLED production functions wrapped at runtime so every branch taken is
RECORDED, never inferred from a function name.  No production file is edited.

Route P (painted region) is run on an identical scan at the same waist location
so the two kernels can be compared directly on the same geometry.

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/userpathdbg.py
"""

import math
import os
import statistics
import subprocess
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, kdtree

_OUT = r"C:\Projects\Blender Add-on Braces\userpathdbg_result.txt"
_A_SCAN = r"C:\Projects\Blender Add-on Braces\A type model.stl"
_STYLE_LABEL = "AUDIT 49k Pressure"
_AMOUNT_MM = 20.0
_FEATHER_MM = 15.0
_TRIES = {"n": 0}
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _entry_by_label(lib, label):
    """Look an entry up by LABEL.  ``identifier_from_label`` mints a fresh
    unique id (appending _2 when the base is taken) — it is a generator, not
    a lookup, and using it as one silently misses the saved style."""
    for entry in lib.load_library(force=True):
        if entry.get("label") == label:
            return entry
    return None


# --------------------------------------------------------------------------- #
# instrumentation — wrap installed production functions, record every call
# --------------------------------------------------------------------------- #
_TRACE = []
_COUNT = {}
_ORIG = {}


def _count(key, n=1):
    _COUNT[key] = _COUNT.get(key, 0) + n


def _install_probes(ro, so):
    """Wrap the functions the audit must observe.  Each wrapper calls the real
    implementation — behaviour is unchanged, only observed."""

    def wrap(mod, name, note=None):
        orig = getattr(mod, name)
        _ORIG[name] = orig

        def wrapper(*a, **k):
            _count(f"call:{name}")
            out = orig(*a, **k)
            if note is not None:
                try:
                    note(a, k, out)
                except Exception as exc:  # noqa: BLE001
                    _TRACE.append(f"  [note {name} failed: {exc!r}]")
            return out

        wrapper.__name__ = name
        setattr(mod, name, wrapper)

    # --- the #49e curve-distance field (painted path only, we believe) ---
    def note_rim_field(a, k, out):
        _TRACE.append(
            f"  _authored_rim_field -> {'FIELD' if out is not None else 'None (REJECTED)'}"
        )
        _count("rim_field_returned" if out is not None else "rim_field_none")

    def note_boundary(a, k, out):
        _count("boundary_distance_calls")

    def note_refine(a, k, out):
        field = k.get("field", a[5] if len(a) > 5 else None)
        added = out[0] if isinstance(out, tuple) else out
        kind = "FIELD (#49e)" if field is not None else "IDW+HARMONIC (pre-#49e)"
        _TRACE.append(f"  _refine_footprint kernel={kind} verts_added={added}")
        _count("refine_field" if field is not None else "refine_idw")
        _COUNT["refine_verts_added"] = added

    def note_style_weights(a, k, out):
        entry = a[1]
        has_grid = bool(entry.get("field"))
        w = out[0] if isinstance(out, tuple) else out
        _TRACE.append(
            f"  _weights_from_style kernel="
            f"{'BILINEAR GRID v2' if has_grid else 'IDW SAMPLES v1'} "
            f"cell_mm={(entry.get('field') or {}).get('cell_mm')} "
            f"verts={len(w)}"
        )
        _count("style_grid" if has_grid else "style_idw")

    def note_sel_weights(a, k, out):
        _TRACE.append(f"  _region_weights_from_selection verts={len(out[0])}")
        _count("painted_field")

    def note_trim(a, k, out):
        w, realized = out
        _TRACE.append(
            f"  _geodesic_trim (Dijkstra fade) kept={len(w)} realized_mm={realized:.1f}"
        )
        _count("geodesic_trim")

    def note_repair(a, k, out):
        _TRACE.append(f"  _repair_folds remaining={len(out) if out else 0}")

    wrap(ro, "_authored_rim_field", note_rim_field)
    wrap(ro, "_boundary_distance", note_boundary)
    wrap(ro, "_refine_footprint", note_refine)
    wrap(ro, "_weights_from_style", note_style_weights)
    wrap(ro, "_region_weights_from_selection", note_sel_weights)
    wrap(ro, "_geodesic_trim", note_trim)
    wrap(ro, "_repair_folds", note_repair)
    # per-vertex kernels: count only
    wrap(ro, "_field_weight")
    wrap(ro, "_idw_weight")
    wrap(so, "_smooth_selection_hc")
    wrap(so, "_feathered_strength")


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


def _wall_stats(obj, weights, tag):
    """Dihedral statistics across the TRANSITION WALL (0.05<w<0.95) — the
    surface the orthotist actually looks at."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    angles = []
    ridge10 = ridge30 = 0
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        a, b = e.verts[0].index, e.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        try:
            unsigned = math.degrees(abs(e.calc_face_angle()))
            signed = math.degrees(e.calc_face_angle_signed())
        except ValueError:
            continue
        angles.append(unsigned)
        if signed > 10.0:
            ridge10 += 1
        if signed > 30.0:
            ridge30 += 1
    bm.free()
    if not angles:
        _mark(f"  WALL[{tag}] no wall edges")
        return {}
    stats = {
        "n": len(angles),
        "mean": statistics.fmean(angles),
        "p95": _pct(angles, 0.95),
        "max": max(angles),
        "over30": sum(1 for a in angles if a > 30.0),
        "ridge10": ridge10,
        "ridge30": ridge30,
    }
    _mark(
        f"  WALL[{tag}] n={stats['n']} mean={stats['mean']:.2f} "
        f"p95={stats['p95']:.2f} max={stats['max']:.2f} "
        f"over30={stats['over30']} ridge10={ridge10} ridge30={ridge30}"
    )
    return stats


def _predicted_wall(me, weights, offset, tag):
    """Phase D discriminator: displace the UNDISPLACED pre-commit mesh by the
    authored field alone (no refinement, no repair, no smoothing) and measure
    the wall.  Isolates the FIELD from every downstream stage — if the ridges
    are already here, they were authored, not introduced later."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        w = weights.get(v.index, 0.0)
        if w > 0.0:
            v.co = v.co + v.normal * (offset * w)
    angles = []
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        a, b = e.verts[0].index, e.verts[1].index
        wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
        if not (0.05 < wa < 0.95 and 0.05 < wb < 0.95):
            continue
        try:
            angles.append(math.degrees(abs(e.calc_face_angle())))
        except ValueError:
            continue
    bm.free()
    if not angles:
        _mark(f"  FIELD-ONLY[{tag}] no wall edges")
        return {}
    stats = {
        "n": len(angles),
        "mean": statistics.fmean(angles),
        "p95": _pct(angles, 0.95),
        "max": max(angles),
        "over30": sum(1 for a in angles if a > 30.0),
    }
    _mark(
        f"  FIELD-ONLY[{tag}] n={stats['n']} mean={stats['mean']:.2f} "
        f"p95={stats['p95']:.2f} max={stats['max']:.2f} over30={stats['over30']}"
    )
    return stats


# --------------------------------------------------------------------------- #
# fixture
# --------------------------------------------------------------------------- #
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
    """A lateral waist vertex — where the user places the pressure pad."""
    me = obj.data
    zs = [v.co.z for v in me.vertices]
    zmin, zmax = min(zs), max(zs)
    target_z = zmin + 0.45 * (zmax - zmin)
    band = [v for v in me.vertices if abs(v.co.z - target_z) < 0.01]
    if not band:
        band = list(me.vertices)
    return max(band, key=lambda v: v.co.x).index


def _paint_radius(obj, seed_index, radius_m):
    """Select every face whose centre lies within radius_m of the seed."""
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    origin = bm.verts[seed_index].co.copy()
    n = 0
    for f in bm.faces:
        if (f.calc_center_median() - origin).length <= radius_m:
            f.select = True
            n += 1
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    return n


def _select_footprint(obj, weights):
    """Re-select the committed footprint in Edit Mode, as the user does with
    Paint Area before pressing Smooth Area."""
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    n = 0
    for f in bm.faces:
        if all(weights.get(v.index, 0.0) > 0.05 for v in f.verts):
            f.select = True
            n += 1
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    return n


# --------------------------------------------------------------------------- #
# phases
# --------------------------------------------------------------------------- #
def _phase_a(ro, so, lib):
    _mark("=== PHASE A — runtime identity ===")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=r"C:\Projects\Blender Add-on Braces",
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        commit = "unknown"
    _mark(f"repo_head={commit}")
    _mark(f"blender={bpy.app.version_string}")
    _mark(f"region_ops.__file__={ro.__file__}")
    _mark(f"select_ops.__file__={so.__file__}")
    _mark(f"region_library.__file__={lib.__file__}")
    import hashlib
    for mod in (ro, so):
        with open(mod.__file__, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        _mark(f"loaded_sha256 {os.path.basename(mod.__file__)}={digest}")
    resident = sorted(
        m for m in sys.modules if "rigo" in m.lower()
    )
    _mark(f"resident_rigo_modules={len(resident)}")
    dupes = [m for m in resident if m.count("rigo_brace") > 1]
    _mark(f"duplicate_module_paths={dupes}")
    _mark(f"library_entries={[e.get('id') for e in lib.load_library(force=True)]}")


def _route_library(ro, so, lib):
    """The user's exact path: import a saved Pressure style, commit, smooth."""
    _mark("")
    _mark("=== ROUTE L — Library Pressure -> Import at Cursor -> Commit -> Smooth ===")
    obj = _import_scan()
    seed = _waist_seed(obj)
    cursor_world = obj.matrix_world @ obj.data.vertices[seed].co
    bpy.context.scene.cursor.location = cursor_world
    bpy.ops.object.mode_set(mode="OBJECT")

    settings = bpy.context.scene.rigo_brace
    entry = _entry_by_label(lib, _STYLE_LABEL)
    if entry is None:
        _mark("  audit style missing from library — cannot run ROUTE L")
        return None
    settings.region_style = entry["id"]
    _mark(f"  region_style={settings.region_style}")

    _TRACE.append("[UI] rigo.region_style_import")
    t0 = time.perf_counter()
    res = bpy.ops.rigo.region_style_import()
    _mark(f"  region_style_import -> {res} ({time.perf_counter() - t0:.2f}s)")
    if "FINISHED" not in res:
        return None
    region = obj.rigo_regions[obj.rigo_region_index]
    _mark(
        f"  region name={region.name!r} kind={region.kind} "
        f"amount={region.magnitude_mm:.1f}mm falloff={region.falloff_type} "
        f"mask={region.surface_mask}"
    )
    weights = _group_weights(obj, region.surface_mask)
    _mark(f"  authored verts={len(weights)}")

    pre_me = obj.data.copy()
    offset = -region.magnitude_mm * 0.001
    field_only = _predicted_wall(pre_me, weights, offset, "ROUTE L")

    _TRACE.append("[UI] rigo.region_apply")
    t0 = time.perf_counter()
    res = bpy.ops.rigo.region_apply()
    _mark(f"  region_apply -> {res} ({time.perf_counter() - t0:.2f}s)")
    committed = _group_weights(obj, region.surface_mask)
    after_commit = _wall_stats(obj, committed, "ROUTE L commit")

    n_sel = _select_footprint(obj, committed)
    _TRACE.append(f"[UI] rigo.smooth_selection (faces selected={n_sel})")
    res = bpy.ops.rigo.smooth_selection()
    _mark(f"  smooth_selection -> {res}")
    bpy.ops.object.mode_set(mode="OBJECT")
    after_smooth = _wall_stats(obj, committed, "ROUTE L smooth")

    bpy.data.meshes.remove(pre_me)
    return {"field_only": field_only, "commit": after_commit,
            "smooth": after_smooth, "obj": obj}


def _route_painted(ro, so):
    """The path every existing regression test exercises."""
    _mark("")
    _mark("=== ROUTE P — Paint Area -> Create Live Region -> Commit -> Smooth ===")
    obj = _import_scan()
    seed = _waist_seed(obj)
    settings = bpy.context.scene.rigo_brace
    settings.region_kind = "PRESSURE"
    settings.region_magnitude = _AMOUNT_MM
    settings.region_feather = _FEATHER_MM
    settings.region_falloff = "SMOOTH"
    n_faces = _paint_radius(obj, seed, 0.030)
    _mark(f"  painted faces={n_faces}")

    _TRACE.append("[UI] rigo.region_add")
    res = bpy.ops.rigo.region_add()
    _mark(f"  region_add -> {res}")
    if "FINISHED" not in res:
        return None
    bpy.ops.object.mode_set(mode="OBJECT")
    region = obj.rigo_regions[obj.rigo_region_index]
    weights = _group_weights(obj, region.surface_mask)
    _mark(f"  authored verts={len(weights)}")

    pre_me = obj.data.copy()
    offset = -region.magnitude_mm * 0.001
    field_only = _predicted_wall(pre_me, weights, offset, "ROUTE P")

    _TRACE.append("[UI] rigo.region_apply")
    t0 = time.perf_counter()
    res = bpy.ops.rigo.region_apply()
    _mark(f"  region_apply -> {res} ({time.perf_counter() - t0:.2f}s)")
    committed = _group_weights(obj, region.surface_mask)
    after_commit = _wall_stats(obj, committed, "ROUTE P commit")

    n_sel = _select_footprint(obj, committed)
    _TRACE.append(f"[UI] rigo.smooth_selection (faces selected={n_sel})")
    res = bpy.ops.rigo.smooth_selection()
    _mark(f"  smooth_selection -> {res}")
    bpy.ops.object.mode_set(mode="OBJECT")
    after_smooth = _wall_stats(obj, committed, "ROUTE P smooth")

    bpy.data.meshes.remove(pre_me)
    return {"field_only": field_only, "commit": after_commit,
            "smooth": after_smooth, "obj": obj}


def _author_style(ro, lib):
    """Author the reusable Pressure style once, exactly as the orthotist does:
    paint -> create -> commit -> Save as Reusable Style."""
    _mark("=== authoring the library style (paint -> commit -> save) ===")
    obj = _import_scan()
    seed = _waist_seed(obj)
    settings = bpy.context.scene.rigo_brace
    settings.region_kind = "PRESSURE"
    settings.region_magnitude = _AMOUNT_MM
    settings.region_feather = _FEATHER_MM
    settings.region_falloff = "SMOOTH"
    n = _paint_radius(obj, seed, 0.030)
    _mark(f"  painted faces={n}")
    res = bpy.ops.rigo.region_add()
    _mark(f"  region_add -> {res}")
    bpy.ops.object.mode_set(mode="OBJECT")
    res = bpy.ops.rigo.region_apply()
    _mark(f"  region_apply -> {res}")
    res = bpy.ops.rigo.region_style_save(style_name=_STYLE_LABEL)
    _mark(f"  region_style_save -> {res}")
    entry = _entry_by_label(lib, _STYLE_LABEL)
    if entry is None:
        _mark("  STYLE SAVE FAILED")
    else:
        grid = entry.get("field") or {}
        _mark(
            f"  saved entry schema_v={entry.get('schema_version')} "
            f"kind={entry.get('kind')} amount={entry.get('magnitude_mm')} "
            f"grid_cell_mm={grid.get('cell_mm')} grid={grid.get('nx')}x{grid.get('ny')} "
            f"samples={len(entry.get('samples', []))} "
            f"max_geodesic_mm={entry.get('max_geodesic_mm')}"
        )
    for o in list(bpy.data.objects):
        if o.type == "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    return entry


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    t_all = time.perf_counter()
    lib = None
    try:
        import importlib
        ro = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.region_ops"
        )
        so = importlib.import_module(
            "bl_ext.user_default.rigo_brace.operators.select_ops"
        )
        lib = importlib.import_module(
            "bl_ext.user_default.rigo_brace.core.region_library"
        )
        _phase_a(ro, so, lib)

        _author_style(ro, lib)

        _install_probes(ro, so)
        _mark("")
        _mark("probes installed (production behaviour unchanged, only observed)")

        _COUNT.clear()
        _TRACE.clear()
        route_l = _route_library(ro, so, lib)
        _mark("")
        _mark("--- ROUTE L trace ---")
        for line in _TRACE:
            _mark(line)
        _mark(f"--- ROUTE L counters --- {dict(sorted(_COUNT.items()))}")
        counts_l = dict(_COUNT)

        _COUNT.clear()
        _TRACE.clear()
        route_p = _route_painted(ro, so)
        _mark("")
        _mark("--- ROUTE P trace ---")
        for line in _TRACE:
            _mark(line)
        _mark(f"--- ROUTE P counters --- {dict(sorted(_COUNT.items()))}")
        counts_p = dict(_COUNT)

        _mark("")
        _mark("=== VERDICT ===")
        _mark(
            f"#49e curve-distance field ran on ROUTE L (user path)? "
            f"{'YES' if counts_l.get('refine_field') else 'NO'}"
        )
        _mark(
            f"#49e curve-distance field ran on ROUTE P (tested path)? "
            f"{'YES' if counts_p.get('refine_field') else 'NO'}"
        )
        if route_l and route_p:
            for stage in ("field_only", "commit", "smooth"):
                a = route_l.get(stage) or {}
                b = route_p.get(stage) or {}
                _mark(
                    f"  {stage:11s} L p95={a.get('p95', 0):6.2f} "
                    f"max={a.get('max', 0):6.2f} over30={a.get('over30', 0):4d} | "
                    f"P p95={b.get('p95', 0):6.2f} max={b.get('max', 0):6.2f} "
                    f"over30={b.get('over30', 0):4d}"
                )
        _mark(f"total_time={time.perf_counter() - t_all:.1f}s")
        _mark("DONE=True")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nDONE=False")
    finally:
        if lib is not None:
            try:
                removed = []
                for entry in list(lib.load_library(force=True)):
                    if entry.get("label") == _STYLE_LABEL:
                        lib.delete_entry(entry["id"])
                        removed.append(entry["id"])
                _mark(f"audit styles removed from the user's library: {removed}")
            except Exception:  # noqa: BLE001
                pass
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
