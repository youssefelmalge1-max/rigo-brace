"""Route-specific end-to-end gates for Pressure/Expansion (#49k).

The #49k audit proved that a painted-path test is NOT evidence for any other
route: of six user workflows that can produce a correction, only the painted
one reached the #49e field, and the whole battery painted.  This suite holds
one permanent end-to-end gate per production route with different authoring or
field semantics.  First and foremost:

    golden_user_pressure
        Library Style v2 -> A-model / coarse torso -> 20 mm -> Feather 15 mm
        -> Commit -> Smooth Area

the orthotist's actual clinical workflow, reproduced button for button.

The oracle is deliberately NOT derived from any production helper.  Wall
quality is measured two independent ways:

  * mesh dihedrals across the transition band (the established #48/#49 metric,
    comparable with every previous number in the decision log), and
  * the REALIZED CORRECTION DEPTH the orthotist actually feels - each committed
    vertex's distance to the ORIGINAL surface, read off a BVH of the
    pre-commit mesh - from which two production-independent defect detectors
    are computed:
      - wall bumps: interior wall vertices that are strict local extrema of
        realized depth among their wall neighbours (literal speed bumps and
        dimples), and
      - ring roughness: the oscillation of realized depth around an
        iso-distance ring through the wall - a smooth wall is near-constant
        around the ring, a pleated one undulates.  This is the "crown of
        radial pleats" in the orthotist's screenshots, measured in mm.

The style fixture is IMMUTABLE: tests/fixtures/style_v2_golden.json, authored
once and committed, so the gate cannot drift when the painted authoring path
changes.  A missing fixture is bootstrapped and written on first run.

GUI Blender only:
  & blender.exe --app-template rigo_brace --python tools/goldenroutetest.py
"""

import json
import math
import os
import statistics
import subprocess
import sys
import time
import traceback

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quality_contract

_ROOT = r"C:\Projects\Blender Add-on Braces"
_OUT = os.path.join(_ROOT, "goldenroutetest_result.txt")
_A_SCAN = os.path.join(_ROOT, "A type model.stl")
_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "style_v2_golden.json")
_STYLE_LABEL = "GOLDEN User Pressure"
_AMOUNT_MM = 20.0
_FEATHER_MM = 15.0
_PAINT_RADIUS_M = 0.030
_TRIES = {"n": 0}
_log = []
_GATES = {}
_T = None


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _gate(name, ok, detail=""):
    _GATES[name] = bool(ok)
    _mark(f"GATE {name}={'ok' if ok else 'FAIL'} {detail}")


# --------------------------------------------------------------------------- #
# scene helpers
# --------------------------------------------------------------------------- #
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
    """The lateral waist vertex - where the orthotist places the pad."""
    me = obj.data
    zs = [v.co.z for v in me.vertices]
    zmin, zmax = min(zs), max(zs)
    target_z = zmin + 0.45 * (zmax - zmin)
    band = [v for v in me.vertices if abs(v.co.z - target_z) < 0.01]
    if not band:
        band = list(me.vertices)
    return max(band, key=lambda v: v.co.x).index


def _settings():
    settings = bpy.context.scene.rigo_brace
    settings.region_kind = "PRESSURE"
    settings.region_magnitude = _AMOUNT_MM
    settings.region_feather = _FEATHER_MM
    settings.region_falloff = "SMOOTH"
    return settings


def _paint_radius(obj, seed_index, radius_m):
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    origin = bm.verts[seed_index].co.copy()
    for face in bm.faces:
        if (face.calc_center_median() - origin).length <= radius_m:
            face.select = True
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)


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


def _select_footprint(obj, weights):
    """Re-select the committed footprint, as the orthotist does with Paint Area
    before pressing Smooth Area."""
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    count = 0
    for face in bm.faces:
        if all(weights.get(v.index, 0.0) > 0.05 for v in face.verts):
            face.select = True
            count += 1
    bm.select_flush_mode()
    bmesh.update_edit_mesh(obj.data)
    return count


# --------------------------------------------------------------------------- #
# measurement - production-independent
# --------------------------------------------------------------------------- #
def _pct(values, fraction):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * fraction))]


def _wall_dihedrals(obj, weights):
    """Established metric: dihedral angles across the transition band."""
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
        "n": len(angles),
        "mean": statistics.fmean(angles) if angles else 0.0,
        "p95": _pct(angles, 0.95),
        "max": max(angles) if angles else 0.0,
        "over30": sum(1 for a in angles if a > 30.0),
        "ridge10": ridge10,
    }


def _realized_depth(obj, pre_mesh):
    """Realized correction depth per committed vertex: distance to the ORIGINAL
    surface.  This is the quantity the orthotist feels; it is read from a BVH
    of the pre-commit mesh and owes nothing to the production field."""
    tree = BVHTree.FromPolygons(
        [v.co.copy() for v in pre_mesh.vertices],
        [tuple(p.vertices) for p in pre_mesh.polygons],
        all_triangles=False,
    )
    depth = {}
    for vertex in obj.data.vertices:
        hit, _normal, _index, dist = tree.find_nearest(vertex.co)
        if hit is not None:
            depth[vertex.index] = dist * 1000.0
    return depth


def _wall_band(obj, weights):
    """Interior wall vertices and their wall-only adjacency."""
    member = {i for i, w in weights.items() if 0.05 < w < 0.95}
    adjacency = {i: [] for i in member}
    for edge in obj.data.edges:
        a, b = edge.vertices
        if a in member and b in member:
            adjacency[a].append(b)
            adjacency[b].append(a)
    interior = {i for i in member if len(adjacency[i]) >= 3}
    return member, adjacency, interior


def _wall_bumps(adjacency, interior, depth):
    """Fraction of interior wall vertices that are STRICT local extrema of
    realized depth among their wall neighbours - literal speed bumps and
    dimples in the transition.  A monotone wall has almost none; a pleated
    one is full of them."""
    if not interior:
        return 0.0, 0
    extrema = 0
    for i in interior:
        di = depth.get(i)
        if di is None:
            continue
        neighbours = [depth[j] for j in adjacency[i] if j in depth]
        if len(neighbours) < 3:
            continue
        if di > max(neighbours) + 1e-6 or di < min(neighbours) - 1e-6:
            extrema += 1
    return extrema / float(len(interior)), extrema


def _ring_roughness(obj, region, weights, member, depth):
    """Oscillation of realized depth AROUND the wall, in mm.

    Takes the vertices in the middle of the transition band, orders them
    circumferentially in the region's own tangent frame, and returns the median
    absolute second difference of realized depth along that ring.  A smooth
    conical wall is near-constant around the ring (small value); the 'crown of
    radial pleats' in the orthotist's screenshots is exactly an oscillation
    here."""
    if len(member) < 12:
        return 0.0, 0
    weights_mid = [
        i for i in member
        if i in depth and 0.35 < weights.get(i, 0.0) < 0.65
    ]
    if len(weights_mid) < 8:
        return 0.0, 0
    normal = Vector(region.direction).normalized()
    centre = Vector(region.center)
    helper = Vector((0.0, 0.0, 1.0))
    if abs(normal.dot(helper)) > 0.9:
        helper = Vector((1.0, 0.0, 0.0))
    side = normal.cross(helper).normalized()
    up = normal.cross(side).normalized()
    ordered = []
    for i in weights_mid:
        rel = obj.data.vertices[i].co - centre
        ordered.append((math.atan2(rel.dot(up), rel.dot(side)), depth[i]))
    ordered.sort()
    values = [d for _angle, d in ordered]
    if len(values) < 8:
        return 0.0, 0
    seconds = [
        abs(values[k - 1] - 2.0 * values[k] + values[(k + 1) % len(values)])
        for k in range(len(values))
    ]
    return statistics.median(seconds), len(values)


def _normal_residual(obj, weights):
    """High-frequency residual of the NORMAL field across the transition wall.

    Smooth shading displays the normal field; a 'crown of radial pleats' is
    precisely a high-frequency wobble in it.  For each wall vertex this is the
    angle between its own normal and the mean normal of its 2-ring - a
    low-pass residual, in degrees.  Production-independent: computed from the
    committed mesh alone.
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    wall = [
        v for v in bm.verts
        if 0.05 < weights.get(v.index, 0.0) < 0.95
    ]
    residuals = []
    for vertex in wall:
        ring = set()
        for edge in vertex.link_edges:
            other = edge.other_vert(vertex)
            ring.add(other)
            for edge2 in other.link_edges:
                ring.add(edge2.other_vert(other))
        ring.discard(vertex)
        if len(ring) < 4:
            continue
        mean = Vector()
        for other in ring:
            mean += other.normal
        if mean.length < 1e-9:
            continue
        mean.normalize()
        dot = max(-1.0, min(1.0, vertex.normal.normalized().dot(mean)))
        residuals.append(math.degrees(math.acos(dot)))
    bm.free()
    if not residuals:
        return {"n": 0, "median": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "n": len(residuals),
        "median": statistics.median(residuals),
        "p95": _pct(residuals, 0.95),
        "max": max(residuals),
    }


def _measure(obj, region, weights, pre_mesh, tag):
    dih = _wall_dihedrals(obj, weights)
    depth = _realized_depth(obj, pre_mesh)
    member, adjacency, interior = _wall_band(obj, weights)
    bump_frac, bumps = _wall_bumps(adjacency, interior, depth)
    ring, ring_n = _ring_roughness(obj, region, weights, member, depth)
    shading = _normal_residual(obj, weights)
    core = [depth[i] for i, w in weights.items() if w > 0.95 and i in depth]
    stats = {
        "dih_n": dih["n"], "p95": dih["p95"], "max": dih["max"],
        "over30": dih["over30"], "ridge10": dih["ridge10"],
        "bump_frac": bump_frac, "bumps": bumps, "wall_interior": len(interior),
        "ring_mm": ring, "ring_n": ring_n,
        "shade_med": shading["median"], "shade_p95": shading["p95"],
        "shade_max": shading["max"], "shade_n": shading["n"],
        "core_depth_mm": statistics.median(core) if core else 0.0,
    }
    _mark(
        f"  MEASURE[{tag}] p95={stats['p95']:6.2f} max={stats['max']:6.2f} "
        f"over30={stats['over30']:3d} ridge10={stats['ridge10']:3d} | "
        f"shade med={shading['median']:5.2f} p95={shading['p95']:6.2f} "
        f"max={shading['max']:6.2f} | "
        f"bumps={bump_frac * 100:4.1f}% ring={ring:5.3f}mm "
        f"core={stats['core_depth_mm']:5.2f}mm"
    )
    return stats


# --------------------------------------------------------------------------- #
# the immutable style fixture
# --------------------------------------------------------------------------- #
def _bootstrap_fixture(lib):
    """Author the v2 style once (paint -> commit -> Save as Reusable Style) and
    freeze it to tests/fixtures/ so the gate can never drift with the painted
    authoring path."""
    _mark("  fixture missing - bootstrapping from a painted authoring pass")
    _clear()
    obj = _import_scan()
    seed = _waist_seed(obj)
    _settings()
    _paint_radius(obj, seed, _PAINT_RADIUS_M)
    bpy.ops.rigo.region_add()
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.rigo.region_apply()
    bpy.ops.rigo.region_style_save(style_name=_STYLE_LABEL)
    entry = None
    for candidate in lib.load_library(force=True):
        if candidate.get("label") == _STYLE_LABEL:
            entry = candidate
            break
    if entry is None:
        raise RuntimeError("could not author the golden style fixture")
    entry = dict(entry)
    entry["id"] = "GOLDEN_USER_PRESSURE"
    os.makedirs(os.path.dirname(_FIXTURE), exist_ok=True)
    with open(_FIXTURE, "w", encoding="utf-8") as fh:
        json.dump(entry, fh, indent=1, sort_keys=True)
    _mark(f"  fixture written: {_FIXTURE}")
    for candidate in list(lib.load_library(force=True)):
        if candidate.get("label") == _STYLE_LABEL:
            lib.delete_entry(candidate["id"])
    _clear()
    return entry


def _load_fixture(lib):
    if not os.path.exists(_FIXTURE):
        return _bootstrap_fixture(lib)
    with open(_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# the golden route
# --------------------------------------------------------------------------- #
def _run_library_route(lib, entry):
    """Library Style v2 -> import at cursor -> Commit -> Smooth Area."""
    _clear()
    obj = _import_scan()
    seed = _waist_seed(obj)
    cursor = obj.matrix_world @ obj.data.vertices[seed].co
    bpy.context.scene.cursor.location = cursor
    lib.upsert_entry(dict(entry))
    settings = _settings()
    settings.region_style = entry["id"]

    result = bpy.ops.rigo.region_style_import()
    if "FINISHED" not in result:
        _gate("golden_user_pressure.import", False, f"import -> {result}")
        return None
    _gate("golden_user_pressure.import", True)
    region = obj.rigo_regions[obj.rigo_region_index]
    weights = _group_weights(obj, region.surface_mask)
    pre_mesh = obj.data.copy()

    _gate(
        "golden_user_pressure.amount_is_the_style_amount",
        abs(region.magnitude_mm - _AMOUNT_MM) < 1e-6,
        f"amount={region.magnitude_mm}",
    )

    t0 = time.perf_counter()
    result = bpy.ops.rigo.region_apply()
    commit_s = time.perf_counter() - t0
    if "FINISHED" not in result:
        _gate("golden_user_pressure.commit", False, f"commit -> {result}")
        bpy.data.meshes.remove(pre_mesh)
        return None
    _gate("golden_user_pressure.commit", True, f"{commit_s:.2f}s")
    committed = _group_weights(obj, region.surface_mask)
    after_commit = _measure(obj, region, committed, pre_mesh, "L commit")

    selected = _select_footprint(obj, committed)
    result = bpy.ops.rigo.smooth_selection()
    bpy.ops.object.mode_set(mode="OBJECT")
    _gate(
        "golden_user_pressure.smooth_area_acts",
        "FINISHED" in result,
        f"faces={selected} -> {result}",
    )
    after_smooth = _measure(obj, region, committed, pre_mesh, "L smooth")

    bpy.data.meshes.remove(pre_mesh)
    return {"commit": after_commit, "smooth": after_smooth}


def _run_painted_route():
    """The painted route at the same place with the same numbers - the parity
    reference.  It is a PRODUCTION output, not an oracle: it says what this
    body, amount and feather can already achieve on a route that owns its
    field."""
    _clear()
    obj = _import_scan()
    seed = _waist_seed(obj)
    _settings()
    _paint_radius(obj, seed, _PAINT_RADIUS_M)
    if "FINISHED" not in bpy.ops.rigo.region_add():
        return None
    bpy.ops.object.mode_set(mode="OBJECT")
    region = obj.rigo_regions[obj.rigo_region_index]
    pre_mesh = obj.data.copy()
    if "FINISHED" not in bpy.ops.rigo.region_apply():
        bpy.data.meshes.remove(pre_mesh)
        return None
    committed = _group_weights(obj, region.surface_mask)
    after_commit = _measure(obj, region, committed, pre_mesh, "P commit")
    _select_footprint(obj, committed)
    bpy.ops.rigo.smooth_selection()
    bpy.ops.object.mode_set(mode="OBJECT")
    after_smooth = _measure(obj, region, committed, pre_mesh, "P smooth")
    bpy.data.meshes.remove(pre_mesh)
    return {"commit": after_commit, "smooth": after_smooth}


def _quad_scan_route():
    """Route gate (#49m): Remesh -> Paint -> Commit on a QUAD scan.

    The Mesh stage's Remesh emits 100 % quads and the Exoside Quad Remesher's
    output is adopted verbatim, so the patient scan is routinely not
    triangles.  Commit used to die with `ValueError: non triangle found`
    inside BVHTree.FromPolygons — a Python traceback in the orthotist's face
    on an ordinary workflow.  No suite committed anything on a quad mesh.
    """
    _clear()
    obj = _import_scan()
    result = bpy.ops.rigo.remesh()
    obj = bpy.context.scene.rigo_brace.scan_object
    mix = {}
    for poly in obj.data.polygons:
        mix[len(poly.vertices)] = mix.get(len(poly.vertices), 0) + 1
    non_tri = sum(n for k, n in mix.items() if k != 3)
    _gate(
        "quad_scan.remesh_really_makes_quads",
        non_tri > 0,
        f"remesh -> {result} faces={mix}",
    )
    seed = _waist_seed(obj)
    _settings()
    _paint_radius(obj, seed, _PAINT_RADIUS_M)
    if "FINISHED" not in bpy.ops.rigo.region_add():
        _gate("quad_scan.region_add", False)
        return
    _gate("quad_scan.region_add", True)
    bpy.ops.object.mode_set(mode="OBJECT")
    region = obj.rigo_regions[obj.rigo_region_index]
    pre_mesh = obj.data.copy()
    try:
        result = bpy.ops.rigo.region_apply()
        raised = ""
    except Exception as exc:  # noqa: BLE001
        result = "RAISED"
        raised = str(exc).strip().splitlines()[-1][:160]
    _gate(
        "quad_scan.commit_does_not_crash",
        result != "RAISED",
        f"{result} {raised}",
    )
    if result == "RAISED":
        bpy.data.meshes.remove(pre_mesh)
        return
    _gate(
        "quad_scan.commit_finished",
        "FINISHED" in result,
        f"commit -> {result}",
    )
    if "FINISHED" in result:
        committed = _group_weights(obj, region.surface_mask)
        stats = _measure(obj, region, committed, pre_mesh, "QUAD commit")
        _gate(
            "quad_scan.core_depth",
            stats["core_depth_mm"] >= _AMOUNT_MM * 0.90,
            f"core={stats['core_depth_mm']:.2f}mm of {_AMOUNT_MM}mm",
        )
    bpy.data.meshes.remove(pre_mesh)


def _apply_gates(library, painted):
    # Diagnostics that were BUILT as independent defect detectors and REJECTED
    # on measurement: both rate the defective library route BETTER than the
    # painted one, because they are dominated by the coarse torso's own
    # triangulation rather than by the defect.  Printed so the next reader does
    # not mistake them for coverage; deliberately not gated.
    _mark(
        "  DIAGNOSTIC (not gated, does not discriminate): "
        f"bump_frac L={library['commit']['bump_frac'] * 100:.1f}% "
        f"P={painted['commit']['bump_frac'] * 100:.1f}% | "
        f"ring L={library['commit']['ring_mm']:.3f}mm "
        f"P={painted['commit']['ring_mm']:.3f}mm | "
        f"shade_median L={library['commit']['shade_med']:.2f} "
        f"P={painted['commit']['shade_med']:.2f}"
        if painted else "  DIAGNOSTIC: painted reference unavailable"
    )
    golden = (_T or {}).get("golden")
    if not golden:
        _mark("")
        _mark("NO 'golden' SECTION IN THE CONTRACT - measurement run only, "
              "no gates evaluated.  Add thresholds and re-run.")
        return
    commit = library["commit"]
    _gate(
        "golden_user_pressure.wall_p95",
        commit["p95"] <= golden["commit_wall_p95_max"],
        f"p95={commit['p95']:.2f} ceiling={golden['commit_wall_p95_max']}",
    )
    _gate(
        "golden_user_pressure.wall_max_dihedral",
        commit["max"] <= golden["commit_wall_max_deg"],
        f"max={commit['max']:.2f} ceiling={golden['commit_wall_max_deg']}",
    )
    _gate(
        "golden_user_pressure.wall_over30",
        commit["over30"] <= golden["commit_wall_over30_max"],
        f"over30={commit['over30']} ceiling={golden['commit_wall_over30_max']}",
    )
    _gate(
        "golden_user_pressure.shading_tail",
        commit["shade_max"] <= golden["commit_shade_max_deg"],
        f"shade_max={commit['shade_max']:.2f} "
        f"ceiling={golden['commit_shade_max_deg']}",
    )
    _gate(
        "golden_user_pressure.smooth_area_wall",
        library["smooth"]["p95"] <= golden["smooth_wall_p95_max"],
        f"post-smooth p95={library['smooth']['p95']:.2f} "
        f"ceiling={golden['smooth_wall_p95_max']}",
    )
    _gate(
        "golden_user_pressure.smooth_area_keeps_depth",
        library["smooth"]["core_depth_mm"]
        >= _AMOUNT_MM * golden["core_depth_min_frac"],
        f"post-smooth core={library['smooth']['core_depth_mm']:.2f}mm",
    )
    _gate(
        "golden_user_pressure.core_depth",
        commit["core_depth_mm"] >= _AMOUNT_MM * golden["core_depth_min_frac"],
        f"core={commit['core_depth_mm']:.2f}mm of {_AMOUNT_MM}mm",
    )
    if painted:
        ratio = (
            commit["p95"] / painted["commit"]["p95"]
            if painted["commit"]["p95"] > 1e-9 else 99.0
        )
        _gate(
            "golden_user_pressure.route_parity_with_painted",
            ratio <= golden["parity_p95_factor"],
            f"library/painted p95 = {commit['p95']:.2f}/"
            f"{painted['commit']['p95']:.2f} = {ratio:.2f} "
            f"ceiling={golden['parity_p95_factor']}",
        )


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 40:
        return 0.5
    global _T
    t_all = time.perf_counter()
    lib = None
    try:
        import importlib
        lib = importlib.import_module(
            "bl_ext.user_default.rigo_brace.core.region_library")
        try:
            _T = quality_contract.load()
        except Exception as exc:  # noqa: BLE001
            _mark(f"contract load failed: {exc!r}")
            _T = {}
        try:
            head = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT,
                capture_output=True, text=True, timeout=10,
            ).stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001
            head = "unknown"
        _mark(f"build={head} blender={bpy.app.version_string}")

        _mark("=== golden_user_pressure — Library Style v2 -> Commit -> Smooth ===")
        entry = _load_fixture(lib)
        grid = entry.get("field") or {}
        _mark(
            f"  fixture schema_v={entry.get('schema_version')} "
            f"kind={entry.get('kind')} amount={entry.get('magnitude_mm')}mm "
            f"grid={grid.get('nx')}x{grid.get('ny')}@{grid.get('cell_mm')}mm "
            f"samples={len(entry.get('samples', []))}"
        )
        _gate(
            "golden_user_pressure.fixture_is_schema_v2",
            entry.get("schema_version") == 2 and bool(grid),
            f"schema_version={entry.get('schema_version')}",
        )
        library = _run_library_route(lib, entry)
        _mark("")
        _mark("=== painted route parity reference (same body, same numbers) ===")
        painted = _run_painted_route()
        _mark("")
        _mark("=== quad_scan — Remesh -> Paint -> Commit on a QUAD mesh ===")
        _quad_scan_route()
        _mark("")
        if library:
            _apply_gates(library, painted)
        _mark("")
        _mark(f"total_time={time.perf_counter() - t_all:.1f}s")
        failed = [k for k, v in _GATES.items() if not v]
        _mark(f"failed_gates={failed}")
        _mark(f"PASS={not failed and len(_GATES) > 3}")
    except Exception as exc:  # noqa: BLE001
        _mark(f"ERROR={exc!r}\n{traceback.format_exc()}\nPASS=False")
    finally:
        if lib is not None:
            try:
                for candidate in list(lib.load_library(force=True)):
                    if candidate.get("label") == _STYLE_LABEL:
                        lib.delete_entry(candidate["id"])
            except Exception:  # noqa: BLE001
                pass
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
