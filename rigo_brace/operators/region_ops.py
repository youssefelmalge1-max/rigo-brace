"""Guided sculpt — measurable CorrectionRegion push/pull (Patch 4a).

The clinical model (knowledge/correction_region_model.md, DEC-0014): a
correction is a data object stored on the brace mesh — anatomical label, kind
(pressure/expansion), centroid, mean surface normal, magnitude/radius in mm and
a falloff-weighted vertex group — never just "vertices someone moved".

Workflow: paint a region (the existing Edit-Mode face selection), press
"Add Region" (bakes the falloff weights), tune the mm amount, press "Apply".
Mirror creates the coupled opposite-side region (Rigo pressure/expansion pair).
Concept inspired by uFit's push_pull_region (GPL-3.0, PROV-0004) — clean
original implementation.
"""

import heapq
import json
import math

import bpy
import bmesh
import numpy as np
from bpy.props import StringProperty
from bpy.types import Operator
from mathutils import Matrix, Vector, kdtree

from ..core import (
    CORSET_BASE_NAME,
    DEFORM_MODIFIER,
    mark_brace_dirty,
    region_library,
)


_PREVIEW_PREFIX = "RIGO_REGION_PREVIEW_"
_MASK_EDGE_WEIGHT = 1e-6
# Undisplaced tangent-frame snapshot of each region, stored on the object at
# bake time so "Save Committed Style" never samples the deformed surface (#48).
_SNAPSHOT_PREFIX = "rigo_style_src_"
# Wave 1 validator floors.  The values are documented and derived in
# region_quality_contract.md; the regionqualtest `contract_constants` gate
# fails whenever these drift from the contract's machine-readable block.
# Clearance is a GEOMETRIC collision floor (never press through or within
# this distance of another body sheet), not a clinical thickness rule.
_WALL_CLEARANCE_MM = 3.0
_FOLD_DOT = -0.95
_FOLD_PRE_DOT = -0.5
# A face whose own normal passed 90° from its pre-commit normal is only a
# real inversion when the SURFACE confirms it: at least one of its edges must
# actually crease back on itself.  A legitimately steep wall tilts its whole
# neighbourhood (15 mm through a 10 mm feather is a 2.19 mm/mm slope — a 65°
# tilt), so a thin scan triangle riding that wall can cross 90° while the
# surface around it stays sound.  Confirmation at 0.0 (dihedral past 90°) is
# far stricter than the _FOLD_DOT fold-over test it backs up, and it sits a
# wide margin below the benign case measured on paint15 face 53270 (every
# neighbour dihedral 0.77, no self-intersection, 2.14 mm² area).
_FLIP_CONFIRM_DOT = 0.0
# #54 Task 6: the fold test above fires only when two neighbouring faces turn
# ANTIPARALLEL (past 162°).  A two-face hinge folded back to 100–160° passed
# it (measured: 123° on a corner-refined smoothstep trial, 150.9° on the
# DEC-0064 EASEOUT arm — both shipped as FINISHED).  A pair that was smoother
# than _HINGE_PRE_DEG before the commit and is past _HINGE_DEG after it is a
# fold we made: a repair target and, unrepaired, a refusal.  Legitimate steep
# walls measured at most ~70° per edge, well below 100°.
_HINGE_DEG = 100.0
_HINGE_PRE_DEG = 60.0
_HINGE_DOT = math.cos(math.radians(_HINGE_DEG))
_HINGE_PRE_DOT = math.cos(math.radians(_HINGE_PRE_DEG))
_HINGE_MIN_HEIGHT_M = 0.0001  # 0.1 mm: below this a face has no normal to judge


def _preview_name(region):
    return f"{_PREVIEW_PREFIX}{region.surface_mask}"


def _committed_key(region):
    return f"rigo_committed_{region.surface_mask}"


def _preview_modifier(obj, region):
    return obj.modifiers.get(_preview_name(region))


def _sync_preview(obj, region):
    """Create/update a reversible, surface-normal correction preview."""
    if obj.get(_committed_key(region), False):
        return None
    modifier = _preview_modifier(obj, region)
    if modifier is None:
        modifier = obj.modifiers.new(_preview_name(region), "DISPLACE")
    modifier.vertex_group = region.surface_mask
    modifier.direction = "NORMAL"
    modifier.mid_level = 0.0
    sign = -1.0 if region.kind == "PRESSURE" else 1.0
    modifier.strength = sign * region.magnitude_mm * 0.001
    modifier.show_in_editmode = True
    modifier.show_on_cage = True
    return modifier


def _remove_preview(obj, region):
    modifier = _preview_modifier(obj, region)
    if modifier is not None:
        obj.modifiers.remove(modifier)


# --------------------------------------------------------------------------- #
# #54 Task 1: the region's CONTINUOUS definition is the surface distance from
# the painted outline (mm, per vertex, -1 outside the region), stored as a
# float point attribute next to the mask.  The vertex-group weights are a
# VIEW of it — amount × falloff(min(d, f) / f) — re-evaluated whenever the
# orthotist edits feather/falloff, so nothing is baked before Commit.
# --------------------------------------------------------------------------- #
_DIST_SUFFIX = ".dist"
_CONTACT_SUFFIX = ".contact"   # #54 Task 7: the painted (full-depth) set
_OUTLINE_SUFFIX = ".outline"   # #54 Task 7: the drawn pad / band outlines
_BAND_CAP_MM = 60.0            # feather_mm's hard max: the band is stored once
_BAND_WALK = 1.4               # candidate walk past the cap (DEC-0070: 36.7 % p95)
# #54 Task 3: corner-aware sampling.  A fillet of radius r is drawn cleanly
# when each edge turns at most _CORNER_TURN radians (edge <= 0.25 r); below
# _CORNER_EDGE_FLOOR_M (or half the mesh's own edge) refinement would be a
# remesh, so the corner is reported instead of silently creased.
_CORNER_TURN = 0.2
_CORNER_EDGE_FLOOR_M = 0.0005
# A corner that would STILL turn more than this per edge after the one
# halving the floor allows is not drawn by refining it: measured, corners at
# 1.0–1.45 mesh edges got WORSE (golden painted route, 1.9 mm corner on
# ~1.3 mm edges: wall p95 17.6° → 20.8–22.3°; a 1.1 mm smoothstep corner on
# 2 mm edges went from a 54° crease to a 123° hinge) while a corner at 2
# edges improved (shoulder dihedral 21° → 8° median).  0.3 rad = corners of
# at least 1.67 mesh edges.  Below that the corner is left exactly as it was
# and named in the commit note.
_CORNER_SKIP_TURN = 0.3


def _corner_edge_floor(mean_edge_m):
    return max(_CORNER_EDGE_FLOOR_M, 0.5 * mean_edge_m)


def _drawable_corner_mm(edge_mm):
    """Smallest corner radius (mm) this mesh draws without a crease."""
    if edge_mm <= 0.0:
        return None
    return _corner_edge_floor(edge_mm * 0.001) / _CORNER_TURN * 1000.0


def _dist_name(mask):
    return mask + _DIST_SUFFIX


def _store_distance(me, mask, depth_mm, band_mm=None):
    """``depth_mm``: {vertex index: inward distance in mm} for every member.

    Outward regions (#54 Task 7) also pass ``band_mm`` {index: outward
    distance in mm} for the stored band candidates; those are written as
    NEGATIVE values and non-members as NaN (legacy encoding: -1)."""
    name = _dist_name(mask)
    attribute = me.attributes.get(name)
    if attribute is not None:
        me.attributes.remove(attribute)
    attribute = me.attributes.new(name, "FLOAT", "POINT")
    fill = np.nan if band_mm is not None else -1.0
    values = np.full(len(me.vertices), fill, dtype=np.float32)
    if depth_mm:
        index = np.fromiter(depth_mm.keys(), dtype=np.int64, count=len(depth_mm))
        values[index] = np.fromiter(
            depth_mm.values(), dtype=np.float64, count=len(depth_mm)
        )
    if band_mm:
        index = np.fromiter(band_mm.keys(), dtype=np.int64, count=len(band_mm))
        # strictly negative: a band vertex is never mistaken for pad (0.0)
        values[index] = -np.maximum(np.fromiter(
            band_mm.values(), dtype=np.float64, count=len(band_mm)
        ), 1e-6)
    attribute.data.foreach_set("value", values)


def _contact_name(mask):
    return f"{mask}{_CONTACT_SUFFIX}"


def _store_contact(me, mask, indices):
    """#54 Task 7: the painted set, stored explicitly — never reconstructed
    from the field (its rim re-zeroing leaves a zero plateau)."""
    name = _contact_name(mask)
    attribute = me.attributes.get(name)
    if attribute is not None:
        me.attributes.remove(attribute)
    attribute = me.attributes.new(name, "BOOLEAN", "POINT")
    values = np.zeros(len(me.vertices), dtype=bool)
    indices = list(indices)
    if indices:
        values[np.asarray(indices, dtype=np.int64)] = True
    attribute.data.foreach_set("value", values)


def _load_contact(me, mask):
    attribute = me.attributes.get(_contact_name(mask))
    if attribute is None or attribute.domain != "POINT":
        return None
    values = np.empty(len(me.vertices), dtype=bool)
    attribute.data.foreach_get("value", values)
    return values


def _drop_contact(me, mask):
    attribute = me.attributes.get(_contact_name(mask))
    if attribute is not None:
        me.attributes.remove(attribute)


def _outward_contact(me, region):
    """The painted set of an OUTWARD region, or None.  `feather_outside`
    is the single switch (Codex round C, Q7): a stale `.contact` on a
    region flagged inward is ignored, and a bare falloff string is legacy."""
    if isinstance(region, str) or not getattr(region, "feather_outside", False):
        return None
    return _load_contact(me, region.surface_mask)


def _band_weights(d_out_mm, feather_mm, falloff_kind, profile=(0.0, 0.0, 0.0)):
    """Outward band (#54 Task 7): weight = profile(feather - d_out), the same
    Smooth/Linear/Sharp/Rounded shapes as the inward path, no clamp."""
    d_out_mm = np.asarray(d_out_mm, dtype=np.float64)
    if d_out_mm.size == 0:
        return d_out_mm
    f = float(feather_mm)
    if f <= 1e-6:
        return np.zeros_like(d_out_mm)
    x = np.clip(f - d_out_mm, 0.0, f)
    if falloff_kind == "ROUNDED":
        amount, top, bottom = profile
        _theta, _rt, _rb, evaluate = _rounded_profile(amount, f, top, bottom)
        return evaluate(x)
    return _falloff_np(x / f, falloff_kind)


def _band_members(band_mm, feather_mm, falloff_kind, profile=(0.0, 0.0, 0.0)):
    """{index: weight} for the stored band candidates within the feather."""
    if not band_mm or feather_mm <= 1e-6:
        return {}
    order = [i for i, d in band_mm.items() if d <= feather_mm + 1e-9]
    if not order:
        return {}
    values = _band_weights(
        [band_mm[i] for i in order], feather_mm, falloff_kind, profile
    )
    return dict(zip(order, np.maximum(values, _MASK_EDGE_WEIGHT).tolist()))


def _outward_distance(contact, neighbours, co, cap_m):
    """Outline distance for the painted set AND an outward band (#54 Task 7).

    ``contact``: vertex indices of the painted pad; ``neighbours(i)`` yields
    neighbour indices; ``co(i)`` the position in metres.  Walks from the
    painted rim through NON-painted vertices to ``_BAND_WALK`` x ``cap_m``
    (the root walk overestimates by up to 37 % p95, DEC-0070), then measures
    every vertex with the same mollified-rim field the inside uses
    (``_boundary_distance``).  Returns ``(inward_m, outward_m, evaluate)`` —
    inward for every contact vertex, outward for band candidates within the
    cap — or ``(None, None, None)`` for a closed selection.
    """
    rim = {i for i in contact if any(j not in contact for j in neighbours(i))}
    if not rim:
        return None, None, None
    reach = cap_m * _BAND_WALK
    seen = {i: 0.0 for i in rim}
    heap = [(0.0, i) for i in rim]
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > seen.get(i, 1e30):
            continue
        ci = co(i)
        for j in neighbours(i):
            if j in contact:
                continue
            nd = d + (ci - co(j)).length
            if nd <= reach and nd < seen.get(j, 1e30):
                seen[j] = nd
                heapq.heappush(heap, (nd, j))
    candidates = {j for j in seen if j not in contact}
    members = contact | candidates
    coords = {i: co(i).copy() for i in members}
    adjacency = {i: [j for j in neighbours(i) if j in members] for i in members}
    dist, evaluate = _boundary_distance(coords, adjacency, rim)
    inward = {i: dist.get(i, 0.0) for i in contact}
    # The inside re-zeroes by the largest rim residual so every painted rim
    # vertex sits at exactly 0.  Applied outward, that same shift puts the
    # band's first ring AT 0 (weight 1) and the pad grows by a ring
    # (measured: 338 band vertices displaced the full amount).  The band
    # therefore uses the RAW distance to the mollified rim: strictly > 0.
    raw = getattr(evaluate, "raw", dist)
    outward = {
        j: max(raw[j], 1e-9) for j in candidates if raw.get(j, 1e30) <= cap_m
    }
    return inward, outward, evaluate


def _stored_band_mm(outward_m):
    """Band distances in mm as they will be STORED (float32, >= 1e-6): the
    attribute is the region's definition, so the first evaluation must use
    exactly the values every later re-evaluation reads back."""
    return {
        i: float(np.float32(max(d * 1000.0, 1e-6))) for i, d in outward_m.items()
    }


def _mesh_neighbours(me):
    """``neighbours(i)`` over a Mesh (Object mode) from its edge table."""
    n = len(me.vertices)
    ev = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    a = np.concatenate([ev[:, 0], ev[:, 1]])
    b = np.concatenate([ev[:, 1], ev[:, 0]])
    order = np.argsort(a, kind="stable")
    a, b = a[order], b[order]
    starts = np.searchsorted(a, np.arange(n + 1))
    return lambda i: b[starts[i]:starts[i + 1]].tolist()


def _outward_fields_from_contact(me, contact, feather_mm, falloff_kind,
                                 profile=(0.0, 0.0, 0.0)):
    """Weights + stored distances for an outward region given only its
    painted set (imported styles and mirrors, #54 Task 7).  Returns
    ``(weights, depth_mm, band_mm)`` or None."""
    contact = set(contact)
    verts = me.vertices
    inward, outward, _evaluate = _outward_distance(
        contact, _mesh_neighbours(me), lambda i: verts[i].co,
        _BAND_CAP_MM * 0.001,
    )
    if inward is None:
        return None
    depth_mm = {i: d * 1000.0 for i, d in inward.items()}
    band_mm = _stored_band_mm(outward)
    weights = {i: 1.0 for i in contact}
    weights.update(_band_members(band_mm, feather_mm, falloff_kind, profile))
    return weights, depth_mm, band_mm


def _outline_name(obj, region):
    # The scan's name is part of it: history copies keep their mask names
    # (Codex round C, Q5), so a bare mask name could resolve to another
    # object's outline.  Blender object names are capped at 63 bytes.
    return f"{obj.name}.{region.surface_mask}{_OUTLINE_SUFFIX}"[-63:]


def _delete_outline_object(outline):
    mesh = outline.data
    bpy.data.objects.remove(outline, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _boundary_edge_pairs(me, inside):
    """Edges with both ends ``inside`` that border a face not fully inside
    (numpy over the loop table; no Python per-face loop)."""
    n_edges = len(me.edges)
    if n_edges == 0 or len(me.polygons) == 0:
        return np.zeros((0, 2), dtype=np.int64)
    ev = np.empty(n_edges * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    both = inside[ev[:, 0]] & inside[ev[:, 1]]
    loop_edge = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("edge_index", loop_edge)
    loop_vert = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", loop_vert)
    totals = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_total", totals)
    face_of_loop = np.repeat(np.arange(len(me.polygons)), totals)
    face_inside = np.ones(len(me.polygons), dtype=bool)
    np.logical_and.at(face_inside, face_of_loop, inside[loop_vert])
    inside_count = np.bincount(
        loop_edge[face_inside[face_of_loop]], minlength=n_edges
    )
    total_count = np.bincount(loop_edge, minlength=n_edges)
    boundary = both & (inside_count >= 1) & (inside_count < total_count)
    return ev[boundary]


def _region_member_flags(obj, region):
    """(contact flags or None, member flags) over the vertices, from the
    stored attributes (fast) or the vertex group (legacy without distance)."""
    me = obj.data
    n = len(me.vertices)
    contact = _outward_contact(me, region)
    depth = _load_distance(me, region.surface_mask)
    if contact is not None and depth is not None:
        band = (~contact) & (depth < 0.0) & (-depth <= region.feather_mm + 1e-9)
        return contact, contact | band
    if depth is not None:
        return None, depth >= 0.0
    group = obj.vertex_groups.get(region.surface_mask)
    member = np.zeros(n, dtype=bool)
    if group is not None:
        gi = group.index
        for vertex in me.vertices:
            for g in vertex.groups:
                if g.group == gi and g.weight > 0.0:
                    member[vertex.index] = True
                    break
    return None, member


def _outline_geometry(obj, region):
    """Vertices (local space, on the EVALUATED surface) and edges of the
    painted outline and, for an outward region, the band's outer edge."""
    me = obj.data
    n = len(me.vertices)
    contact, member = _region_member_flags(obj, region)
    coords = np.empty(n * 3, dtype=np.float64)
    me.vertices.foreach_get("co", coords)
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        me_e = evaluated.to_mesh()
        if me_e is not None and len(me_e.vertices) == n:
            me_e.vertices.foreach_get("co", coords)
        if me_e is not None:
            evaluated.to_mesh_clear()
    except (RuntimeError, AttributeError):
        pass
    coords = coords.reshape(-1, 3)
    verts, edges = [], []
    loops = [contact] if contact is not None else []
    loops.append(member)
    for flags in loops:
        pairs = _boundary_edge_pairs(me, flags)
        if pairs.size == 0:
            continue
        unique, inverse = np.unique(pairs.ravel(), return_inverse=True)
        base = len(verts)
        verts.extend(coords[unique].tolist())
        edges.extend((base + inverse.reshape(-1, 2)).tolist())
    return verts, edges


def sync_outline(obj):
    """#54 Task 7: draw the ACTIVE live region's outline — the painted pad
    edge and, for an outward region, the band's outer edge — as a wire
    object parented to the scan; remove every other region's outline.
    Idempotent; safe when nothing is active or the object is missing."""
    if obj is None or getattr(obj, "type", None) != "MESH":
        return
    region = _active_region(obj)
    want = None
    if (region is not None and region.surface_mask
            and not obj.get(_committed_key(region), False)
            and not obj.data.is_editmode
            and obj.vertex_groups.get(region.surface_mask) is not None):
        want = _outline_name(obj, region)
    for other in list(bpy.data.objects):
        if (other.name.endswith(_OUTLINE_SUFFIX) and other.parent == obj
                and other.name != want):
            _delete_outline_object(other)
    if want is None:
        return
    verts, edges = _outline_geometry(obj, region)
    existing = bpy.data.objects.get(want)
    if existing is not None and existing.parent == obj:
        _delete_outline_object(existing)
    if not edges:
        return
    mesh = bpy.data.meshes.new(want)
    mesh.from_pydata(verts, edges, [])
    outline = bpy.data.objects.new(want, mesh)
    collections = obj.users_collection
    (collections[0] if collections else bpy.context.scene.collection).objects.link(outline)
    outline.parent = obj
    outline.matrix_parent_inverse = Matrix()
    outline.hide_select = True
    outline.hide_render = True
    outline.display_type = "WIRE"
    outline.show_in_front = True
    outline.color = (1.0, 0.55, 0.0, 1.0)


def _load_distance(me, mask):
    attribute = me.attributes.get(_dist_name(mask))
    if attribute is None or attribute.domain != "POINT":
        return None
    values = np.empty(len(me.vertices), dtype=np.float32)
    attribute.data.foreach_get("value", values)
    return values.astype(np.float64)


def _drop_distance(me, mask):
    attribute = me.attributes.get(_dist_name(mask))
    if attribute is not None:
        me.attributes.remove(attribute)


def _falloff_np(t, kind):
    if kind == "LINEAR":
        return t
    if kind == "SHARP":
        return t * t
    return t * t * (3.0 - 2.0 * t)  # SMOOTH (smoothstep) — same as _falloff


def _rounded_profile(amount_mm, feather_mm, top_mm, bottom_mm):
    """The ROUNDED transition (#54 Task 2): flat pad → top fillet ``top_mm``
    → straight wall at angle θ → bottom fillet ``bottom_mm`` → untouched body,
    drawn in the (distance-from-outline, height) plane, all in mm.

    Height identity  A = (r_t + r_b)(1 − cos θ) + L·tan θ  with the straight
    wall L = f − (r_t + r_b)·sin θ ≥ 0 is monotone in θ, solved by bisection.
    Radii that do not fit the width are scaled down TOGETHER (the panel shows
    the effective values).  Returns ``(theta, r_top, r_bottom, evaluate)``;
    ``evaluate(d)`` maps a numpy array of distances (mm) to weights z / A.
    """
    amount = abs(float(amount_mm))
    width = float(feather_mm)
    r_t = max(0.0, float(top_mm))
    r_b = max(0.0, float(bottom_mm))
    if amount <= 1e-6 or width <= 1e-6:
        return 0.0, r_t, r_b, (
            lambda d: np.ones_like(np.asarray(d, dtype=np.float64))
        )
    # r_t + r_b < f is feasible for any amount; r_t + r_b == f only up to
    # A == f (two tangent quarter-circles).
    limit = width if amount <= width else width * 0.999
    total = r_t + r_b
    if total > limit and total > 0.0:
        scale = limit / total
        r_t *= scale
        r_b *= scale
        total = limit

    def height(theta):
        s, c = math.sin(theta), math.cos(theta)
        return total * (1.0 - c) + (width - total * s) * (s / c)

    lo, hi = 0.0, math.pi * 0.5 - 1e-9
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if height(mid) < amount:
            lo = mid
        else:
            hi = mid
    theta = 0.5 * (lo + hi)
    s, c = math.sin(theta), math.cos(theta)
    slope = s / c
    x_b, z_b = r_b * s, r_b * (1.0 - c)
    x_t = width - r_t * s

    def evaluate(d):
        d = np.clip(np.asarray(d, dtype=np.float64), 0.0, width)
        z_bottom = r_b - np.sqrt(np.maximum(r_b * r_b - d * d, 0.0))
        z_wall = z_b + (d - x_b) * slope
        gap = width - d
        z_top = amount - r_t + np.sqrt(np.maximum(r_t * r_t - gap * gap, 0.0))
        z = np.where(d <= x_b, z_bottom, np.where(d >= x_t, z_top, z_wall))
        return np.clip(z / amount, 0.0, 1.0)

    evaluate.theta = theta
    evaluate.x_bottom = x_b  # mm: end of the bottom fillet
    evaluate.x_top = x_t  # mm: start of the top fillet
    return theta, r_t, r_b, evaluate


def _region_profile(region):
    """(amount, top radius, bottom radius) — the ROUNDED profile's inputs."""
    return (region.magnitude_mm, region.top_radius_mm, region.bottom_radius_mm)


def transition_readout(region):
    """Panel readout for the active region: what the profile bends over, and
    whether this mesh can draw it.  Returns ``(text, warn)``."""
    f_eff = region.feather_mm
    if region.depth_mm > 0.0 and not region.feather_outside:
        f_eff = min(f_eff, region.depth_mm)
    amount = region.magnitude_mm
    kind = region.falloff_type
    corner = None
    if kind == "ROUNDED":
        theta, r_t, r_b, _evaluate = _rounded_profile(
            amount, f_eff, region.top_radius_mm, region.bottom_radius_mm
        )
        text = f"Wall {math.degrees(theta):.0f}° · corners {r_t:.1f} / {r_b:.1f} mm"
        if r_t + r_b < region.top_radius_mm + region.bottom_radius_mm - 1e-6:
            text += " (shrunk to fit the width)"
        corner = min(r_t, r_b)
    elif kind == "SMOOTH":
        if amount > 1e-6 and f_eff > 1e-6:
            corner = f_eff * f_eff / (6.0 * amount)
            text = f"Smooth bends over {corner:.1f} mm at both corners"
        else:
            text = "Smooth"
    elif kind == "LINEAR":
        corner = 0.0
        text = "Linear: hard edges at both corners"
    else:
        corner = 0.0
        text = "Sharp: hard edge at the pad top"
    drawable = _drawable_corner_mm(region.edge_mm)
    warn = bool(drawable is not None and corner is not None
                and corner < drawable - 1e-9)
    if warn:
        text += f" — finer than this mesh draws ({drawable:.1f} mm)"
    return text, warn


def profile_readout(region):
    return transition_readout(region)[0]


def _weights_from_distance(depth_mm, feather_mm, falloff_kind,
                           profile=(0.0, 0.0, 0.0)):
    """Array of weights for member distances ``depth_mm`` (numpy, mm).

    The feather cannot be wider than the region is deep — clamped to the
    largest distance so the innermost vertices always reach 1.0 (the same
    rule ``_region_weights_from_selection`` always applied).  ``profile`` =
    (amount, top radius, bottom radius) feeds the ROUNDED kind only."""
    depth_mm = np.asarray(depth_mm, dtype=np.float64)
    if depth_mm.size == 0:
        return depth_mm
    f_eff = min(float(feather_mm), float(depth_mm.max()))
    if f_eff <= 1e-6:
        return np.ones_like(depth_mm)
    if falloff_kind == "ROUNDED":
        amount, top, bottom = profile
        _theta, _rt, _rb, evaluate = _rounded_profile(amount, f_eff, top, bottom)
        return evaluate(np.minimum(depth_mm, f_eff))
    return _falloff_np(np.minimum(depth_mm, f_eff) / f_eff, falloff_kind)


def _refresh_snapshot_weights(obj, mask, weights):
    """Light snapshot refresh: only the weight column changes on a profile
    edit (membership, frame and anchor are fixed by the painted outline)."""
    snapshot = _load_snapshot(obj, mask)
    if snapshot is None or snapshot.get("applied_field"):
        return
    samples = snapshot["samples"]
    indices = sorted(weights)
    if len(samples) != len(indices):
        return
    for sample, index in zip(samples, indices):
        sample[2] = round(float(weights[index]), 5)
    snapshot.pop("field", None)
    _store_snapshot(obj, mask, snapshot)


def reevaluate_region(obj, region):
    """Rebuild the mask weights from the stored outline distance and the
    region's own feather/falloff, then refresh the live preview.

    Returns False (and only re-syncs the preview) when the region has no
    stored distance: imported styles and mirrors carry a chart field, not a
    distance, and legacy regions predate the attribute — for those the
    feather is edited by Edit Selection → Update Preview, as before."""
    if obj is None or obj.type != "MESH" or not region.surface_mask:
        return False
    if obj.get(_committed_key(region), False):
        return False
    me = obj.data
    if me.is_editmode:
        _sync_preview(obj, region)  # amount stays live; Update applies the rest
        return False
    group = obj.vertex_groups.get(region.surface_mask)
    depth = _load_distance(me, region.surface_mask)
    if group is None or depth is None:
        _sync_preview(obj, region)
        return False
    contact = _outward_contact(me, region)
    if contact is not None:
        return _reevaluate_outward(obj, region, group, depth, contact)
    members = np.flatnonzero(depth >= 0.0)
    if members.size == 0:
        return False
    weights = np.maximum(
        _weights_from_distance(
            depth[members], region.feather_mm, region.falloff_type,
            _region_profile(region),
        ),
        _MASK_EDGE_WEIGHT,
    )
    by_index = dict(zip(members.tolist(), weights.tolist()))
    for index, weight in by_index.items():
        group.add([index], weight, "REPLACE")
    _refresh_snapshot_weights(obj, region.surface_mask, by_index)
    _sync_preview(obj, region)
    return True


def _reevaluate_outward(obj, region, group, depth, contact):
    """#54 Task 7: the painted set stays at 1.0; the band is re-cut at the
    feather from the stored candidates — members beyond it are REMOVED, so
    a narrower feather releases the surface it no longer reaches."""
    # Band = strictly NEGATIVE stored distance (Codex round C, Q2): a stray
    # 0.0 (fresh attribute after Subdivide Scan) must never read as a band
    # vertex at the outline, i.e. full weight.
    candidates = np.flatnonzero((~contact) & (depth < 0.0))
    d_out = -depth[candidates]
    keep = d_out <= region.feather_mm + 1e-9
    drop = candidates[~keep].tolist()
    if drop:
        group.remove(drop)
    weights = np.maximum(
        _band_weights(d_out[keep], region.feather_mm, region.falloff_type,
                      _region_profile(region)),
        _MASK_EDGE_WEIGHT,
    )
    for index in np.flatnonzero(contact).tolist():
        group.add([index], 1.0, "REPLACE")
    for index, weight in zip(candidates[keep].tolist(), weights.tolist()):
        group.add([index], float(weight), "REPLACE")
    _sync_preview(obj, region)
    sync_outline(obj)
    return True


def sync_preview(obj, region):
    """Public alias for the core property callbacks (live Amount)."""
    if obj is None or obj.type != "MESH":
        return None
    return _sync_preview(obj, region)


def _make_active(context, obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _surface_frame(normal):
    outward = normal.normalized()
    vertical = Vector((0.0, 0.0, 1.0))
    tangent_up = vertical - outward * vertical.dot(outward)
    if tangent_up.length < 0.1:
        tangent_up = Vector((0.0, 1.0, 0.0))
        tangent_up -= outward * tangent_up.dot(outward)
    tangent_up.normalize()
    tangent_side = outward.cross(tangent_up).normalized()
    return tangent_side, tangent_up, outward


def _group_weights(scan, group):
    weights = {}
    for vertex in scan.data.vertices:
        for membership in vertex.groups:
            if membership.group == group.index:
                weights[vertex.index] = membership.weight
                break
    return weights


def _style_samples(scan, group):
    weights = _group_weights(scan, group)
    matrix = scan.matrix_world
    normal_matrix = matrix.to_3x3()
    center = sum((matrix @ scan.data.vertices[i].co for i in weights), Vector())
    center /= len(weights)
    normal = sum(
        (normal_matrix @ scan.data.vertices[i].normal for i in weights), Vector()
    ).normalized()
    side, up, outward = _surface_frame(normal)
    samples = []
    normal_offsets = []
    for index, weight in weights.items():
        relative = matrix @ scan.data.vertices[index].co - center
        samples.append([relative.dot(side) * 1000.0, relative.dot(up) * 1000.0, weight])
        normal_offsets.append(abs(relative.dot(outward)) * 1000.0)
    return samples, normal_offsets, weights


def _sample_spacing_mm(scan, indices):
    matrix = scan.matrix_world
    lengths = []
    for edge in scan.data.edges:
        if edge.vertices[0] in indices and edge.vertices[1] in indices:
            first = matrix @ scan.data.vertices[edge.vertices[0]].co
            second = matrix @ scan.data.vertices[edge.vertices[1]].co
            lengths.append((first - second).length * 1000.0)
    return sum(lengths) / len(lengths) if lengths else 2.0


def _mesh_spacing_mm(scan):
    matrix = scan.matrix_world
    total_length = 0.0
    for edge in scan.data.edges:
        first = matrix @ scan.data.vertices[edge.vertices[0]].co
        second = matrix @ scan.data.vertices[edge.vertices[1]].co
        total_length += (first - second).length * 1000.0
    return total_length / len(scan.data.edges) if scan.data.edges else 2.0


def _style_snapshot(scan, weights, coords=None, normals=None,
                    build_field=False, origin_world=None, pad=None):
    """Tangent-frame samples + resampled field of the UNdisplaced region.

    Captured at bake time (before any displacement is committed) so a saved
    style describes the authored influence field, not a crater-shaped
    snapshot of already-corrected geometry (#48 RC3).  ``coords``/``normals``
    default to the raw mesh; pass evaluated arrays where the region was built
    against the evaluated surface.
    """
    me = scan.data
    if coords is None:
        coords = [v.co for v in me.vertices]
    if normals is None:
        normals = [v.normal for v in me.vertices]
    matrix = scan.matrix_world
    normal_matrix = matrix.to_3x3()
    indices = sorted(weights)
    # Frame origin = the point the orthotist anchored the region to (circle
    # seed / import cursor); painted regions use the strong-member vertex
    # nearest the weighted centroid.  Snapping ONTO the pad matters for
    # non-convex footprints: a horseshoe's centroid sits in its gap, and the
    # import cursor (necessarily on the pad) would shift the whole pattern
    # by the centroid-to-pad distance (#48 Wave 2, measured 40 mm / IoU
    # 0.123 before the snap).  The frame NORMAL must be derived exactly the
    # way the import side derives it (_target_surface at the anchor) — any
    # other normal shears the projection on creased surfaces.
    if origin_world is None:
        centroid = Vector()
        total = 0.0
        for i in indices:
            w = max(weights[i], 1e-6)
            centroid += (matrix @ coords[i]) * w
            total += w
        centroid /= total
        # #54 Task 7: an outward region anchors on its PAINTED set — the
        # band fills a horseshoe's gap and would pull the anchor into it.
        strong = (
            [i for i in indices if i in pad] if pad
            else [i for i in indices if weights[i] >= 0.3]
        ) or indices
        anchor_index = min(
            strong,
            key=lambda i: (matrix @ coords[i] - centroid).length_squared,
        )
        center = matrix @ coords[anchor_index]
    else:
        center = Vector(origin_world)
    surface_point, normal = _target_surface(scan, center)
    if surface_point is not None:
        center = surface_point
    else:
        normal = Vector()
        for i in indices:
            normal += (normal_matrix @ normals[i]) * (weights[i] * weights[i])
        if normal.length < 1e-9:
            normal = Vector((0.0, 0.0, 1.0))
        normal.normalize()
    side, up, outward = _surface_frame(normal)
    samples = []
    normal_offsets = []
    for i in indices:
        relative = matrix @ coords[i] - center
        samples.append([
            round(relative.dot(side) * 1000.0, 3),
            round(relative.dot(up) * 1000.0, 3),
            round(weights[i], 5),
        ])
        normal_offsets.append(abs(relative.dot(outward)) * 1000.0)
    spacing = _sample_spacing_mm(scan, set(indices))
    # Intrinsic size: the farthest EFFECTIVE (w > 0.05) vertex measured
    # ALONG the surface from the anchor.  This — not the chart's chord
    # extent — is the style's authoritative size (Wave 2 decision: surface
    # mm); the import-side trim uses it so distant lobes of non-convex pads
    # survive, and the import-side size check compares against the same
    # w > 0.05 definition.
    effective = {i for i in indices if weights[i] > 0.05} or set(indices)
    seed = min(
        effective, key=lambda i: (matrix @ coords[i] - center).length_squared
    )
    snapshot = {
        "samples": samples,
        "sample_radius_mm": max(1.0, spacing * 1.75),
        "normal_tolerance_mm": max(15.0, max(normal_offsets) + spacing * 2.0),
        "spacing_mm": spacing,
        "max_geodesic_mm": round(
            _member_geodesic_max(me, effective, coords, seed), 2
        ),
        "anchor_uv": [0.0, 0.0],
        "anchor_world": [center.x, center.y, center.z],
        # The frame NORMAL, so the chart this snapshot was written in can be
        # rebuilt exactly (`_surface_frame` derives side/up deterministically
        # from it).  Without it a stored style field cannot be re-evaluated at
        # commit time — see `_style_applied_field` (#49k).
        "anchor_normal": [normal.x, normal.y, normal.z],
    }
    if build_field:
        snapshot["field"] = _field_from_samples(samples, spacing)
    return snapshot


def _member_geodesic_max(me, member, coords, seed):
    """Largest edge-walk distance (mm) from ``seed`` inside the member set."""
    neighbors = {}
    for edge in me.edges:
        a, b = edge.vertices
        if a in member and b in member:
            length = (coords[a] - coords[b]).length
            neighbors.setdefault(a, []).append((b, length))
            neighbors.setdefault(b, []).append((a, length))
    dist = {seed: 0.0}
    heap = [(0.0, seed)]
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist.get(i, 1e30):
            continue
        for j, length in neighbors.get(i, ()):
            nd = d + length
            if nd < dist.get(j, 1e30):
                dist[j] = nd
                heapq.heappush(heap, (nd, j))
    return max(dist.values()) * 1000.0 if dist else 0.0


def _store_snapshot(scan, mask, snapshot):
    scan[_SNAPSHOT_PREFIX + mask] = json.dumps(snapshot)


def _load_snapshot(scan, mask):
    raw = scan.get(_SNAPSHOT_PREFIX + mask)
    if not raw:
        return None
    try:
        snapshot = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return snapshot if snapshot.get("samples") else None


def _drop_snapshot(scan, mask):
    key = _SNAPSHOT_PREFIX + mask
    if key in scan:
        del scan[key]


def _evaluated_positions(scan):
    """Vertex-aligned coords/normals of the EVALUATED scan, or (None, None).

    The user paints and places the cursor on the surface AFTER modifiers
    (live region previews, smoothing, lattices).  Reading raw ``scan.data``
    against an evaluated target frame mixes two geometry states and tears the
    imported footprint apart (#48 RC2).  Topology-changing modifiers break
    the per-vertex alignment, so those return None and the caller refuses.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = scan.evaluated_get(depsgraph)
    me = evaluated.to_mesh()
    if me is None:
        return None, None
    if len(me.vertices) != len(scan.data.vertices):
        evaluated.to_mesh_clear()
        return None, None
    coords = [v.co.copy() for v in me.vertices]
    normals = [v.normal.copy() for v in me.vertices]
    evaluated.to_mesh_clear()
    return coords, normals


def _target_surface(scan, target_world):
    """Closest point/normal on the EVALUATED surface — what the user sees."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = scan.evaluated_get(depsgraph)
    inverse = scan.matrix_world.inverted()
    found, location, normal, _index = evaluated.closest_point_on_mesh(
        inverse @ target_world
    )
    if not found:
        return None, None
    world_location = scan.matrix_world @ location
    world_normal = (scan.matrix_world.to_3x3() @ normal).normalized()
    return world_location, world_normal


def _field_from_samples(samples, spacing_mm):
    """Resample scattered (u, v, weight) samples onto a regular 2D grid.

    The stored grid is what makes an imported style geometrically continuous:
    bilinear interpolation cannot reproduce the source triangulation's Voronoi
    cells the way nearest-sample lookup did (#48 RC1), and it is independent
    of the target mesh density by construction.
    """
    xs = [s[0] for s in samples]
    ys = [s[1] for s in samples]
    pad = 2.0
    extent_x = max(xs) - min(xs) + 2.0 * pad
    extent_y = max(ys) - min(ys) + 2.0 * pad
    cell = max(1.0, min(2.0, spacing_mm * 0.75), extent_x / 127.0, extent_y / 127.0)
    x0 = min(xs) - pad
    y0 = min(ys) - pad
    nx = int(math.ceil(extent_x / cell)) + 1
    ny = int(math.ceil(extent_y / cell)) + 1
    tree = kdtree.KDTree(len(samples))
    for index, sample in enumerate(samples):
        tree.insert((sample[0], sample[1], 0.0), index)
    tree.balance()
    support = spacing_mm * 2.5
    eps2 = (spacing_mm * 0.35) ** 2
    values = []
    for j in range(ny):
        cy = y0 + j * cell
        for i in range(nx):
            cx = x0 + i * cell
            numerator = 0.0
            denominator = 0.0
            nearest = None
            for _co, sindex, dist in tree.find_n((cx, cy, 0.0), 6):
                if nearest is None or dist < nearest:
                    nearest = dist
                if dist > support:
                    continue
                kernel = 1.0 / (dist * dist + eps2)
                numerator += samples[sindex][2] * kernel
                denominator += kernel
            if denominator == 0.0 or nearest is None or nearest > support:
                values.append(0.0)
                continue
            value = numerator / denominator
            # Taper cells beyond the authored sample hull so the imported
            # footprint keeps the authored outline instead of an IDW skirt.
            hull_start = spacing_mm * 1.2
            if nearest > hull_start:
                t = max(0.0, 1.0 - (nearest - hull_start) / (spacing_mm * 1.3))
                value *= t * t * (3.0 - 2.0 * t)
            # Core plateau: the full requested amount must survive
            # resampling — including a SECOND resample (mirror evaluates the
            # stored field again), where bilinear attenuation of a
            # one-cell-wide plateau reaches ~5 %.  0.95 absorbs that; the
            # parity gates (IoU/RMS/profile) verify the outline is unharmed.
            if value >= 0.95:
                value = 1.0
            elif value <= 0.005:
                value = 0.0
            values.append(round(value, 4))
    return {
        "cell_mm": cell,
        "x0": round(x0, 3),
        "y0": round(y0, 3),
        "nx": nx,
        "ny": ny,
        "values": values,
    }


def _field_weight(field, u, v):
    """Bilinear sample of the stored weight grid; 0 outside its bounds."""
    cell = field["cell_mm"]
    gx = (u - field["x0"]) / cell
    gy = (v - field["y0"]) / cell
    i0 = int(math.floor(gx))
    j0 = int(math.floor(gy))
    fx = gx - i0
    fy = gy - j0
    nx = field["nx"]
    ny = field["ny"]
    values = field["values"]

    def cell_value(i, j):
        if i < 0 or j < 0 or i >= nx or j >= ny:
            return 0.0
        return values[j * nx + i]

    return (
        cell_value(i0, j0) * (1.0 - fx) * (1.0 - fy)
        + cell_value(i0 + 1, j0) * fx * (1.0 - fy)
        + cell_value(i0, j0 + 1) * (1.0 - fx) * fy
        + cell_value(i0 + 1, j0 + 1) * fx * fy
    )


def _idw_weight(samples, tree, u, v, support, eps2):
    """Continuous inverse-distance interpolation for legacy (v1) styles."""
    numerator = 0.0
    denominator = 0.0
    nearest = None
    for _co, sindex, dist in tree.find_n((u, v, 0.0), 6):
        if nearest is None or dist < nearest:
            nearest = dist
        if dist > support:
            continue
        kernel = 1.0 / (dist * dist + eps2)
        numerator += samples[sindex][2] * kernel
        denominator += kernel
    if denominator == 0.0 or nearest is None or nearest > support:
        return 0.0
    weight = numerator / denominator
    # Smooth taper beyond the sample hull instead of a hard radius cliff.
    half = support * 0.5
    if nearest > half:
        t = 1.0 - (nearest - half) / half
        weight *= t * t * (3.0 - 2.0 * t)
    return weight


def _connected_subset(scan, weights, coords, target_world):
    """Keep only the mesh-connected patch nearest the cursor.

    The tangent-plane footprint can also catch the far wall of the body; edge
    connectivity — not a hard normal-offset cull — is what separates them
    without tearing the near patch (#48 RC5).
    """
    if not weights:
        return weights
    me = scan.data
    member = set(weights)
    parent = {i: i for i in member}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for edge in me.edges:
        a, b = edge.vertices
        if a in member and b in member:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    components = {}
    for i in member:
        components.setdefault(find(i), []).append(i)
    if len(components) == 1:
        return weights
    matrix = scan.matrix_world

    def closest_distance(indices):
        return min(
            (matrix @ coords[i] - target_world).length_squared for i in indices
        )

    keep = min(components.values(), key=closest_distance)
    return {i: weights[i] for i in keep}


# --------------------------------------------------------------------------- #
# Whole-mesh scans in numpy (#53).  These replace Python loops over every
# edge/loop/polygon of the scan (60-90 % of the non-collapse commit time on a
# 357k-face scan).  Rule: numpy SELECTS and INDEXES; any arithmetic whose
# float bits feed a threshold (edge lengths, normals) stays in mathutils on
# the selected subset, so every result is bit-identical to the loop it
# replaced (tools/vecequivdbg.py proves it on real regions).
# --------------------------------------------------------------------------- #
def _vertex_mask(count, member):
    mask = np.zeros(count, dtype=bool)
    if member:
        mask[np.fromiter(member, dtype=np.int64, count=len(member))] = True
    return mask


def _edge_pairs(me):
    ev = np.empty(2 * len(me.edges), dtype=np.int32)
    me.edges.foreach_get("vertices", ev)
    return ev.reshape(-1, 2)


def _loop_arrays(me):
    """Per-loop vertex index plus per-polygon loop start/total (int32)."""
    vidx = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", vidx)
    starts = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get("loop_start", starts)
    totals = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get("loop_total", totals)
    return vidx, starts, totals


def _faces_by_membership(me, member):
    """(faces holding at least one ``member`` vertex, faces holding none),
    both in polygon-index order — ``any(vi in member for vi in p.vertices)``
    evaluated for the whole mesh at once."""
    polys = me.polygons
    if not len(polys):
        return [], []
    vidx, starts, _totals = _loop_arrays(me)
    hit = np.add.reduceat(
        _vertex_mask(len(me.vertices), member)[vidx].astype(np.int32), starts
    ) > 0
    return (
        [polys[i] for i in np.flatnonzero(hit).tolist()],
        [polys[i] for i in np.flatnonzero(~hit).tolist()],
    )


def _mean_touching_edge(me, member):
    """Mean length of the edges with at least one end in ``member`` (edge
    order, mathutils float32 lengths summed in Python exactly as before);
    ``None`` when no edge touches."""
    ev = _edge_pairs(me)
    mask = _vertex_mask(len(me.vertices), member)
    pairs = ev[mask[ev[:, 0]] | mask[ev[:, 1]]].tolist()
    if not pairs:
        return None
    verts = me.vertices
    total = 0.0
    for a, b in pairs:
        total += (verts[a].co - verts[b].co).length
    return total / len(pairs)


def _faired_normals(me, weights, mean_edge):
    """Displacement directions: normals averaged over a geodesic radius.

    On wrinkled scan areas the raw per-vertex normals point every which way;
    pressing 15 mm along them shreds the crease walls even under a perfectly
    smooth influence field.  A pad presses along a coherent direction, so the
    commit displaces along normals faired over ~2 edge lengths (min 6 mm).
    Unit length, so |displacement| stays exactly amount × weight.
    (#49d measured: scaling this radius with the amount changes NO seam
    outcome at 15–20 mm — only the cost — the steep-wall seam collapses are
    not direction-coherence-limited.)
    """
    radius = max(0.006, 2.0 * mean_edge)
    # Membership is "in the mask" (> 0.0), NOT ">= the 1e-6 floor": vertex
    # groups store float32, and float32(1e-6) < 1e-6, so floor-valued
    # boundary vertices would silently fail a >= test (#48 hardening, item 8).
    member = {i for i, w in weights.items() if w > 0.0}
    # Two-pass zone-restricted adjacency (member + ~2 rings) — building the
    # whole scan's adjacency per commit costs more than the fairing itself.
    ev = _edge_pairs(me)
    mask = _vertex_mask(len(me.vertices), member)
    ring1 = set(member)
    ring1.update(ev[mask[ev[:, 0]] | mask[ev[:, 1]]].ravel().tolist())
    r1 = _vertex_mask(len(me.vertices), ring1)
    adjacency = {}
    for a, b in ev[r1[ev[:, 0]] | r1[ev[:, 1]]].tolist():
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    faired = {}
    for i in member:
        dist = {i: 0.0}
        heap = [(0.0, i)]
        accumulated = Vector()
        while heap:
            d, j = heapq.heappop(heap)
            if d > dist.get(j, 1e30):
                continue
            accumulated += me.vertices[j].normal
            for k in adjacency.get(j, ()):
                nd = d + (me.vertices[j].co - me.vertices[k].co).length
                if nd <= radius and nd < dist.get(k, 1e30):
                    dist[k] = nd
                    heapq.heappush(heap, (nd, k))
        if accumulated.length < 1e-9:
            accumulated = me.vertices[i].normal.copy()
        faired[i] = accumulated.normalized()
    return faired, adjacency


def _tri_bvh(me, faces):
    """BVH over ``faces``, fan-triangulated, plus a triangle -> owning-face map.

    The patient scan is NOT always triangles (#49m).  The Mesh stage's own
    Remesh emits 100 % quads — measured on the A-model, 89 144 triangles in,
    46 098 quads out — and the Exoside Quad Remesher's output is adopted
    verbatim as the patient scan.  ``BVHTree.FromPolygons(...,
    all_triangles=True)`` is a hard ASSERTION, not a hint: it raises
    ``ValueError: non triangle found`` on the first quad.  Committing a
    correction on a quad scan therefore died with a Python traceback in the
    orthotist's face, on the ordinary Remesh -> Paint -> Commit path.

    Fan-triangulating here rather than passing ``all_triangles=False`` keeps
    the hit indices meaningful: callers look the face up by the index the tree
    reports, so the owner map must be ours, not Blender's internal
    tessellation.  Returns ``(tree, owner, polys)``.
    """
    from mathutils.bvhtree import BVHTree

    if not faces:
        return None, [], []
    # All-triangle input (the usual case): gather the corner indices in one
    # shot; np.unique's sorted output is exactly ``sorted(set)`` and its
    # inverse is exactly the ``local`` map below.
    fi = np.fromiter((p.index for p in faces), dtype=np.int64, count=len(faces))
    vidx, starts, totals = _loop_arrays(me)
    if np.all(totals[fi] == 3):
        tri = vidx[starts[fi][:, None] + np.arange(3)]
        used_np, inv = np.unique(tri, return_inverse=True)
        co = np.empty(3 * len(me.vertices), dtype=np.float32)
        me.vertices.foreach_get("co", co)
        verts = co.reshape(-1, 3)[used_np].tolist()
        polys = [tuple(t) for t in inv.reshape(-1, 3).tolist()]
        return (
            BVHTree.FromPolygons(verts, polys, all_triangles=True),
            list(faces),
            polys,
        )
    used = sorted({vi for p in faces for vi in p.vertices})
    local = {vi: n for n, vi in enumerate(used)}
    verts = [me.vertices[vi].co.copy() for vi in used]
    polys = []
    owner = []
    for poly in faces:
        idx = [local[vi] for vi in poly.vertices]
        for k in range(1, len(idx) - 1):
            polys.append((idx[0], idx[k], idx[k + 1]))
            owner.append(poly)
    if not polys:
        return None, [], []
    return BVHTree.FromPolygons(verts, polys, all_triangles=True), owner, polys


def _footprint_self_intersections(me, member, faces=None):
    """Indices of footprint faces that intersect a non-adjacent face."""
    if faces is None:
        faces = _faces_by_membership(me, member)[0]
    tree, owner, polys = _tri_bvh(me, faces)
    if tree is None:
        return set()
    bad = set()
    for a, b in tree.overlap(tree):
        # Two triangles of the SAME quad always share an edge — they are not
        # a self-intersection.
        if a == b or owner[a] is owner[b]:
            continue
        if set(polys[a]) & set(polys[b]):
            continue
        bad.add(owner[a].index)
        bad.add(owner[b].index)
    return bad


def _static_faces_bvh(me, member):
    """BVH of the body's faces that hold NO footprint vertex (they never move
    during a commit).  These are exactly the faces the footprint-local checks
    cannot see — the opposite body wall, adjacent anatomical sheets (#48
    Wave 1, P0)."""
    faces = _faces_by_membership(me, member)[1]
    tree, owner, _polys = _tri_bvh(me, faces)
    return tree, owner


def _wall_blocked_points(me, weights, faired, offset, static_tree):
    """Count core vertices whose displacement would end through, or within
    the safety clearance of, another sheet of the body.

    Predictive: rays are cast from the UNdisplaced positions along the actual
    displacement direction against the static faces only, so the check runs
    BEFORE any mutation and a refusal leaves the scan untouched.  Only the
    pressed core (w > 0.5) is tested — rim vertices barely move, and
    legitimate concave creases near the rim must not trigger refusals.
    """
    if static_tree is None:
        return 0
    margin = _WALL_CLEARANCE_MM * 0.001
    sign = 1.0 if offset > 0.0 else -1.0
    blocked = 0
    for i, direction in faired.items():
        if weights.get(i, 0.0) <= 0.5:
            continue
        depth = abs(offset) * weights[i]
        location, _n, _idx, _d = static_tree.ray_cast(
            me.vertices[i].co, direction * sign, depth + margin
        )
        if location is not None:
            blocked += 1
    return blocked


def _cross_sheet_pairs(me, static_tree, static_faces, affected):
    """(footprint face, static face) pairs that actually intersect.

    The post-commit safety net behind the predictive ray check: it also
    catches lateral folds into an adjacent sheet that no core ray predicted.
    Pairs sharing a vertex (the footprint's own boundary ring) are ignored;
    pre-existing contacts are baselined out by the caller.
    """
    if static_tree is None or not affected:
        return set()
    moved, moved_owner, _polys = _tri_bvh(me, affected)
    if moved is None:
        return set()
    pairs = set()
    for a, b in moved.overlap(static_tree):
        face_a = moved_owner[a]
        face_b = static_faces[b]
        if set(face_a.vertices) & set(face_b.vertices):
            continue
        pairs.add((face_a.index, face_b.index))
    return pairs


def _edge_face_pairs(affected):
    """Adjacent-face index pairs (shared edge) within the footprint faces."""
    by_edge = {}
    for p in affected:
        vs = p.vertices
        count = len(vs)
        for k in range(count):
            a, b = vs[k], vs[(k + 1) % count]
            key = (b, a) if a > b else (a, b)
            by_edge.setdefault(key, []).append(p.index)
    return [tuple(f) for f in by_edge.values() if len(f) == 2]


def _folded_pairs(me, fold_pairs, pre_face_normals):
    """Faces whose shared edge folded closed (normals turned antiparallel)
    without being folded before the commit.

    This is the flip test's blind window: folding a pre-creased wall flat
    onto its neighbour rotates each face by LESS than 90°, so
    `normal.dot(pre) <= 0` never fires, and the shared edge exempts the pair
    from the self-intersection check (#48 Wave 1, P0 — measured in
    hardendbg `adjfold.foldover_creased`).
    """
    folded = set()
    verts = me.vertices
    for a, b in fold_pairs:
        pre = pre_face_normals[a].dot(pre_face_normals[b])
        if pre <= _FOLD_PRE_DOT:
            continue  # already creased shut before us — not ours
        post = me.polygons[a].normal.dot(me.polygons[b].normal)
        if post < _FOLD_DOT:
            folded.add(a)
            folded.add(b)
        elif post < _HINGE_DOT and pre > _HINGE_PRE_DOT:
            # A hinge is a statement about two REAL faces: a needle's
            # normal is numerically meaningless (measured 1.7° triangles
            # reading 93–97° against sound neighbours), and needles are the
            # sliver rule's business — flagging their neighbours as hinges
            # sent the ladder through 47 s of hopeless retries.
            if _face_height(me, verts, a) < _HINGE_MIN_HEIGHT_M \
                    or _face_height(me, verts, b) < _HINGE_MIN_HEIGHT_M:
                continue
            folded.add(a)
            folded.add(b)
    return folded


def _face_height(me, verts, index):
    """Shortest altitude of a triangle (2·area / longest edge), metres."""
    vs = me.polygons[index].vertices
    if len(vs) != 3:
        return 1.0
    longest = max(
        (verts[vs[k]].co - verts[vs[(k + 1) % 3]].co).length for k in range(3)
    )
    return 2.0 * me.polygons[index].area / longest if longest > 1e-12 else 0.0


def _pad_fold_faces(me, fold_pairs, pre_face_normals, contact):
    """Faces touching an ORIGINAL painted-pad vertex that folded shut in the
    displacement itself, before any repair (the repair then slides those
    original vertices; the commit note discloses it)."""
    n = len(contact)

    def touches_pad(index):
        return any(v < n and contact[v] for v in me.polygons[index].vertices)

    folded = set()
    for a, b in fold_pairs:
        if not (touches_pad(a) or touches_pad(b)):
            continue
        pre = pre_face_normals[a].dot(pre_face_normals[b])
        if pre <= _FOLD_PRE_DOT:
            continue
        if me.polygons[a].normal.dot(me.polygons[b].normal) < _FOLD_DOT:
            folded.add(a)
            folded.add(b)
    return folded


def _surface_confirmed_flips(me, flipped, fold_pairs):
    """Keep only the flipped faces whose own neighbourhood confirms an
    inversion (#49e).

    ``normal · pre_normal <= 0`` asks a single triangle whether it turned
    past 90°, which conflates two very different events: the surface folding
    back on itself (a real defect) and the surface legitimately TILTING under
    a steep authored wall (not a defect — it is the correction).  On a
    coarse scan the second one fires on thin triangles: measured on the
    wrinkled paint15 fixture at 15 mm through a 10 mm feather, face 53270
    reached self-flip −0.05 while its three neighbours sat at dihedral 0.77
    and had themselves rotated 0.64–0.72.  Nothing there is folded, degenerate
    or self-intersecting — and blocking on it threw a healthy refined commit
    away for the unrefined staircase.

    A genuine inversion always creases at least one shared edge past 90°;
    where a whole strip inverts together, its border faces still do, so the
    repair still gets a handle on it.  Self-intersection, degeneracy and
    fold-over stay on their own independent tests — this only narrows the
    single-triangle rotation heuristic.
    """
    if not flipped:
        return set()
    neighbours = {}
    for a, b in fold_pairs:
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
    confirmed = set()
    for index in flipped:
        others = neighbours.get(index)
        if not others:  # no surface to ask — keep the strict answer
            confirmed.add(index)
            continue
        normal = me.polygons[index].normal
        if any(
            normal.dot(me.polygons[other].normal) < _FLIP_CONFIRM_DOT
            for other in others
        ):
            confirmed.add(index)
    return confirmed


def _apply_dissolve(temp_me, plans, n_start):
    """Apply accumulated seam-sliver dissolve plans to a COPY of the
    once-computed refined mesh (#49d perf: re-running the deterministic
    refinement per retry measured 13 s commits).  Each plan's NEW-vertex
    indices were identified with all earlier plans already applied, so
    sequential application keeps every plan's numbering valid.  Each vertex
    is removed by a SEQUENTIAL link-condition-gated edge collapse (nearest
    ORIGINAL neighbour preferred) — the only manifold-safe single collapse;
    a vertex with no safe collapse stays and the validation ladder decides.
    Original scan vertices never move; every surviving vertex keeps its
    authored/field weight."""
    bm = bmesh.new()
    bm.from_mesh(temp_me)
    for target_verts, expected in plans:
        bm.verts.index_update()
        if len(bm.verts) != expected:
            break  # determinism broken — the fallback decides honestly
        bm.verts.ensure_lookup_table()
        plan_refs = [
            bm.verts[vi] for vi in sorted(target_verts)
            if n_start <= vi < len(bm.verts)
        ]
        plan_set = set(plan_refs)
        for v in plan_refs:
            if not v.is_valid:
                continue
            for e in sorted(v.link_edges,
                            key=lambda e: (e.calc_length(), _ekey(e))):
                n = e.other_vert(v)
                if n in plan_set or not n.is_valid:
                    continue
                if n.index >= n_start:
                    # prefer an ORIGINAL target if one is also safe
                    better = None
                    for e3 in sorted(v.link_edges,
                                     key=lambda e3: (e3.calc_length(),
                                                     _ekey(e3))):
                        m = e3.other_vert(v)
                        if (m.index < n_start and m not in plan_set
                                and m.is_valid):
                            nbrs_v = {
                                e4.other_vert(v) for e4 in v.link_edges
                            }
                            nbrs_m = {
                                e5.other_vert(m) for e5 in m.link_edges
                            }
                            if len(nbrs_v & nbrs_m) == 2:
                                better = m
                                break
                    if better is not None:
                        n = better
                if _link_safe_collapse(bm, v, n):
                    break
        bm.normal_update()
    bm.to_mesh(temp_me)
    bm.free()
    temp_me.update()


def _refine_footprint(temp_me, group_index, offset,
                      curved=True, harmonic=True, field=None):
    """Adaptive local refinement of the footprint on the WORKING mesh (#49).

    Splits only edges whose predicted post-displacement length exceeds the
    wall's sampling requirement (derived from the authored profile's peak
    slope and per-edge turning); confined to weighted edges; no-op on
    already-dense meshes; new-vertex weights of THIS region re-evaluated
    from the authored field (other regions' masks interpolate through the
    deform layer).  Returns (verts_added, h_target_mm).

    Seam-sliver dissolution lives in ``_apply_dissolve`` (#49d): the
    refined state is computed ONCE per commit and dissolve retries operate
    on copies of it.

    ``curved`` (#49c): place split points by Phong tessellation — projected
    onto the parent vertices' tangent planes — instead of on the flat parent
    triangle.  Linear splitting leaves the refined base piecewise-flat at
    the ORIGINAL facet scale, so even a perfectly smooth field commits a
    faceted wall on coarse scans; the lift curves the base through the
    original vertices WITHOUT moving them.  Applied only where both parent
    endpoints carry weight (unweighted new vertices must stay exactly on
    the original surface — the feather 'outside' contract is 0.001 mm) and
    only across agreeing normals (no crease bulging).

    ``harmonic`` (#49c): after refinement, relax the NEW vertices' weights
    to the harmonic solution anchored at the ORIGINAL authored samples
    (Gauss–Seidel on the refined connectivity).  IDW's gradient vanishes at
    every sample point — a flat spot per original vertex, read as ring
    ridges in the wall; the harmonic field is smooth between anchors, never
    overshoots (maximum principle), and keeps every authored weight exact.

    ``field`` (#49e): a closed-form evaluator for the authored falloff, from
    ``_authored_rim_field``.  When present it REPLACES the IDW+harmonic
    interpolation for new vertices — no interpolant can be smoother than the
    function it interpolates, and this one is pinned to the coarse original
    lattice.  ``None`` (library/style and legacy regions) keeps the
    interpolation path exactly as it was.
    """
    weights = {}
    for v in temp_me.vertices:
        for g in v.groups:
            if g.group == group_index:
                weights[v.index] = g.weight
                break
    if not weights:
        return 0, 0.0
    mean_edge = _mean_touching_edge(temp_me, weights)
    if mean_edge is None:
        return 0, 0.0
    amount_mm = abs(offset) * 1000.0

    # Per-edge sampling requirement (no global feather guess): the local
    # wall slope g = |amount|·|Δw|/L sets both the rows the transition
    # needs (per-edge turning ≤ 0.25 rad) and the wall arc those rows
    # span; an edge splits ONLY when its predicted post-displacement
    # length exceeds 1.4× its own requirement.  The requirement is
    # ABSOLUTE (mm, from amount and turning): a mesh already denser than
    # every local requirement is a no-op by construction — and a COARSE
    # scan must be refined down to the same requirement, never to its own
    # coarseness (#49b: a mean-edge floor here made the input
    # triangulation the ceiling of output quality — the staircase
    # survived verbatim on coarse scans).  Splitting cannot reduce the
    # stretch RATIO (halving L halves Δw too), it fixes SAMPLING.
    def h_required(g):
        if g < 0.35:
            return None  # gentle turning: a ramp at any density, no shelf
        rows = max(4, int(math.ceil(2.0 * math.atan(g) / 0.25)))
        wall_arc_mm = (1.5 * amount_mm / g) * math.sqrt(1.0 + g * g)
        return max(0.0012, wall_arc_mm / rows * 0.001)

    h_target = mean_edge  # provenance figure: tightest requirement seen

    # #54 Task 3: turning criterion from the analytic profile.  The slope
    # rule above is blind to a corner (a 1 mm fillet drawn with 1 mm edges
    # passed it untouched, DEC-0064); an edge inside a fillet band must not
    # turn more than _CORNER_TURN, floored at half the mesh's own edge so a
    # coarse scan is refined one halving, not remeshed (contract growth gate).
    corner_radius = getattr(field, "corner_radius", None)
    distance_of = getattr(field, "distance", None)
    corner_floor = _corner_edge_floor(mean_edge)
    distance_cache = {}

    def corner_requirement(va, vb):
        if corner_radius is None or distance_of is None:
            return None
        radius = None
        for v in (va, vb):
            d = distance_cache.get(v)
            if d is None:
                d = distance_of(v.co)
                distance_cache[v] = d
            r = corner_radius(d)
            if r is not None and (radius is None or r < radius):
                radius = r
        if radius is None:
            return None
        if radius < corner_floor / _CORNER_SKIP_TURN:
            return None  # undrawable at the floor: the commit note says so
        return max(_CORNER_TURN * radius, corner_floor)

    if field is not None:
        # #49e: the authored falloff is a closed-form function of the
        # region's own boundary — sample it at the new vertices instead of
        # interpolating the coarse authored samples.  IDW + the harmonic
        # pass is a good interpolant, but it is PINNED at the original
        # vertices, so a coarse scan's anchor lattice prints its own ring of
        # kinks into the wall (measured, A-model waist 20/15, same mesh and
        # same field: wall dihedral p95 23.0° interpolated vs 17.6° sampled,
        # edges over 30° 35 vs 12).
        sampler = field
        harmonic = False
    else:
        # New-vertex weights come from a smooth 3D IDW over the ORIGINAL
        # vertices' authored weights.  Parent-edge interpolation provably
        # keeps the staircase; a chart-space field disagrees with the
        # authored per-vertex weights exactly at creases (measured:
        # fold-scale weight jumps).  k-NN IDW in 3D is smooth, exactly
        # consistent with the surviving original weights, and needs no
        # snapshot (legacy and library regions refine too).
        entries = [
            (temp_me.vertices[i].co.copy(), w) for i, w in weights.items()
        ]
        field_kd = kdtree.KDTree(len(entries))
        for index, (co, _w) in enumerate(entries):
            field_kd.insert(co, index)
        field_kd.balance()
        support = 2.5 * mean_edge
        eps2 = (0.35 * mean_edge) ** 2

        def sampler(co_local):
            numerator = 0.0
            denominator = 0.0
            for _co, index, dist in field_kd.find_n(co_local, 6):
                if dist > support:
                    continue
                kernel = 1.0 / (dist * dist + eps2)
                numerator += entries[index][1] * kernel
                denominator += kernel
            return numerator / denominator if denominator else 0.0

    bm = bmesh.new()
    bm.from_mesh(temp_me)
    deform = bm.verts.layers.deform.verify()
    added = 0
    n_start = len(bm.verts)
    all_new = []
    # Perf (#49c): every candidate edge has a weighted endpoint, so scan the
    # weighted verts' link edges instead of the whole mesh (measured: the
    # full-mesh scans dominated large commits — 133k edges × rounds).
    bm.verts.ensure_lookup_table()
    field_verts = [bm.verts[i] for i in weights]
    for _round in range(4):
        bm.normal_update()
        marked = []
        seen_edges = set()
        for fv in field_verts:
            if not fv.is_valid:
                continue
            for e in fv.link_edges:
                if e in seen_edges:
                    continue
                seen_edges.add(e)
                marked.append(e)
        candidates = marked
        marked = []
        for e in candidates:
            wa = e.verts[0][deform].get(group_index, 0.0)
            wb = e.verts[1][deform].get(group_index, 0.0)
            if wa <= 0.0 and wb <= 0.0:
                continue
            # Never refine across a genuinely SHARP crease (>72° dihedral):
            # pressing walls physically collide there at fine resolution.
            # Mild scan wrinkles (50–70°) must refine WITH the wall — an
            # unrefined edge bordering refined neighbours becomes a seam
            # sliver that collapses under displacement (measured).  A
            # failed repair still falls back to a fully unrefined commit.
            faces = e.link_faces
            if len(faces) == 2 and faces[0].normal.dot(faces[1].normal) < 0.3:
                continue
            length = (e.verts[0].co - e.verts[1].co).length
            if length < 1e-9:
                continue
            g = abs(offset) * abs(wa - wb) / length
            predicted = math.hypot(length, abs(offset) * abs(wa - wb))
            need = None
            h_req = h_required(g)
            if h_req is not None and predicted > 1.4 * h_req:
                need = h_req
            # The corner rule compares the PRE-displacement length: with the
            # floor at half the mesh edge that is exactly one halving per
            # commit in the fillet bands (the stretched length would demand
            # two, measured 3.25x footprint faces on the B x4 fixture).
            h_corner = corner_requirement(e.verts[0], e.verts[1])
            if h_corner is not None and length > 1.4 * h_corner:
                need = h_corner if need is None else min(need, h_corner)
            if need is not None:
                h_target = min(h_target, need)
                marked.append(e)
        if not marked:
            break
        # #53: subdivide_edges numbers the round's new vertices in INPUT
        # order, and every later sort keys on those numbers — so the input
        # order must not be the disk-cycle/pool order left by earlier edits.
        marked.sort(key=_ekey)
        # Single-cut rounds: each round halves the offending edges, then
        # re-marks with RE-EVALUATED weights — simple, deterministic, and
        # free of cross-call reference invalidation.  Subdivision never
        # removes vertices, so the round's new vertices are exactly the
        # tail of the vertex table.
        lift_map = {}
        if curved:
            # Phong tessellation record per marked edge, keyed by the exact
            # midpoint the subdivide will place the new vertex at.
            for e in marked:
                va, vb = e.verts
                wa = va[deform].get(group_index, 0.0)
                wb = vb[deform].get(group_index, 0.0)
                if wa <= 0.0 or wb <= 0.0:
                    continue  # boundary edge: stay on the original surface
                na, nb = va.normal, vb.normal
                if na.dot(nb) < 0.3:
                    continue  # crease: no bulging
                mid = (va.co + vb.co) * 0.5
                proj_a = mid - na * (mid - va.co).dot(na)
                proj_b = mid - nb * (mid - vb.co).dot(nb)
                lift = (proj_a + proj_b) * 0.5
                key = (round(mid.x, 8), round(mid.y, 8), round(mid.z, 8))
                lift_map[key] = mid + (lift - mid) * 0.75
        n_before = len(bm.verts)
        split = bmesh.ops.subdivide_edges(
            bm, edges=marked, cuts=1, use_grid_fill=False,
        )
        fresh = {
            ele for ele in split.get("geom_inner", ())
            if isinstance(ele, bmesh.types.BMVert)
        }
        ngons = [f for f in bm.faces if len(f.verts) > 3]
        if ngons:
            ngons.sort(key=_fkey)
            _split_refined_ngons(bm, ngons, fresh)
        # Fresh vertices are created with index -1; the #53 tie-break keys
        # need every vertex uniquely numbered (new ones are the tail).
        bm.verts.index_update()
        bm.verts.ensure_lookup_table()
        new_verts = list(bm.verts[n_before:])
        if lift_map:
            for v in new_verts:
                key = (round(v.co.x, 8), round(v.co.y, 8), round(v.co.z, 8))
                lifted = lift_map.get(key)
                if lifted is not None:
                    v.co = lifted
        all_new.extend(new_verts)
        if sampler is not None:
            for v in new_verts:
                dv = v[deform]
                if group_index in dv or any(
                    n[deform].get(group_index, 0.0) > 0.0
                    for e in v.link_edges for n in (e.other_vert(v),)
                ):
                    w = sampler(v.co)
                    if w > 0.0:
                        dv[group_index] = w
                        field_verts.append(v)
                    elif group_index in dv:
                        del dv[group_index]
        added += len(new_verts)

    if all_new:
        # Quality pass (mesh-quality lens): splitting alone leaves slivers
        # whose normals flip unstably under displacement (measured: 0.19 mm
        # edges, collinear caps at 1e-7 m²).  The classical triad completes
        # split with COLLAPSE and FLIP — always position-preserving for
        # original scan vertices.
        new_set = {v for v in all_new if v.is_valid}
        short_limit = 0.35 * h_target
        for v in sorted(new_set, key=lambda v: v.index):
            if not v.is_valid:
                continue
            for e in sorted(v.link_edges,
                            key=lambda e: (e.calc_length(), _ekey(e))):
                if e.calc_length() >= short_limit:
                    break
                # weld the NEW vert onto its neighbour — link-gated (#49d)
                if _link_safe_collapse(bm, v, e.other_vert(v)):
                    break
        # Flip toward max-min-angle on every interior edge of the touched
        # zone (flips change triangulation, never positions).  Scoped scan:
        # any face with a weighted vert is reachable from a field vert.
        interior = []
        seen_edges = set()
        for fv in field_verts:
            if not fv.is_valid:
                continue
            for f in fv.link_faces:
                for e in f.edges:
                    if e in seen_edges:
                        continue
                    seen_edges.add(e)
                    if len(e.link_faces) == 2:
                        interior.append(e)
        if interior:
            # Deterministic input order (sets iterate by pointer, disk
            # cycles by edit history): flips must be bit-reproducible run
            # to run and independent of the collapse primitive (#53).
            bm.faces.index_update()
            interior.sort(key=_ekey)
            seen = set()
            faces = []
            for e in interior:
                for f in e.link_faces:
                    if f not in seen:
                        seen.add(f)
                        faces.append(f)
            faces.sort(key=_fkey)
            bmesh.ops.beautify_fill(bm, faces=faces, edges=interior)
        # Cap sweep: a face whose two short edges were split but whose long
        # edge was not becomes a collinear sliver beautify may refuse to
        # touch (non-convex quad on a crease) — rotate its long edge
        # directly; positions never change.
        new_set = {v for v in new_set if v.is_valid}
        cap_edges = []
        cap_seen = set()
        cap_faces = []
        for v in sorted(new_set, key=lambda v: v.index):
            for f in v.link_faces:
                if f not in cap_seen:
                    cap_seen.add(f)
                    cap_faces.append(f)
        cap_faces.sort(key=_fkey)
        for f in cap_faces:
            if len(f.verts) != 3:
                continue
            els = [(e.calc_length(), e) for e in f.edges]
            longest, e_long = max(els, key=lambda t: (t[0], _ekey(t[1])))
            area = f.calc_area()
            if longest > 1e-9 and 2.0 * area / longest < 0.35 * h_target \
                    and len(e_long.link_faces) == 2:
                cap_edges.append(e_long)
        if cap_edges:
            seen = set()
            unique = []
            for e in cap_edges:
                if e.is_valid and e not in seen:
                    seen.add(e)
                    unique.append(e)
            unique.sort(key=_ekey)
            # One batch call on purpose: every bmesh.ops call pays a
            # whole-mesh setup, and rotating cap edges one at a time
            # measured 22 s for 261 refinement vertices on a 180k mesh
            # (#54 Task 6).  The rim needles that motivated the attempt
            # turned out to be the SCAN's own needle triangles inherited
            # by the split, not cap slivers.
            try:
                bmesh.ops.rotate_edges(bm, edges=unique, use_ccw=False)
            except RuntimeError:
                pass
        # Sliver purge: any residual refinement-born triangle thinner than
        # the sampling target has a numerically unstable normal that folds
        # under displacement (measured: every stubborn fold was such a
        # sliver).  Collapse its shortest new-vertex edge — deterministic,
        # never moves an original vertex, repeated until clean.  Each pass
        # sees only the faces alive at its start (see the alias note below),
        # so the collapses' own new faces wait for the next pass; the loop
        # ends on the first pass that collapses nothing (measured: the old
        # two-pass cap only converged because aliased wrappers happened to
        # reach the new faces early — #53).
        for _purge in range(8):
            new_set = {v for v in new_set if v.is_valid}
            purge_seen = set()
            purge_faces = []
            for v in sorted(new_set, key=lambda v: v.index):
                for f in v.link_faces:
                    if f not in purge_seen:
                        purge_seen.add(f)
                        purge_faces.append(f)
            # Keep each face's identity beside its wrapper (#53): collapses
            # later in this same pass kill faces and create new ones, and
            # BMesh reuses freed slots, so a stale wrapper can come back
            # is_valid while pointing at a DIFFERENT face.  Which slot gets
            # reused depends on the allocator's history, not the geometry —
            # the old purge silently processed such aliases.
            # Worklist: the faces alive at the start of the pass, then every
            # face a collapse or rotation creates, examined right away —
            # a fresh sliver next to a just-collapsed vertex must not wait
            # for the next pass (measured: deferring it left a 125 degree
            # fold on the painted golden route).
            queue = sorted(
                ((_fkey(f), f) for f in purge_faces), key=lambda t: t[0]
            )
            any_collapsed = False
            qi = 0
            while qi < len(queue):
                fk, f = queue[qi]
                qi += 1
                if not f.is_valid or len(f.verts) != 3 or _fkey(f) != fk:
                    continue
                els = [(e.calc_length(), e) for e in f.edges]
                longest = max(length for length, _e in els)
                if longest < 1e-9 or 2.0 * f.calc_area() / longest                         >= 0.3 * h_target:
                    continue
                touched = None
                for _length, e in sorted(
                        els, key=lambda t: (t[0], _ekey(t[1]))):
                    if not e.is_valid:
                        continue
                    va, vb = e.verts
                    if va in new_set and _link_safe_collapse(bm, va, vb):
                        touched = [vb]
                        break
                    if vb in new_set and _link_safe_collapse(bm, vb, va):
                        touched = [va]
                        break
                if touched is None:
                    # No link-safe collapse: rotate the sliver's long edge
                    # instead — position-preserving, manifold-safe, and the
                    # classical escape for an uncollapsible thin triangle
                    # (#49d: one such survivor displaced into an inverted
                    # face on the decim065 fixture).
                    _l, e_long = max(els, key=lambda t: (t[0], _ekey(t[1])))
                    if e_long.is_valid and len(e_long.link_faces) == 2:
                        try:
                            bmesh.ops.rotate_edges(
                                bm, edges=[e_long], use_ccw=False
                            )
                            # Rotation-born faces wait for the next pass:
                            # queueing them here lets two slivers rotate
                            # the same edge back and forth forever
                            # (measured: a commit that never returned).
                            touched = []
                        except RuntimeError:
                            pass
                if touched is not None:
                    any_collapsed = True
                    # Only collapse targets grow the queue — every collapse
                    # removes a vertex, so this terminates.
                    grown = []
                    for v in touched:
                        if v.is_valid:
                            grown.extend(v.link_faces)
                    queue.extend(sorted(
                        ((_fkey(g), g) for g in grown), key=lambda t: t[0]
                    ))
            if not any_collapsed:
                break
        bm.normal_update()
        live_new = [v for v in all_new if v.is_valid]
        for _pass in range(2):
            moves = []
            for v in live_new:
                neighbors = [e.other_vert(v) for e in v.link_edges]
                if not neighbors:
                    continue
                mean = Vector()
                for n in neighbors:
                    mean += n.co
                mean /= len(neighbors)
                delta = mean - v.co
                normal = v.normal
                delta -= normal * delta.dot(normal)
                moves.append((v, v.co + delta * 0.5))
            for v, co in moves:
                v.co = co
            bm.normal_update()
        if sampler is not None:
            for v in live_new:
                dv = v[deform]
                if group_index in dv:
                    w = sampler(v.co)
                    if w > 0.0:
                        dv[group_index] = w
                    else:
                        del dv[group_index]
        if harmonic:
            # Harmonic field relaxation (#49c): Gauss–Seidel toward the
            # Laplace solution on the refined connectivity, ORIGINAL
            # authored weights (including implicit zeros) as fixed anchors,
            # NEW vertices only.  Deterministic (sorted order), bounded,
            # no overshoot by the maximum principle.
            live_new = [v for v in live_new if v.is_valid]
            live_new.sort(key=lambda v: v.index)
            relax_field = [
                v for v in live_new
                if group_index in v[deform] or any(
                    n[deform].get(group_index, 0.0) > 0.0
                    for e in v.link_edges for n in (e.other_vert(v),)
                )
            ]
            for _pass in range(24):
                for v in relax_field:
                    total = 0.0
                    count = 0
                    for e in v.link_edges:
                        n = e.other_vert(v)
                        total += n[deform].get(group_index, 0.0)
                        count += 1
                    if count:
                        v[deform][group_index] = total / count
            for v in relax_field:
                dv = v[deform]
                if dv.get(group_index, 0.0) <= 1e-6 and group_index in dv:
                    del dv[group_index]

    # The weld pass removes some of the counted vertices — the DECLARED
    # provenance must be the final net growth, exactly.
    added = len(bm.verts) - n_start
    bm.to_mesh(temp_me)
    bm.free()
    temp_me.update()
    return added, h_target * 1000.0


def _split_refined_ngons(bm, ngons, fresh):
    """Triangulate the n-gons a single-cut ``subdivide_edges`` leaves.

    Only the QUAD with exactly one new midpoint (``fresh`` = the vertices the
    subdivide just created; it runs before ``index_update``, in the same face
    order as the plain triangulation it replaces) is split by hand — midpoint to the opposite vertex.  When that midpoint is
    not Phong-lifted (endpoint normals nearly equal: exactly the fillet
    bands) it lies on the old edge line, the quad has a 180° corner, and
    ``bmesh.ops.triangulate``'s beauty rule ties and falls back to the
    first diagonal — the OLD edge — on both sides of the split, stacking
    four faces on one edge (measured: six non-manifold edges per commit,
    which the ladder correctly refused; ERR-0038).  Every other n-gon keeps
    the beauty triangulation: on irregular scan triangles it measurably
    beats fixed patterns (golden painted route p95 17.6° vs 21.3°).
    """
    fallback = []
    for face in ngons:
        if not face.is_valid:
            continue
        verts = list(face.verts)
        if len(verts) == 4:
            mids = [k for k, v in enumerate(verts) if v in fresh]
            if len(mids) == 1:
                k = mids[0]
                mid, prev, nxt = verts[k], verts[k - 1], verts[(k + 1) % 4]
                # Only the UNLIFTED midpoint (boundary / crease edges keep
                # it exactly on the old edge line) is degenerate for beauty;
                # a lifted midpoint makes the quad convex and beauty's
                # Delaunay choice is the right one — and measurably smooths
                # better afterwards than a fixed pattern (regionqualtest
                # w49f: ridges after Smooth Area 75 vs ceiling 64).
                chord = nxt.co - prev.co
                length = chord.length_squared
                if length > 1e-24:
                    rel = mid.co - prev.co
                    off = rel - chord * (rel.dot(chord) / length)
                    if off.length_squared < 1e-8 * length:  # 1e-4 relative
                        bmesh.utils.face_split(face, mid, verts[(k + 2) % 4])
                        continue
        fallback.append(face)
    if fallback:
        bmesh.ops.triangulate(bm, faces=fallback)


def _ekey(e):
    """Order-independent edge identity for tie-breaks (#53): refinement
    midpoints make exactly equal edge lengths common, and a length-only sort
    then falls back to BMesh's internal element order, which depends on the
    history of creates and kills — so the refined topology depended on which
    collapse primitive ran.  Vertex indices survive every local edit."""
    a, b = e.verts[0].index, e.verts[1].index
    return (a, b) if a < b else (b, a)


def _fkey(f):
    return tuple(sorted(v.index for v in f.verts))


def _link_safe_collapse(bm, v, n):
    """Collapse ``v`` onto its edge-neighbour ``n`` iff the classical LINK
    CONDITION holds (their shared neighbours are exactly the two opposite
    vertices of the edge) — the only manifold-safe single edge collapse.
    Clump welds without this test measurably tore holes and built fins
    (#49d: 16 non-manifold edges on one commit).  Returns True on collapse.
    """
    if not (v.is_valid and n.is_valid):
        return False
    nbrs_v = {e.other_vert(v) for e in v.link_edges}
    nbrs_n = {e.other_vert(n) for e in n.link_edges}
    if len(nbrs_v & nbrs_n) != 2:
        return False
    # #53 perf: bmesh.ops.weld_verts walks the WHOLE mesh per call (29 ms at
    # 89k faces, 188 ms at 357k) and a commit makes ~100 collapses — 60% of
    # commit time at either size.  On a manifold all-triangle star the edge
    # collapse v->n is exactly "dissolve v into one polygon, fan-triangulate
    # from n" (the two faces on edge v-n vanish, every other (v,a,b) becomes
    # (n,a,b)): three local bmesh.utils calls, O(valence).  Anything else
    # (boundary, non-manifold, n-gons) keeps the mesh-wide weld verbatim.
    if (
        n in nbrs_v
        and v.is_manifold
        and not v.is_boundary
        and all(len(f.verts) == 3 for f in v.link_faces)
        and _fan_collapse(v, n, nbrs_v - {n})
    ):
        # bmesh.ops calls renumber every element table on exit; the local
        # utils do not.  Every later pass sorts on .index, so keep the
        # numbering identical to what the weld left (measured: without
        # this the refined topology differs from the first collapse on).
        bm.verts.index_update()
        bm.edges.index_update()
        bm.faces.index_update()
        return True
    bmesh.ops.weld_verts(bm, targetmap={v: n})
    return True


def _fan_collapse(v, n, link):
    """Local v->n collapse: dissolve ``v`` (its star becomes one polygon over
    ``link``), then split that polygon into a fan from ``n``.  False only
    when the dissolve refuses before touching anything."""
    if not bmesh.utils.vert_dissolve(v):
        return False
    poly = None
    for f in n.link_faces:
        if len(f.verts) > 3 and link <= set(f.verts):
            poly = f
            break
    while poly is not None and len(poly.verts) > 3:
        verts = [loop.vert for loop in poly.loops]
        other = verts[(verts.index(n) + 2) % len(verts)]
        new_face, _loop = bmesh.utils.face_split(poly, n, other)
        if len(new_face.verts) > len(poly.verts):
            poly = new_face
    return True


def _nonmanifold_count(me):
    """Edges not shared by exactly two faces (#49d transactional guard):
    dissolution welds are the commit's only topology-editing step and must
    never change the mesh's manifoldness — a fin or duplicate face that the
    local weld cleanup missed must never ship."""
    edge_indices = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("edge_index", edge_indices)
    counts = np.bincount(edge_indices, minlength=len(me.edges))
    return int(np.count_nonzero(counts != 2))


def _sliver_dissolve_plan(temp, remaining, n_orig):
    """Plan the #49 seam-sliver dissolution retry, or None.

    A plan exists only when EVERY still-defective face is refinement-born
    (touches at least one new vertex) and the defect is small enough to be
    a seam artefact rather than a genuinely infeasible wall (measured seam
    failures: 1–2 faces).  An original-geometry defect, or a large defect
    set, is not ours to dissolve — the unrefined fallback is then the
    honest answer.
    """
    if not remaining or len(remaining) > 12:
        return None  # a defect field that large = genuinely infeasible zone
    seed = set()
    for fi in remaining:
        new_on_face = [
            vi for vi in temp.polygons[fi].vertices if vi >= n_orig
        ]
        if not new_on_face:
            return None  # an original-geometry fold — not ours to dissolve
        seed.update(new_on_face)
    # ALL seam clusters in one plan (#49d): per-cluster retries cost a full
    # pipeline run per cluster (measured 15 s commits).  Joint welding was
    # only dangerous when clump welds could tear — every collapse is now
    # link-condition-gated, so the joint plan is safe by construction and
    # most walls converge in 1–2 retries.
    # Expand to the one-ring NEW neighbourhood: dissolving only the exact
    # defective vertices lets the fold migrate to the adjacent seam sliver
    # (measured) — dissolving the whole local seam returns that one spot
    # to original sampling in a single deterministic step.
    verts = set(seed)
    for e in temp.edges:
        a, b = e.vertices
        if a in seed and b >= n_orig:
            verts.add(b)
        elif b in seed and a >= n_orig:
            verts.add(a)
    if not verts or len(verts) > 48:
        return None
    return frozenset(verts), len(temp.vertices)


def _repair_folds(me, weights, pre_face_normals, pre_vertex_normals,
                  adjacency, baseline, affected=None, fold_pairs=(),
                  new_start=None, sliver_h=0.0):
    """Remove folded, degenerate or self-intersecting slivers after commit.

    Slides ONLY the vertices of defective faces (plus one ring, never outside
    the mask) toward their one-ring mean, restricted to the pre-commit
    tangent plane — the normal component, i.e. the clinical mm amount, is
    preserved by construction.  ``baseline`` holds face indices that were
    already defective BEFORE the commit (dirty scans) — those are not ours to
    fix and never count.  Deterministic, bounded, self-terminating.
    Returns the number of faces still defective after the pass.

    ``new_start`` (#49): first REFINEMENT vertex index of a refined commit.
    When the tangential phase stalls (a seam sliver on a crease-excluded
    edge has diverging faired directions — tangential sliding provably
    cannot unfold it), the remaining defective faces' NEW vertices only are
    allowed full one-ring relaxation, normal component included.  A new
    vertex carries no authored amount — its normal position is derived from
    the field sampling — so the clinical promise (original scan vertices
    keep their exact authored displacement) is untouched.
    """
    member = {i for i, w in weights.items() if w > 0.0}
    if not member:
        return set()
    if affected is None:
        affected = _faces_by_membership(me, member)[0]

    def defective(strict=True):
        """``strict`` drives what the repair AIMS at; the relaxed reading
        decides what may not SHIP (#49e).

        Keeping the single-triangle rotation test as a repair target is
        useful — sliding a face back before it creases anything is cheap
        insurance, and dropping it from the target set measurably let real
        inversions through on the circle fixtures.  But leaving an
        unconfirmed rotation in the RETURNED set is what threw a healthy
        refined commit away for the unrefined staircase, so the two
        questions are answered separately.
        """
        bad = {p.index for p in affected if p.area < 1e-12}
        flipped = {
            p.index for p in affected
            if p.normal.dot(pre_face_normals[p.index]) <= 1e-9
        }
        bad |= (
            flipped if strict
            else _surface_confirmed_flips(me, flipped, fold_pairs)
        )
        bad |= _footprint_self_intersections(me, member, affected)
        bad |= _folded_pairs(me, fold_pairs, pre_face_normals)
        if new_start is not None and sliver_h > 0.0:
            # Refined commits only (#49): displacement can compress a
            # refinement-born triangle into a sub-sampling sliver whose
            # normal is numerically meaningless (measured: 0.24 mm height
            # against a 2.38 mm sampling target) — those are ours to fix,
            # via escalation, before the commit is accepted.
            for p in affected:
                vs = p.vertices
                if len(vs) != 3 or not any(vi >= new_start for vi in vs):
                    continue
                longest = max(
                    (me.vertices[vs[k]].co
                     - me.vertices[vs[(k + 1) % 3]].co).length
                    for k in range(3)
                )
                if longest > 1e-9 and 2.0 * p.area / longest < sliver_h:
                    bad.add(p.index)
        return bad - baseline

    # (returns the set of still-defective face indices — empty on success)

    bad = defective()
    # 40 iterations, not 20: refined footprints (#49) have smaller one-rings,
    # so each tangential step is proportionally smaller and deep crease folds
    # need more of them to unwind.  Still bounded, still deterministic.
    stall = 0
    prev_key = None
    escalated = False
    for iteration in range(40):
        if not bad:
            return set()
        # Escalation (#49): a seam sliver whose faired directions diverge is
        # provably tangential-unfixable, and every wasted tangential
        # iteration slides the surrounding ORIGINAL vertices around,
        # grinding collateral damage (edge stretch, off-profile reversals)
        # into a healthy wall.  So: detect the stall (identical defect set 3
        # iterations running) and switch to moving ONLY the defective
        # faces' own NEW vertices — full one-ring relaxation, normal
        # component included.  Never the ring, never originals.
        key = tuple(sorted(bad))
        stall = stall + 1 if key == prev_key else 0
        prev_key = key
        if new_start is not None and not escalated and stall >= 3:
            escalated = True
        if stall >= 16:
            # The defect set survived 16 straight iterations of tangential
            # AND escalated moves unchanged — provably stuck.  Grinding the
            # remaining budget is pure frozen UI on the failure path
            # (measured 10.8 s commits on large regions, read by the
            # orthotist as "no action at all").
            break
        if escalated:
            relax = {
                vi for p_index in bad
                for vi in me.polygons[p_index].vertices
                if vi >= new_start
            }
            if not relax:
                break  # an all-original defect — escalation cannot help
        else:
            relax = set()
            for p_index in bad:
                for vi in me.polygons[p_index].vertices:
                    if vi in member:
                        relax.add(vi)
                    for neighbor in adjacency.get(vi, ()):
                        if neighbor in member:
                            relax.add(neighbor)
        for vi in sorted(relax):
            neighbors = adjacency.get(vi)
            if not neighbors:
                continue
            mean = Vector()
            for j in neighbors:
                mean += me.vertices[j].co
            mean /= len(neighbors)
            delta = mean - me.vertices[vi].co
            if not escalated:
                normal = pre_vertex_normals[vi]
                delta -= normal * delta.dot(normal)  # tangential slide only
            me.vertices[vi].co += delta * 0.5
        me.update()
        bad = defective()
    return defective(strict=False)


def _weights_from_style(scan, entry, target_world, target_normal, coords):
    """Evaluate the stored style field at every (evaluated) target vertex.

    Returns a continuous weight field: bilinear grid for v2 entries, IDW for
    v1 sample clouds; a soft normal-offset guard fades over [tol, 2*tol]
    instead of cutting, and only the cursor-connected patch survives.
    """
    side, up, outward = _surface_frame(target_normal)
    samples = entry["samples"]
    field = entry.get("field") or None
    tree = None
    support = eps2 = 0.0
    if field is None:
        spacing = max(0.5, float(entry.get("sample_radius_mm", 3.0)) / 1.75)
        support = spacing * 2.5
        eps2 = (spacing * 0.35) ** 2
        tree = kdtree.KDTree(len(samples))
        for index, sample in enumerate(samples):
            tree.insert((sample[0], sample[1], 0.0), index)
        tree.balance()
    tolerance = max(5.0, float(entry.get("normal_tolerance_mm", 15.0)))
    matrix = scan.matrix_world
    weights = {}
    for index, co in enumerate(coords):
        relative = matrix @ co - target_world
        normal_offset = abs(relative.dot(outward)) * 1000.0
        if normal_offset >= tolerance * 2.0:
            continue
        u = relative.dot(side) * 1000.0
        v = relative.dot(up) * 1000.0
        if field is not None:
            weight = _field_weight(field, u, v)
        else:
            weight = _idw_weight(samples, tree, u, v, support, eps2)
        if weight <= 0.005:
            continue
        if normal_offset > tolerance:
            t = 1.0 - (normal_offset - tolerance) / tolerance
            weight *= t * t * (3.0 - 2.0 * t)
            if weight <= 0.005:
                continue
        weights[index] = weight
    weights = _connected_subset(scan, weights, coords, target_world)
    return _geodesic_trim(
        scan, weights, coords, target_world, samples,
        entry.get("max_geodesic_mm"),
    )


def _geodesic_trim(scan, weights, coords, target_world, samples,
                   max_geodesic_mm=None):
    """Soft-trim vertices the authored region could never have reached, and
    measure the realized surface size.

    The tangent-plane mapping is extrinsic: it happily assigns weights across
    a concave fold to surface 22 mm away in space but 50 mm away along the
    surface.  The authored region (paint or geodesic circle) is intrinsic, so
    the surface path from the cursor, measured inside the footprint, must not
    exceed the authored size; the excess fades out smoothly, never a cliff.

    The limit is the style's stored INTRINSIC size (``max_geodesic_mm``,
    surface mm — Wave 2 decision) so distant lobes of non-convex pads
    survive; legacy entries fall back to the chart's chord extent.
    Returns (trimmed weights, realized surface radius in mm).
    """
    if not weights:
        return weights, 0.0
    if max_geodesic_mm:
        limit = float(max_geodesic_mm) * 1.15 * 0.001
    else:
        limit = max(math.hypot(s[0], s[1]) for s in samples) * 1.35 * 0.001
    if limit <= 0.0:
        return weights, 0.0
    me = scan.data
    matrix = scan.matrix_world
    member = set(weights)
    seed = min(
        member,
        key=lambda i: (matrix @ coords[i] - target_world).length_squared,
    )
    neighbors = {}
    for edge in me.edges:
        a, b = edge.vertices
        if a in member and b in member:
            length = (coords[a] - coords[b]).length
            neighbors.setdefault(a, []).append((b, length))
            neighbors.setdefault(b, []).append((a, length))
    dist = {seed: 0.0}
    heap = [(0.0, seed)]
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist.get(i, 1e30):
            continue
        for j, length in neighbors.get(i, ()):
            nd = d + length
            if nd <= limit and nd < dist.get(j, 1e30):
                dist[j] = nd
                heapq.heappush(heap, (nd, j))
    fade_start = limit * 0.8
    trimmed = {}
    realized = 0.0
    for i, w in weights.items():
        d = dist.get(i)
        if d is None:
            continue
        if d > fade_start:
            t = 1.0 - (d - fade_start) / (limit - fade_start)
            w *= t * t * (3.0 - 2.0 * t)
        if w > 0.005:
            trimmed[i] = w
            if w > 0.05 and d > realized:
                realized = d
    return trimmed, realized * 1000.0


def _scan(context):
    settings = context.scene.rigo_brace
    obj = settings.scan_object or context.active_object
    if obj is None or obj.type != "MESH":
        return None
    return obj


def _falloff(t, kind):
    if kind == "LINEAR":
        return t
    if kind == "SHARP":
        return t * t
    return t * t * (3.0 - 2.0 * t)  # SMOOTH (smoothstep)


def _inv_falloff(y, kind):
    """Inverse of ``_falloff`` — recovers the normalized distance a weight
    was produced from (used to recover the authored feather from a baked
    region, which stores weights but not the feather)."""
    y = min(1.0, max(0.0, y))
    if kind == "LINEAR":
        return y
    if kind == "SHARP":
        return math.sqrt(y)
    return 0.5 - math.sin(math.asin(1.0 - 2.0 * y) / 3.0)  # smoothstep


def _point_segment_distance(p, a, b):
    ab = b - a
    denom = ab.length_squared
    if denom < 1e-18:
        return (p - a).length
    t = (p - a).dot(ab) / denom
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return (p - (a + ab * t)).length


# Rim mollification (#49e).  One Laplacian pass with λ=0.5 along the rim
# polyline annihilates the one-vertex zigzag (wavelength 2 → factor 0) and
# multiplies a 6-vertex wavelength by 0.75; six passes leave everything
# below ~6 rim edges at ≤18 % while the authored outline itself (mode 1 of a
# ~100-vertex loop) keeps 0.996 of its radius.  The scale is the rim's OWN
# sampling — nothing here is tuned to a fixture.
_RIM_SMOOTH_PASSES = 6
# The nearest point of the mollified rim to a band vertex lies within a rim
# edge or two of that vertex's walk ROOT (the root IS its nearest rim
# vertex); three steps is margin.  Gating by the root — which came from a
# walk ON the surface — is what stops the Euclidean measurement below from
# ever short-cutting through space to a far-side rim.
_RIM_GATE_STEPS = 3
# An unedited region baked by this formulation reconstructs to ~1e-9; a
# legacy Dijkstra-baked one deviates by 0.138 at p95 (measured, A-model
# waist 20/15).  0.01 sits two orders below the legacy signature and two
# above numerical noise.
_RIM_FIELD_TOLERANCE = 0.01
# A placed style's field is reconstructed through a resampled grid (2 mm cells)
# or an IDW sample cloud, so it cannot agree with the stored weights as tightly
# as a painted region's closed form does; measured on the A-model waist at
# 20/15, mean |Δ| 0.006, p95 0.018, max 0.036.  0.05 accepts that while still
# rejecting a wrong frame by an order of magnitude (#49k).
_STYLE_FIELD_TOLERANCE = 0.05


def _boundary_distance(coords, adjacency, rim):
    """Distance in metres from the authored region boundary — a falloff that
    is smooth *by construction* (#49e).

    The previous field was an edge-walk Dijkstra distance from the rim
    VERTICES.  Two properties of that construction put ridges in the wall
    that no amount of extra mesh density could remove:

    * **Metrication.** A path forced onto mesh edges is longer than the path
      on the surface, and the excess depends on how the local edges happen to
      point.  Measured on the A-model waist patch: the graph distance
      overestimates true distance by 8.5 % on average and 36.7 % at p95, and
      varies that much *around* the rim.  At the steepest point of a
      smoothstep that is millimetres of radial wall undulation.
    * **Creases.** Distance from a set of POINTS is only C0: its gradient
      jumps along the bisector between neighbouring seeds — one crease per
      reflex corner of the jagged painted rim, radiating inward.  A denser
      mesh reproduces those creases *more* faithfully; it cannot remove them.
      This is why #49b/#49c density work did not close the artifact.

    The field here is instead:

    1. the rim polyline mollified along itself (``_RIM_SMOOTH_PASSES``) — the
       jaggedness is the paint tool quantizing a smooth stroke onto
       triangles, not authored intent;
    2. a multi-source walk from the rim recording each vertex's ROOT rim
       vertex — the intrinsic, surface-following part;
    3. exact point-to-SEGMENT distance, restricted to rim segments within
       ``_RIM_GATE_STEPS`` of that root.  Euclidean measurement is admissible
       *only* because of that gate: across the ≲12 mm neighbourhood it can
       reach, the chord/arc gap on a torso of radius R ≈ 120 mm is
       d³/24R² ≈ 0.005 mm, and no far-side surface is reachable at all
       because the root came from a walk on the mesh (the same
       geodesic-gating discipline as ``_geodesic_trim``);
    4. the level set re-zeroed onto the rim by the LARGEST rim residual, so
       every rim vertex lands at exactly 0 with no per-vertex pinning — the
       region edge stays on the untouched scan and the field stays smooth
       across it (``max(0, ·)`` costs no continuity: every supported falloff
       has zero slope at t = 0).

    ``coords`` maps vertex index → position; ``adjacency`` maps every region
    vertex → its region neighbours; ``rim`` is the boundary vertex set.
    Returns ``(distance_by_index, evaluate)``, where ``evaluate(co)`` gives
    the same field at an arbitrary nearby position — commit-time refinement
    samples it for vertices that did not exist when the region was baked.
    """
    rim_neighbours = {i: [] for i in rim}
    for i in rim:
        for j in adjacency.get(i, ()):
            if j in rim:
                rim_neighbours[i].append(j)

    position = {i: coords[i].copy() for i in rim}
    for _pass in range(_RIM_SMOOTH_PASSES):
        moved = {}
        for i, neighbours in rim_neighbours.items():
            if len(neighbours) < 2:  # spur or isolated rim vertex: leave it
                moved[i] = position[i]
                continue
            mean = Vector()
            for j in neighbours:
                mean += position[j]
            moved[i] = position[i].lerp(mean / len(neighbours), 0.5)
        position = moved

    depth = {i: 0.0 for i in rim}
    root = {i: i for i in rim}
    heap = [(0.0, i) for i in rim]
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > depth.get(i, 1e30):
            continue
        for j in adjacency.get(i, ()):
            nd = d + (coords[i] - coords[j]).length
            if nd < depth.get(j, 1e30):
                depth[j] = nd
                root[j] = root[i]
                heapq.heappush(heap, (nd, j))

    segments = {}
    for r in rim:
        ring = {r}
        frontier = [r]
        for _step in range(_RIM_GATE_STEPS):
            further = []
            for i in frontier:
                for j in rim_neighbours[i]:
                    if j not in ring:
                        ring.add(j)
                        further.append(j)
            frontier = further
        segments[r] = [
            (position[i], position[j])
            for i in ring for j in rim_neighbours[i]
            if j in ring and j > i
        ]

    def measure(co, r):
        segs = segments.get(r)
        if not segs:
            return None
        return min(_point_segment_distance(co, a, b) for a, b in segs)

    raw = {}
    for i in adjacency:
        value = measure(coords[i], root.get(i))
        raw[i] = depth.get(i, 0.0) if value is None else value
    zero = max((raw[i] for i in rim), default=0.0)
    dist = {i: max(0.0, raw[i] - zero) for i in adjacency}

    order = list(adjacency)
    tree = kdtree.KDTree(len(order))
    for slot, i in enumerate(order):
        tree.insert(coords[i], slot)
    tree.balance()

    def evaluate(co):
        _co, slot, _d = tree.find(co)
        if slot is None:
            return 0.0
        i = order[slot]
        value = measure(co, root.get(i))
        return dist.get(i, 0.0) if value is None else max(0.0, value - zero)

    evaluate.raw = raw  # un-re-zeroed distances (the outward band, #54 Task 7)

    def raw_at(co):
        """The band's own measure (no re-zeroing) at an arbitrary position."""
        _co, slot, _d = tree.find(co)
        if slot is None:
            return 0.0
        i = order[slot]
        value = measure(co, root.get(i))
        return raw.get(i, 0.0) if value is None else value

    def nearest(co):
        _co, slot, _d = tree.find(co)
        return None if slot is None else order[slot]

    evaluate.raw_at = raw_at
    evaluate.nearest = nearest
    return dist, evaluate


def _authored_rim_field(me, group_index, region):
    """Reconstruct a painted region's falloff as a closed-form function of
    its own boundary, or ``None`` if this region was not baked that way.
    ``region`` is the CorrectionRegion (or, for the classic kinds only, its
    falloff kind as a string).

    Commit-time refinement otherwise interpolates the authored samples (IDW +
    a harmonic pass anchored at the ORIGINAL vertices).  That interpolant is
    smooth *between* anchors but pinned *at* them, so a coarse scan's anchor
    lattice prints its own ring of kinks into the wall.  Sampling the field
    the region was authored from removes the lattice entirely.

    Self-validating on purpose: the reconstruction is compared against the
    stored weights and rejected unless it agrees to ``_RIM_FIELD_TOLERANCE``.
    Library/style regions (continuous chart field, no zero-weight rim) and
    legacy Dijkstra-baked regions therefore keep their existing interpolation
    path untouched — no schema change, no migration, no silent re-authoring
    of a saved correction.
    """
    weights = {}
    for vertex in me.vertices:
        for g in vertex.groups:
            if g.group == group_index:
                weights[vertex.index] = g.weight
                break
    if len(weights) < 12:
        return None
    contact = _outward_contact(me, region)
    if contact is not None:
        return _outward_rim_field(me, region, weights, contact)
    coords = {i: me.vertices[i].co.copy() for i in weights}
    adjacency = {i: [] for i in weights}
    # The rim is the PAINTED boundary — region vertices with a neighbour
    # outside the region — not "every vertex that ended up at weight zero":
    # re-zeroing the level set leaves a band of interior vertices at zero
    # too, and seeding from those would reconstruct a different field.
    rim = set()
    for edge in me.edges:
        a, b = edge.vertices
        a_in, b_in = a in adjacency, b in adjacency
        if a_in and b_in:
            adjacency[a].append(b)
            adjacency[b].append(a)
        elif a_in:
            rim.add(a)
        elif b_in:
            rim.add(b)
    if len(rim) < 3 or len(weights) - len(rim) < 8:
        return None
    dist, evaluate = _boundary_distance(coords, adjacency, rim)
    # ``region`` may also be a bare falloff kind (older probes): the classic
    # estimation path needs nothing else.
    falloff_kind = region if isinstance(region, str) else region.falloff_type

    amount_m = None if isinstance(region, str) else abs(region.magnitude_mm) * 0.001
    if falloff_kind == "ROUNDED":
        # #54 Task 2: the profile is a closed form of the STORED feather and
        # the region's own corner radii — no estimation needed, still
        # validated against the weights below.
        if region.feather_mm <= 0.0:
            return None
        f_eff = min(region.feather_mm * 0.001, max(dist.values()))
        if f_eff <= 1e-9:
            return None
        _theta, r_top, r_bottom, evaluate_w = _rounded_profile(
            region.magnitude_mm, f_eff * 1000.0,
            region.top_radius_mm, region.bottom_radius_mm,
        )
        x_bottom = evaluate_w.x_bottom * 0.001
        x_top = evaluate_w.x_top * 0.001

        def profile(d):
            return float(evaluate_w(np.array([min(d, f_eff) * 1000.0]))[0])

        def corner_radius(d):
            # #54 Task 3: the target's curvature radius (m) at distance d —
            # None on the straight wall and the flat pad, 0 on a kink.
            if d <= x_bottom:
                return r_bottom * 0.001
            if d >= x_top and d < f_eff + 1e-9:
                return r_top * 0.001
            return None

        min_corner = min(r_top, r_bottom) * 0.001
    else:
        band = [
            i for i, w in weights.items()
            if 0.05 < w < 0.95 and dist[i] > 1e-9
        ]
        if len(band) < 8:
            return None
        ratios = sorted(
            dist[i] / max(_inv_falloff(weights[i], falloff_kind), 1e-6)
            for i in band
        )
        f_eff = ratios[len(ratios) // 2]
        if f_eff <= 1e-9:
            return None

        def profile(d):
            return _falloff(min(d, f_eff) / f_eff, falloff_kind)

        if amount_m is None or amount_m <= 1e-9:
            corner_radius = None
            min_corner = None
        elif falloff_kind == "SMOOTH":
            # z = A·w(d/f): tightest curvature at the two ends, r = f² / 6A —
            # reported (readout + commit note), NOT refined: the classic
            # kinds keep their measured baseline exactly (golden painted
            # route), and the drawn-corner path is ROUNDED, where the
            # orthotist authored the radii.
            corner_radius = None
            min_corner = f_eff * f_eff / (6.0 * amount_m)
        else:
            corner_radius = None  # LINEAR / SHARP: kinks, nothing to sample
            min_corner = 0.0

    deviation = sorted(
        abs(profile(dist[i]) - w) for i, w in weights.items()
    )
    if deviation[int(len(deviation) * 0.95)] > _RIM_FIELD_TOLERANCE:
        return None

    def field(co):
        return profile(evaluate(co))

    field.distance = evaluate
    field.corner_radius = corner_radius
    field.min_corner_radius = min_corner
    return field


def _outward_rim_field(me, region, weights, contact):
    """Closed form of an OUTWARD region (#54 Task 7): 1 on the painted set,
    profile(feather - d_out) on the band, in the same (x = distance from
    the outline toward the pad) coordinate the inward field uses, so the
    corner rule, the drawable-corner note and refinement sampling work
    unchanged.  Self-validated against the stored weights like the inward
    field; ``None`` hands refinement back to interpolation."""
    f = region.feather_mm * 0.001
    if f <= 1e-9:
        return None
    coords = {i: me.vertices[i].co.copy() for i in weights}
    adjacency = {i: [] for i in weights}
    rim = set()
    rim_outside = {}  # rim vertex -> its non-pad neighbours (member or not)
    for edge in me.edges:
        a, b = edge.vertices
        a_in, b_in = a in adjacency, b in adjacency
        if a_in and b_in:
            adjacency[a].append(b)
            adjacency[b].append(a)
        if a_in and contact[a] and not contact[b]:
            rim.add(a)
            rim_outside.setdefault(a, []).append(b)
        if b_in and contact[b] and not contact[a]:
            rim.add(b)
            rim_outside.setdefault(b, []).append(a)
    if len(rim) < 3:
        return None
    _dist, evaluate = _boundary_distance(coords, adjacency, rim)
    raw = evaluate.raw
    # Side of the outline for a refinement-born vertex: nearer to a band
    # member than to a pad member = band (ties -> band).  Codex round C
    # (Q6) objected to the jump at the pad/band bisector; the alternative —
    # the sign against the nearest rim vertex's outward direction, which
    # is continuous on the rim — MEASURED worse on a jagged painted rim
    # (cornertest 4/3 shoulder max 152.5 deg vs 38.6, and the lifecycle
    # commit shipped two hinges), so the nearest-member rule stays and the
    # bisector jump (0.03 in weight for Smooth f10) is accepted.
    pad_tree = kdtree.KDTree(len(weights))
    band_tree = kdtree.KDTree(len(weights))
    n_pad = n_band = 0
    for i in weights:
        if contact[i]:
            pad_tree.insert(coords[i], i)
            n_pad += 1
        else:
            band_tree.insert(coords[i], i)
            n_band += 1
    pad_tree.balance()
    band_tree.balance()
    kind = region.falloff_type
    amount_m = abs(region.magnitude_mm) * 0.001
    if kind == "ROUNDED":
        _theta, r_top, r_bottom, evaluate_w = _rounded_profile(
            region.magnitude_mm, region.feather_mm,
            region.top_radius_mm, region.bottom_radius_mm,
        )
        x_bottom = evaluate_w.x_bottom * 0.001
        x_top = evaluate_w.x_top * 0.001

        def profile(x):
            return float(evaluate_w(np.array([min(x, f) * 1000.0]))[0])

        def corner_radius(x):
            if x <= x_bottom:
                return r_bottom * 0.001
            if x >= x_top and x < f - 1e-9:
                return r_top * 0.001
            return None

        min_corner = min(r_top, r_bottom) * 0.001
    else:
        def profile(x):
            return _falloff(min(max(x / f, 0.0), 1.0), kind)

        corner_radius = None
        if amount_m <= 1e-9:
            min_corner = None
        elif kind == "SMOOTH":
            min_corner = f * f / (6.0 * amount_m)
        else:
            min_corner = 0.0

    def x_of_member(i):
        if contact[i]:
            return f
        stored = float(np.float32(max(raw.get(i, 0.0) * 1000.0, 1e-6)))
        return max(0.0, f - stored * 0.001)

    deviation = sorted(
        abs(profile(x_of_member(i)) - w) for i, w in weights.items()
    )
    if deviation[int(len(deviation) * 0.95)] > _RIM_FIELD_TOLERANCE:
        return None

    def distance(co):
        # x from the outline toward the pad: the pad is the plateau (f),
        # a band position is f - d_out.
        if n_pad == 0:
            return 0.0
        _c, _i, d_pad = pad_tree.find(co)
        if n_band:
            _c, _j, d_band = band_tree.find(co)
            if d_band <= d_pad + 1e-9:
                return max(0.0, f - evaluate.raw_at(co))
        return f

    def field(co):
        return profile(distance(co))

    field.distance = distance
    field.corner_radius = corner_radius
    field.min_corner_radius = min_corner
    return field


def _applied_field_record(entry, normal_world, origin_world):
    """The authoring representation a placed style must carry with it (#49k).

    A schema-v2 reusable style OWNS a continuous displacement field — its
    resampled grid.  That field, not the coarse per-vertex weights it happens
    to produce on this body, is the authority.  Recording it on the region at
    placement time means commit can EVALUATE it for refinement-born vertices
    instead of re-interpolating the samples it already wrote — and it survives
    into the .blend, so a reopened file keeps the same authority without
    consulting the library (which the orthotist may since have renamed or
    deleted).

    Scoped to schema-v2 GRID entries on purpose.  A v1 style's authoring
    representation is itself a cloud of per-vertex samples taken at the
    authoring scan's coarseness — IDW over it is the same pinned interpolant
    the commit already uses, so there is no authoritative continuous field to
    sample.  Measured on the A-model waist at 20/15: routing v1 through this
    path moved the wall from p95 26.14 / max 75.79 to 27.00 / 71.78, i.e. no
    better and marginally worse.  v1 therefore keeps the existing path and is
    tracked as its own route defect rather than given a fake field.
    """
    grid = entry.get("field")
    if not grid:
        return None
    return {
        "kind": "grid",
        "grid": grid,
        "origin_world": [origin_world.x, origin_world.y, origin_world.z],
        "normal_world": [normal_world.x, normal_world.y, normal_world.z],
        "normal_tolerance_mm": max(
            5.0, float(entry.get("normal_tolerance_mm", 15.0))
        ),
    }


def _style_applied_field(scan, mask, me, group_index):
    """Rebuild a placed style's continuous field, or ``None``.

    Self-validating exactly as ``_authored_rim_field`` is: the reconstruction
    is compared against the weights actually stored on the region and rejected
    unless it agrees to ``_STYLE_FIELD_TOLERANCE``.  A region placed before
    this existed, or one whose frame no longer reproduces its own weights,
    therefore keeps the interpolation path untouched — no migration, no silent
    re-authoring of a saved correction.
    """
    snapshot = _load_snapshot(scan, mask)
    if not snapshot:
        return None
    record = snapshot.get("applied_field")
    if not record:
        return None
    try:
        origin = Vector(record["origin_world"])
        normal = Vector(record["normal_world"])
    except (KeyError, TypeError, ValueError):
        return None
    if normal.length < 1e-9:
        return None
    side, up, outward = _surface_frame(normal.normalized())
    tolerance = float(record.get("normal_tolerance_mm", 15.0))
    matrix = scan.matrix_world
    grid = record.get("grid")
    if not grid:
        return None

    def field(co_local):
        relative = matrix @ co_local - origin
        offset = abs(relative.dot(outward)) * 1000.0
        if offset >= tolerance * 2.0:
            return 0.0
        u = relative.dot(side) * 1000.0
        v = relative.dot(up) * 1000.0
        weight = _field_weight(grid, u, v)
        if offset > tolerance:
            t = 1.0 - (offset - tolerance) / tolerance
            weight *= t * t * (3.0 - 2.0 * t)
        return min(1.0, max(0.0, weight))

    weights = {}
    for vertex in me.vertices:
        for group in vertex.groups:
            if group.group == group_index:
                weights[vertex.index] = group.weight
                break
    if len(weights) < 12:
        return None
    deviation = sorted(
        abs(field(me.vertices[i].co) - w) for i, w in weights.items()
    )
    if deviation[int(len(deviation) * 0.95)] > _STYLE_FIELD_TOLERANCE:
        return None
    return field


def _region_weights_from_selection(obj, feather_mm, falloff_kind,
                                   profile=(0.0, 0.0, 0.0), outside=False):
    """Read the Edit-Mode selection and compute per-vertex falloff weights.

    Weight rises from 0 at the painted boundary to 1 at ``feather_mm`` deep
    (topological rings converted via the mean selected edge length), so the
    core of the region gets the full mm amount and the edge blends to zero.
    Returns (weights {vert_index: w}, centroid, mean_normal, radius_mm,
    depth_mm {vert_index: inward distance in mm} or None for a closed
    selection, band_mm).  ``depth_mm`` is the region's continuous
    definition (#54); the weights are evaluated from it by
    ``_weights_from_distance``.  With ``outside`` (#54 Task 7) the painted
    set is the full-depth pad (w = 1) and ``band_mm`` {index: outward
    distance} holds the stored band candidates; otherwise ``band_mm`` is
    None and the feather runs inward as before.
    """
    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    bm.verts.ensure_lookup_table()

    sel = [v for v in bm.verts if v.select]
    if not sel:
        return None, None, None, 0.0, None, None

    centroid = Vector()
    for v in sel:
        centroid += v.co
    centroid /= len(sel)
    radius_mm = max((v.co - centroid).length for v in sel) * 1000.0

    normal = Vector()
    n_faces = 0
    for f in bm.faces:
        if f.select:
            normal += f.normal
            n_faces += 1
    if n_faces == 0:  # vertex-only selection: fall back to vertex normals
        for v in sel:
            normal += v.normal
    if normal.length < 1e-9:
        return None, None, None, 0.0, None, None
    normal.normalize()

    # Surface distance in METRES from the painted boundary inward.  Integer
    # topological rings quantized the feather into visible terraces on
    # irregular scan triangles (#48 RC4); a plain edge-walk Dijkstra fixed
    # the quantization but is itself anisotropic and creased (#49e) —
    # ``_boundary_distance`` measures to the mollified rim CURVE, which is
    # what the orthotist actually painted.
    sel_set = {v.index for v in sel}
    boundary = [
        v for v in sel
        if any(e.other_vert(v).index not in sel_set for e in v.link_edges)
    ]
    if not boundary:  # closed selection (whole mesh) — no boundary anywhere
        weights = {v.index: 1.0 for v in sel}
        return weights, centroid.copy(), normal, radius_mm, None, None

    if outside:
        inward, outward, _evaluate = _outward_distance(
            sel_set,
            lambda i: [e.other_vert(bm.verts[i]).index
                       for e in bm.verts[i].link_edges],
            lambda i: bm.verts[i].co,
            _BAND_CAP_MM * 0.001,
        )
        depth_mm = {i: d * 1000.0 for i, d in inward.items()}
        band_mm = _stored_band_mm(outward)
        weights = {i: 1.0 for i in sel_set}
        weights.update(_band_members(band_mm, feather_mm, falloff_kind, profile))
        return weights, centroid.copy(), normal, radius_mm, depth_mm, band_mm

    coords = {i: bm.verts[i].co.copy() for i in sel_set}
    adjacency = {i: [] for i in sel_set}
    for v in sel:
        for e in v.link_edges:
            o = e.other_vert(v)
            if o.index in sel_set:
                adjacency[v.index].append(o.index)
    depth, _evaluate = _boundary_distance(
        coords, adjacency, {v.index for v in boundary}
    )
    max_depth = max(depth.values())
    order = sorted(sel_set)
    depth_mm = {idx: depth.get(idx, max_depth) * 1000.0 for idx in order}
    values = _weights_from_distance(
        [depth_mm[idx] for idx in order], feather_mm, falloff_kind, profile
    )
    weights = dict(zip(order, values.tolist()))
    return weights, centroid.copy(), normal, radius_mm, depth_mm, None


class RIGO_OT_region_add(Operator):
    """Turn the painted selection into a measurable correction region"""

    bl_idname = "rigo.region_add"
    bl_label = "Add Region From Selection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def execute(self, context):
        obj = _scan(context)
        if obj is None:
            self.report({"ERROR"}, "Import and prepare a scan first")
            return {"CANCELLED"}
        settings = context.scene.rigo_brace

        weights, centroid, normal, radius_mm, depth_mm, band_mm = (
            _region_weights_from_selection(
                obj, settings.region_feather, settings.region_falloff,
                (settings.region_magnitude, settings.region_top_radius,
                 settings.region_bottom_radius),
                outside=True,  # #54 Task 7: paint = the pad, feather outside
            )
        )
        if not weights:
            self.report({"ERROR"}, "Paint a region on the scan first")
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode="OBJECT")

        seq = int(obj.get("rigo_region_seq", 0)) + 1
        obj["rigo_region_seq"] = seq
        mask = f"RIGO_REGION_{seq:03d}"
        vg = obj.vertex_groups.new(name=mask)
        for idx, weight in weights.items():
            # Keep zero-falloff boundary vertices as near-zero group members so
            # Edit Selection can reconstruct the original painted face border.
            vg.add([idx], max(weight, _MASK_EDGE_WEIGHT), "REPLACE")
        if depth_mm is not None:
            _store_distance(obj.data, mask, depth_mm, band_mm)
            if band_mm is not None:
                _store_contact(obj.data, mask, depth_mm.keys())
        # Snapshot against the EVALUATED surface (what the user painted on),
        # like the circle path — the last raw-vs-evaluated mixed-state path
        # (#48 Wave 2); falls back to raw coords when a modifier changes the
        # vertex count.
        coords_e, normals_e = _evaluated_positions(obj)
        _store_snapshot(
            obj, mask, _style_snapshot(
                obj, weights, coords_e, normals_e,
                pad=set(depth_mm) if band_mm is not None else None,
            )
        )

        region = obj.rigo_regions.add()
        region.name = f"Region {seq}"
        region.kind = settings.region_kind
        region.center = centroid
        region.direction = normal
        region.magnitude_mm = settings.region_magnitude
        region.radius_mm = radius_mm
        region.feather_mm = settings.region_feather
        region.depth_mm = max(depth_mm.values()) if depth_mm else 0.0
        region.edge_mm = (_mean_touching_edge(obj.data, set(weights)) or 0.0) * 1000.0
        region.falloff_type = settings.region_falloff
        region.top_radius_mm = settings.region_top_radius
        region.bottom_radius_mm = settings.region_bottom_radius
        region.feather_outside = band_mm is not None
        region.surface_mask = mask
        obj.rigo_region_index = len(obj.rigo_regions) - 1
        _sync_preview(obj, region)
        sync_outline(obj)

        self.report(
            {"INFO"},
            f"{region.name}: {len(weights)} verts, radius {radius_mm:.0f} mm — "
            "live surface preview created",
        )
        return {"FINISHED"}


class RIGO_OT_region_add_circle(Operator):
    """Drop a circular region at the 3D cursor (Shift+Right-Click to place it)"""

    bl_idname = "rigo.region_add_circle"
    bl_label = "Add Circle At Cursor"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _scan(context) is not None

    def execute(self, context):
        obj = _scan(context)
        if obj is None:
            self.report({"ERROR"}, "Import and prepare a scan first")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        settings = context.scene.rigo_brace
        me = obj.data
        if not me.vertices:
            self.report({"ERROR"}, "The scan has no geometry")
            return {"CANCELLED"}

        # Work on the EVALUATED vertex positions (the surface the user sees
        # and places the cursor on); indices stay valid on the raw mesh as
        # long as no modifier changes the vertex count.
        coords, eval_normals = _evaluated_positions(obj)
        if coords is None:
            coords = [v.co.copy() for v in me.vertices]
            eval_normals = [v.normal.copy() for v in me.vertices]

        # Seed = the mesh vertex nearest the 3D cursor (in object space).
        cursor_local = obj.matrix_world.inverted() @ context.scene.cursor.location
        tree = kdtree.KDTree(len(coords))
        for index, co in enumerate(coords):
            tree.insert(co, index)
        tree.balance()
        _co, seed, seed_dist = tree.find(cursor_local)
        radius = settings.region_radius * 0.001
        if seed_dist > radius:
            self.report({"ERROR"}, "Place the 3D cursor ON the scan surface first")
            return {"CANCELLED"}

        # Geodesic (edge-walk Dijkstra) distances from the seed, capped at the
        # radius — surface distance, so the region can NOT bleed through to the
        # far side of the body the way a plain sphere would.
        neighbors = [[] for _ in range(len(coords))]
        for e in me.edges:
            a, b = e.vertices
            length = (coords[a] - coords[b]).length
            neighbors[a].append((b, length))
            neighbors[b].append((a, length))
        dist = {seed: 0.0}
        heap = [(0.0, seed)]
        while heap:
            d, i = heapq.heappop(heap)
            if d > dist.get(i, 1e30):
                continue
            for j, length in neighbors[i]:
                nd = d + length
                if nd <= radius and nd < dist.get(j, 1e30):
                    dist[j] = nd
                    heapq.heappush(heap, (nd, j))

        falloff = settings.region_falloff
        # Continuous definition (#54): inward distance from the circle's rim;
        # feather = radius reproduces the classic falloff(1 - g / radius).
        depth_mm = {
            i: (radius - d) * 1000.0 for i, d in dist.items() if d < radius
        }
        depth_mm[seed] = radius * 1000.0
        order = sorted(depth_mm)
        values = _weights_from_distance(
            [depth_mm[i] for i in order], settings.region_radius, falloff,
            (settings.region_magnitude, settings.region_top_radius,
             settings.region_bottom_radius),
        )
        weights = dict(zip(order, values.tolist()))
        if len(weights) < 3:
            self.report({"ERROR"}, "Circle too small for this mesh density")
            return {"CANCELLED"}

        normal = Vector()
        for i, w in weights.items():
            normal += eval_normals[i] * w
        if normal.length < 1e-9:
            self.report({"ERROR"}, "Could not read the surface direction")
            return {"CANCELLED"}
        normal.normalize()

        seq = int(obj.get("rigo_region_seq", 0)) + 1
        obj["rigo_region_seq"] = seq
        mask = f"RIGO_REGION_{seq:03d}"
        vg = obj.vertex_groups.new(name=mask)
        for idx, w in weights.items():
            vg.add([idx], max(w, _MASK_EDGE_WEIGHT), "REPLACE")
        _store_distance(obj.data, mask, depth_mm)
        _store_snapshot(
            obj, mask, _style_snapshot(
                obj, weights, coords, eval_normals,
                origin_world=obj.matrix_world @ coords[seed],
            )
        )

        region = obj.rigo_regions.add()
        region.name = f"Circle {seq}"
        region.kind = settings.region_kind
        region.center = coords[seed]
        region.direction = normal
        region.magnitude_mm = settings.region_magnitude
        region.radius_mm = settings.region_radius
        region.feather_mm = settings.region_radius
        region.depth_mm = settings.region_radius
        region.edge_mm = (_mean_touching_edge(obj.data, set(weights)) or 0.0) * 1000.0
        region.falloff_type = falloff
        region.top_radius_mm = settings.region_top_radius
        region.bottom_radius_mm = settings.region_bottom_radius
        region.surface_mask = mask
        obj.rigo_region_index = len(obj.rigo_regions) - 1
        _sync_preview(obj, region)

        self.report(
            {"INFO"},
            f"{region.name}: {len(weights)} verts within {settings.region_radius:.0f} mm — "
            "live surface preview created",
        )
        return {"FINISHED"}


def _active_region(obj):
    if obj is None or not obj.rigo_regions:
        return None
    idx = obj.rigo_region_index
    if 0 <= idx < len(obj.rigo_regions):
        return obj.rigo_regions[idx]
    return None


class RIGO_OT_region_edit(Operator):
    """Restore the active region mask as an editable mesh-face selection"""

    bl_idname = "rigo.region_edit"
    bl_label = "Edit Region Selection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_region(_scan(context)) is not None

    def execute(self, context):
        obj = _scan(context)
        region = _active_region(obj)
        if obj.get(_committed_key(region), False):
            self.report({"ERROR"}, "This region is committed; undo before editing it")
            return {"CANCELLED"}
        vg = obj.vertex_groups.get(region.surface_mask)
        if vg is None:
            self.report({"ERROR"}, f"Mask '{region.surface_mask}' is missing")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        _make_active(context, obj)
        group_index = vg.index
        # #54 Task 7: an outward region edits its PAINTED set; the band is
        # derived and must never be absorbed into the pad by an Update.
        contact = _outward_contact(obj.data, region)
        included = (
            set(np.flatnonzero(contact).tolist()) if contact is not None else set()
        )
        for vertex in obj.data.vertices:
            vertex.select = False
            if contact is None and any(
                g.group == group_index and g.weight > 0.0 for g in vertex.groups
            ):
                included.add(vertex.index)
        for polygon in obj.data.polygons:
            polygon.select = all(index in included for index in polygon.vertices)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        self.report({"INFO"}, "Edit the orange faces, then press Update Preview")
        return {"FINISHED"}


class RIGO_OT_region_update(Operator):
    """Rebuild the active mask from selection and refresh its live preview"""

    bl_idname = "rigo.region_update"
    bl_label = "Update Region Preview"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_region(_scan(context)) is not None

    def execute(self, context):
        obj = _scan(context)
        region = _active_region(obj)
        if obj.get(_committed_key(region), False):
            self.report({"ERROR"}, "This region is committed; undo before editing it")
            return {"CANCELLED"}

        if context.mode == "EDIT_MESH":
            # The region's OWN feather/falloff (#54); a legacy region without
            # one adopts the panel default and records it.
            settings = context.scene.rigo_brace
            feather_mm = region.feather_mm or settings.region_feather
            weights, centroid, normal, radius_mm, depth_mm, band_mm = (
                _region_weights_from_selection(
                    obj, feather_mm, region.falloff_type, _region_profile(region),
                    outside=region.feather_outside,
                )
            )
            if not weights:
                self.report({"ERROR"}, "Select faces for this region first")
                return {"CANCELLED"}
            bpy.ops.object.mode_set(mode="OBJECT")
            old_group = obj.vertex_groups.get(region.surface_mask)
            if old_group is not None:
                obj.vertex_groups.remove(old_group)
            group = obj.vertex_groups.new(name=region.surface_mask)
            for index, weight in weights.items():
                group.add([index], max(weight, _MASK_EDGE_WEIGHT), "REPLACE")
            if depth_mm is not None:
                _store_distance(obj.data, region.surface_mask, depth_mm, band_mm)
            else:
                _drop_distance(obj.data, region.surface_mask)
            if band_mm is not None:
                _store_contact(obj.data, region.surface_mask, depth_mm.keys())
            else:
                _drop_contact(obj.data, region.surface_mask)
            # Snapshot the evaluated surface WITHOUT this region's own live
            # preview — otherwise the update would bake its own displacement
            # into the authored field (the RC3 failure, via the preview).
            own_preview = _preview_modifier(obj, region)
            if own_preview is not None:
                shown = own_preview.show_viewport
                own_preview.show_viewport = False
            coords_e, normals_e = _evaluated_positions(obj)
            _store_snapshot(
                obj, region.surface_mask,
                _style_snapshot(
                    obj, weights, coords_e, normals_e,
                    pad=set(depth_mm) if band_mm is not None else None,
                ),
            )
            if own_preview is not None:
                own_preview.show_viewport = shown
            region.center = centroid
            region.direction = normal
            region.radius_mm = radius_mm
            region.depth_mm = max(depth_mm.values()) if depth_mm else 0.0
            region.edge_mm = (_mean_touching_edge(obj.data, set(weights)) or 0.0) * 1000.0
            if region.feather_mm != feather_mm:
                region.feather_mm = feather_mm  # re-evaluates from the fresh distance

        _sync_preview(obj, region)
        sync_outline(obj)
        self.report({"INFO"}, "Preview updated along the body's local normals")
        return {"FINISHED"}


class RIGO_OT_region_style_save(Operator):
    """Save the committed correction as a reusable style.

    Stores the footprint outline and the continuous displacement-field grid
    in a surface-local frame, the size along the surface (mm), the Amount
    (mm), Feather and Falloff, the Pressure/Expansion kind, the surface
    orientation, and the clinical metadata (landmark, pairing/counterforce
    facts, mirror provenance) — schema v2 — so the style can be re-applied
    on any compatible body surface.
    Saving with an existing name updates that style"""

    bl_idname = "rigo.region_style_save"
    bl_label = "Save as Reusable Style"
    bl_options = {"REGISTER"}

    style_name: StringProperty(name="Style Name", default="My Correction Style")

    @classmethod
    def poll(cls, context):
        scan = _scan(context)
        region = _active_region(scan)
        if region is None:
            cls.poll_message_set("Create or import a correction region first")
            return False
        if not scan.get(_committed_key(region), False):
            cls.poll_message_set(
                "Commit the region before saving it as a reusable style"
            )
            return False
        return True

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        scan = _scan(context)
        region = _active_region(scan)
        if not scan.get(_committed_key(region), False):
            self.report({"ERROR"}, "Commit the region before saving its style")
            return {"CANCELLED"}
        group = scan.vertex_groups.get(region.surface_mask)
        if group is None:
            self.report({"ERROR"}, f"Mask '{region.surface_mask}' is missing")
            return {"CANCELLED"}
        label = self.style_name.strip()
        if not label:
            self.report({"ERROR"}, "Enter a style name")
            return {"CANCELLED"}

        snapshot = _load_snapshot(scan, region.surface_mask)
        if snapshot is None:
            # Legacy region without a bake-time snapshot: sample the current
            # (already displaced) surface — last resort, kept for continuity.
            samples, normal_offsets, weights = _style_samples(scan, group)
            spacing = _sample_spacing_mm(scan, set(weights))
            snapshot = {
                "samples": samples,
                "sample_radius_mm": max(1.0, spacing * 1.75),
                "normal_tolerance_mm": max(
                    15.0, max(normal_offsets) + spacing * 2.0
                ),
                "spacing_mm": spacing,
            }
            self.report(
                {"WARNING"},
                "Older region: style sampled from the committed shape",
            )
        if not snapshot.get("field"):
            spacing = float(
                snapshot.get("spacing_mm", snapshot["sample_radius_mm"] / 1.75)
            )
            snapshot["field"] = _field_from_samples(
                snapshot["samples"], spacing
            )
        # Saving under an existing name UPDATES that style (documented in the
        # tooltip); a new name registers a new library entry.
        existing = next(
            (
                e for e in region_library.load_library()
                if e.get("label") == label
            ),
            None,
        )
        # Clinical metadata (Wave 2 decision 1): one region per style, but
        # the pairing facts travel with it — never silently discarded.
        clinical = {
            "anatomical_label": region.anatomical_label,
            "paired": False,
            "mirrored_from": region.mirrored_from,
            "label_auto_mapped": bool(region.label_auto_mapped),
        }
        if 0 <= region.opposing_region < len(scan.rigo_regions):
            opposing = scan.rigo_regions[region.opposing_region]
            clinical.update({
                "paired": True,
                "role": region.kind,
                "counterpart_kind": opposing.kind,
                "counterpart_label": opposing.name,
                "counterpart_anatomical_label": opposing.anatomical_label,
                "counterpart_magnitude_mm": opposing.magnitude_mm,
                "counterpart_center_offset_mm": [
                    round((opposing.center[k] - region.center[k]) * 1000.0, 1)
                    for k in range(3)
                ],
            })
        entry = {
            "id": existing["id"] if existing
            else region_library.identifier_from_label(label),
            "label": label,
            "kind": region.kind,
            "magnitude_mm": region.magnitude_mm,
            "falloff": region.falloff_type,
            "feather_mm": region.feather_mm,
            "feather_outside": bool(region.feather_outside),
            "top_radius_mm": region.top_radius_mm,
            "bottom_radius_mm": region.bottom_radius_mm,
            "samples": snapshot["samples"],
            "sample_radius_mm": snapshot["sample_radius_mm"],
            "normal_tolerance_mm": snapshot["normal_tolerance_mm"],
            "field": snapshot["field"],
            "max_geodesic_mm": snapshot.get("max_geodesic_mm"),
            "anchor_uv": snapshot.get("anchor_uv", [0.0, 0.0]),
            "clinical": clinical,
            "requires_orthotist_review": True,
            "schema_version": 2,
        }
        region_library.upsert_entry(entry)
        context.scene.rigo_brace.region_style = entry["id"]
        verb = "Updated" if existing else "Saved"
        self.report(
            {"INFO"}, f"{verb} style '{label}' for reuse on other scans"
        )
        return {"FINISHED"}


class RIGO_OT_region_style_import(Operator):
    """Place a saved correction mask at the 3D cursor as an editable preview"""

    bl_idname = "rigo.region_style_import"
    bl_label = "Import Style at Cursor"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if _scan(context) is None:
            cls.poll_message_set("Import and prepare a scan first")
            return False
        settings = context.scene.rigo_brace
        if region_library.get_entry(settings.region_style) is None:
            cls.poll_message_set("Save or select a reusable style first")
            return False
        return True

    def execute(self, context):
        scan = _scan(context)
        if scan is None:
            self.report({"ERROR"}, "Import and prepare a scan first")
            return {"CANCELLED"}
        settings = context.scene.rigo_brace
        entry = region_library.get_entry(settings.region_style)
        if entry is None:
            self.report({"ERROR"}, "Save or select a region style first")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        coords, eval_normals = _evaluated_positions(scan)
        if coords is None:
            self.report(
                {"ERROR"},
                "A modifier changes the scan's vertex count — apply it "
                "before importing a style",
            )
            return {"CANCELLED"}
        target, normal = _target_surface(scan, context.scene.cursor.location)
        if target is None:
            self.report({"ERROR"}, "Place the 3D cursor on the scan surface")
            return {"CANCELLED"}
        weights, realized_mm = _weights_from_style(
            scan, entry, target, normal, coords
        )
        if len(weights) < 3:
            self.report({"ERROR"}, "Saved style does not overlap enough scan vertices")
            return {"CANCELLED"}
        # Size semantics (Wave 2 decision): surface mm are authoritative.
        # Warn — never silently resize — when this body realizes the stored
        # footprint materially larger or smaller along its surface.
        authored_mm = float(entry.get("max_geodesic_mm") or 0.0)
        if authored_mm > 0.0 and realized_mm > 0.0:
            deviation = abs(realized_mm - authored_mm) / authored_mm
            if deviation > 0.12:
                self.report(
                    {"WARNING"},
                    f"On this body the footprint measures {realized_mm:.0f} mm "
                    f"along the surface (authored {authored_mm:.0f} mm, "
                    f"{deviation * 100.0:.0f}% off) — review the size",
                )

        sequence = int(scan.get("rigo_region_seq", 0)) + 1
        scan["rigo_region_seq"] = sequence
        mask = f"RIGO_REGION_{sequence:03d}"
        group = scan.vertex_groups.new(name=mask)
        for index, weight in weights.items():
            group.add([index], max(weight, _MASK_EDGE_WEIGHT), "REPLACE")
        snapshot = _style_snapshot(
            scan, weights, coords, eval_normals, origin_world=target
        )
        # #49k: the region carries the style's own continuous field, so commit
        # can sample the AUTHORING representation for refinement-born vertices
        # instead of re-interpolating the coarse weights just written.
        snapshot["applied_field"] = _applied_field_record(entry, normal, target)
        _store_snapshot(scan, mask, snapshot)

        inverse_normal = scan.matrix_world.to_3x3().inverted() @ normal
        region = scan.rigo_regions.add()
        region.name = entry["label"]
        region.kind = entry["kind"]
        region.center = scan.matrix_world.inverted() @ target
        region.direction = inverse_normal.normalized()
        region.magnitude_mm = float(entry["magnitude_mm"])
        # Surface mm are the style's size (Wave 2); the chart's chord extent
        # is only the fallback for legacy entries.
        region.radius_mm = authored_mm or max(
            (Vector((sample[0], sample[1])).length for sample in entry["samples"]),
            default=0.0,
        )
        region.falloff_type = entry.get("falloff", "SMOOTH")
        region.feather_mm = float(entry.get("feather_mm", 0.0) or 0.0)
        region.top_radius_mm = float(entry.get("top_radius_mm", 4.0))
        region.bottom_radius_mm = float(entry.get("bottom_radius_mm", 3.0))
        if entry.get("feather_outside"):
            # #54 Task 7: the style's field carries the pad at 1.0; the band
            # is re-derived here from that pad and the region's own feather,
            # so an imported region never falls back to inward semantics.
            _adopt_outward(scan, group, mask, region,
                           [i for i, w in weights.items() if w >= 0.999])
        clinical = entry.get("clinical") or {}
        if clinical.get("anatomical_label"):
            try:
                region.anatomical_label = clinical["anatomical_label"]
            except TypeError:
                pass
        region.surface_mask = mask
        scan.rigo_region_index = len(scan.rigo_regions) - 1
        _sync_preview(scan, region)
        sync_outline(scan)
        pair_note = (
            " — authored as part of a corrective pair; the counterpart was "
            "not imported" if clinical.get("paired") else ""
        )
        self.report(
            {"INFO"},
            f"Imported '{entry['label']}' as a live region; orthotist "
            f"review required{pair_note}",
        )
        return {"FINISHED"}


class RIGO_OT_region_style_delete(Operator):
    """Delete the selected reusable correction style"""

    bl_idname = "rigo.region_style_delete"
    bl_label = "Delete Saved Style"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        settings = context.scene.rigo_brace
        if region_library.get_entry(settings.region_style) is None:
            cls.poll_message_set("Save or select a reusable style first")
            return False
        return True

    def execute(self, context):
        identifier = context.scene.rigo_brace.region_style
        if not region_library.delete_entry(identifier):
            self.report({"ERROR"}, "No saved style selected")
            return {"CANCELLED"}
        self.report({"INFO"}, "Saved style deleted")
        return {"FINISHED"}


class RIGO_OT_region_apply(Operator):
    """Commit the active non-destructive region preview to the mesh"""

    bl_idname = "rigo.region_apply"
    bl_label = "Apply Region"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_region(_scan(context)) is not None

    def execute(self, context):
        obj = _scan(context)
        region = _active_region(obj)
        if region is None:
            self.report({"ERROR"}, "Add a region first")
            return {"CANCELLED"}
        if not region.enabled:
            self.report({"WARNING"}, f"{region.name} is disabled")
            return {"CANCELLED"}
        if obj.vertex_groups.get(region.surface_mask) is None:
            self.report({"ERROR"}, f"Mask '{region.surface_mask}' is missing")
            return {"CANCELLED"}
        if obj.get(_committed_key(region), False):
            self.report({"WARNING"}, f"{region.name} is already committed")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        _make_active(context, obj)
        modifier = _sync_preview(obj, region)
        if modifier is None:
            self.report({"ERROR"}, "Could not create the region preview")
            return {"CANCELLED"}
        # #49 audit guards: bmesh write-back would mangle shape keys, and a
        # live deform segment would bake stale gains onto new vertices.
        if obj.data.shape_keys is not None:
            self.report(
                {"ERROR"},
                "The scan has shape keys — apply or remove them before "
                "committing a correction",
            )
            return {"CANCELLED"}
        if obj.modifiers.get(DEFORM_MODIFIER):
            self.report(
                {"ERROR"},
                "Finish or reset the Bend/Twist/Stretch deform before "
                "committing a correction",
            )
            return {"CANCELLED"}
        group = obj.vertex_groups.get(region.surface_mask)
        sign = -1.0 if region.kind == "PRESSURE" else 1.0
        offset = sign * region.magnitude_mm * 0.001

        # ------------------------------------------------------------------ #
        # #49 transaction: ALL work happens on a working COPY of the mesh —
        # refinement, displacement, repair and validation.  The real patient
        # mesh is written once, atomically, only when everything is valid;
        # any failure discards the copy and touches nothing.
        # ------------------------------------------------------------------ #
        me = obj.data
        # Seamless attempt ladder: refined first; while the repair leaves
        # ONLY refinement-born seam slivers, retry with those vertices
        # dissolved (welded away pre-displacement) and the whole pipeline
        # re-run from a fresh copy — plans ACCUMULATE across up to three
        # retries, because larger amounts collapse several wrinkle seams
        # and the clusters surface one retry at a time (#49d: measured 1
        # cluster at 10 mm, 2 at 15 mm, 3 at 20 mm on the A-model waist —
        # a single retry meant every amount above 10 mm fell back to the
        # staircase).  Anything else — or an exhausted ladder — falls back
        # to a FULLY unrefined commit (exactly the pre-#49 behaviour, with
        # a visible warning), refusing only if that also fails.  No partial
        # refinement, no density seams, deterministic.
        failure = None
        fell_back = False
        plans = []
        retry = False
        prev_defects = None
        no_gain = 0
        # Ladder depth scales with the AMOUNT (#49d, the orthotist's own
        # principle): a gentle press (≤10 mm) has a mild wall where the
        # warned fallback is visually fine — no dissolve retries, the
        # classic refined-or-fallback keeps commits fast; a deep press is
        # where the staircase genuinely hurts and the orthotist accepted
        # compute for quality — full ladder.
        max_plans = 0 if region.magnitude_mm <= 10.0 else 4
        # The static-body BVH (#49c perf): faces holding no footprint vertex
        # are never split and never move, and original vertex indices are
        # preserved in every working copy — build the opposite-wall net ONCE
        # from the real mesh instead of once per attempt (measured: ~1 s per
        # rebuild on the 44.5k scan, ×3 on the fallback path).
        member0 = set()
        for vertex in me.vertices:
            for g in vertex.groups:
                if g.group == group.index and g.weight > 0.0:
                    member0.add(vertex.index)
                    break
        static_tree, static_faces = _static_faces_bvh(me, member0)
        nonman_me = _nonmanifold_count(me)
        # The refined state is bit-deterministic — compute it ONCE and let
        # every dissolve retry copy it (#49d perf: re-running the
        # refinement per retry measured 13 s commits).
        # #49e: for a painted region the authored falloff is a closed-form
        # function of its own boundary — hand it to the refinement so new
        # vertices SAMPLE it rather than interpolate the coarse authored
        # anchors.  Returns None (and changes nothing) for library/style and
        # legacy regions, which is verified by reconstruction, not assumed.
        rim_field = _authored_rim_field(me, group.index, region)
        contact_pad = _outward_contact(me, region)
        pad_fold_count = 0
        if rim_field is None:
            # #49k: a PLACED STYLE owns a continuous field too — the grid (v2)
            # or sample cloud (v1) it was authored from, recorded on the region
            # at placement.  Measured on the orthotist's own route (A-model
            # waist, 20 mm / 15 mm): re-interpolating the coarse weights gave
            # wall p95 27.2°, max 76.1°, 21 edges over 30°; sampling the stored
            # field gives 21.5°, 38.9°, 6 — and refinement stops being worse
            # than not refining at all.  Also self-validating, so a region
            # without a recorded field keeps the interpolation path exactly.
            rim_field = _style_applied_field(
                obj, region.surface_mask, me, group.index
            )
        n_original = len(me.vertices)
        refined_me = me.copy()
        added0, refine_mm0 = _refine_footprint(refined_me, group.index,
                                               offset, field=rim_field)
        try:
          while True:
            if fell_back:
                temp = me.copy()
            else:
                temp = refined_me.copy()
            retry = False
            try:
                if not fell_back:
                    refine_mm = refine_mm0
                    if plans:
                        _apply_dissolve(temp, plans, len(me.vertices))
                    added = len(temp.vertices) - len(me.vertices)
                    if added and _nonmanifold_count(temp) != nonman_me:
                        # A weld artifact the link condition let through —
                        # topology damage never ships, and more welding
                        # cannot heal it: the unrefined fallback decides
                        # (#49d guard; skips the wasted displacement too).
                        fell_back = True
                        retry = True
                        continue
                else:
                    added, refine_mm = 0, 0.0
                weights = {}
                for vertex in temp.vertices:
                    for g in vertex.groups:
                        if g.group == group.index:
                            weights[vertex.index] = g.weight
                            break
                member = {i for i, w in weights.items() if w > 0.0}
                affected = _faces_by_membership(temp, member)[0]
                pre_face_normals = {
                    p.index: p.normal.copy() for p in affected
                }
                zone = set(member)
                for p in affected:
                    zone.update(p.vertices)
                pre_vertex_normals = {
                    i: temp.vertices[i].normal.copy() for i in zone
                }
                mean_edge = _mean_touching_edge(temp, member)
                if mean_edge is None:
                    mean_edge = 0.003

                # Pre-existing defects on a dirty scan are not ours to fix
                # or to block on — baseline them out of the repair verdict.
                baseline = _footprint_self_intersections(
                    temp, member, affected
                )
                baseline |= {p.index for p in affected if p.area < 1e-12}

                # Commit analytically along FAIRED normals: |displacement|
                # is exactly amount × weight (unit directions), matching
                # the preview magnitude, while the coherent direction field
                # keeps scan creases from shredding (#48).
                faired, adjacency = _faired_normals(temp, weights, mean_edge)

                # Wave 1 (P0): predict wall contact before displacing, and
                # baseline the cross-sheet state for the post net.
                blocked = _wall_blocked_points(
                    temp, weights, faired, offset, static_tree
                )
                if blocked:
                    failure = (
                        f"{region.name}: {region.magnitude_mm:.1f} mm would "
                        f"press through or within "
                        f"{_WALL_CLEARANCE_MM:.0f} mm of the opposite body "
                        f"surface ({blocked} points). Reduce the amount — "
                        "nothing was changed"
                    )
                    break
                fold_pairs = _edge_face_pairs(affected)
                pre_cross = _cross_sheet_pairs(
                    temp, static_tree, static_faces, affected
                )

                for i in faired:
                    temp.vertices[i].co += faired[i] * (offset * weights[i])
                temp.update()
                if contact_pad is not None:
                    # ERR-0043: the full-depth pad folds in the scan's own
                    # needle faces before any repair — measured 2–9 faces on
                    # EVERY fixture, subdivided ones included, all repaired.
                    # Codex round C asked for a transactional refusal; that
                    # would have blocked the orthotist's normal route, so it
                    # is a commit NOTE (the repair's tangential slide on
                    # original pad vertices is what it discloses).
                    pad_fold_count = max(pad_fold_count, len(_pad_fold_faces(
                        temp, fold_pairs, pre_face_normals, contact_pad
                    )))
                remaining = _repair_folds(
                    temp, weights, pre_face_normals, pre_vertex_normals,
                    adjacency, baseline, affected, fold_pairs,
                    new_start=len(me.vertices) if added else None,
                    sliver_h=0.12 * refine_mm * 0.001,
                )
                if remaining:
                    # No-gain cutoff (#49d): one steady defect count is
                    # still progress (a cluster dissolved, one migration
                    # surfaced — measured converging on the next retry),
                    # but TWO consecutive retries without improvement is
                    # whack-a-mole on a geometrically infeasible wall —
                    # stop burning pipeline runs (measured 25 s hopeless
                    # ladders on the 20/10 extreme) and let the honest
                    # fallback decide.  The plan budget covers many-seam
                    # walls (measured: 7 clusters at 20/15 on the A-model
                    # waist — the old 3-plan budget could never finish).
                    if prev_defects is not None \
                            and len(remaining) >= prev_defects:
                        no_gain += 1
                    else:
                        no_gain = 0
                    prev_defects = len(remaining)
                    if (added and not fell_back and len(plans) < max_plans
                            and no_gain < 2):
                        plan = _sliver_dissolve_plan(
                            temp, remaining, len(me.vertices)
                        )
                        if plan is not None:
                            plans.append(plan)
                            retry = True
                            continue
                    if not fell_back:
                        fell_back = True
                        retry = True
                        continue
                    failure = (
                        f"{region.name}: {region.magnitude_mm:.1f} mm folds "
                        f"this area ({len(remaining)} faces would tear). "
                        "Reduce the amount, widen the region, or smooth the "
                        "scan first — nothing was changed"
                    )
                    break
                new_cross = (
                    _cross_sheet_pairs(
                        temp, static_tree, static_faces, affected
                    )
                    - pre_cross
                )
                if new_cross:
                    failure = (
                        f"{region.name}: {region.magnitude_mm:.1f} mm "
                        f"crosses another surface of the body "
                        f"({len(new_cross)} face pairs). Reduce the amount "
                        "— nothing was changed"
                    )
                    break

                # Valid: one atomic in-place write of the real patient mesh.
                bm = bmesh.new()
                bm.from_mesh(temp)
                bm.to_mesh(me)
                bm.free()
                me.validate()
                me.update()
                break
            finally:
                bpy.data.meshes.remove(temp)
        finally:
            bpy.data.meshes.remove(refined_me)
        if failure is not None or retry:
            self.report({"ERROR"}, failure or "Correction could not be made valid")
            return {"CANCELLED"}

        obj.modifiers.remove(modifier)
        obj[_committed_key(region)] = True
        _drop_distance(me, region.surface_mask)  # baked: the definition is now the mesh
        _drop_contact(me, region.surface_mask)
        _mark_refined_nonmember(obj, region, n_original)
        sync_outline(obj)
        # #54 Task 3: say what the mesh could not draw as authored.
        note = ""
        min_corner = getattr(rim_field, "min_corner_radius", None)
        drawable = _drawable_corner_mm(region.edge_mm)
        if min_corner is not None and drawable is not None \
                and min_corner * 1000.0 < drawable - 1e-9:
            note = (
                f"Corner {min_corner * 1000.0:.1f} mm is finer than this mesh "
                f"draws cleanly ({drawable:.1f} mm): use Rounded corners of "
                f"{drawable:.1f} mm or more, a wider feather, or Subdivide "
                "Scan first"
            )
        if pad_fold_count:
            pad_note = (
                f"{pad_fold_count} faces at the painted pad folded in the "
                "displacement and were repaired by sliding — Subdivide Scan "
                "or clean the scan for a cleaner pad"
            )
            note = f"{note}; {pad_note}" if note else pad_note
        region.commit_note = note
        region.refined_added = added
        region.refined_edge_mm = refine_mm
        # Downstream invalidation (#49 audit B4/B7): the cached faired base
        # would rebuild the brace from the PRE-commit body, and the scan
        # verify counters describe the old mesh.
        stale_base = bpy.data.objects.get(CORSET_BASE_NAME)
        if stale_base is not None:
            bpy.data.objects.remove(stale_base, do_unlink=True)
        for key in ("rigo_boundary", "rigo_nonmanifold", "rigo_loose",
                    "rigo_verify_ok"):
            if key in obj:
                del obj[key]
        mark_brace_dirty(context, "Pressure/expansion changed the corrected body")
        verb = "pressed in" if region.kind == "PRESSURE" else "expanded out"
        if fell_back:
            self.report(
                {"WARNING"},
                f"{region.name}: the refined wall could not be made valid "
                "near a sharp crease — committed with the scan's own "
                "sampling there. Smooth the scan first for a finer wall",
            )
        refined_note = (
            f" — wall refined to carry the transition ({added} points, "
            f"{refine_mm:.1f} mm)" if added else ""
        )
        if note:
            self.report({"WARNING"}, f"{region.name}: {note}")
        self.report(
            {"INFO"},
            f"{region.name}: committed {verb} "
            f"{region.magnitude_mm:.1f} mm{refined_note}",
        )
        return {"FINISHED"}


# Landmarks with an unambiguous left/right counterpart (Wave 2 decision 2).
# Midline labels (C7, THORACIC_APEX, LUMBAR_APEX, WAISTLINE, NONE) are never
# auto-changed.
_SIDED_LABELS = {
    "ACROMION_L": "ACROMION_R", "SCAPULA_L": "SCAPULA_R",
    "AXILLA_L": "AXILLA_R", "ILIAC_L": "ILIAC_R", "ASIS_L": "ASIS_R",
    "PSIS_L": "PSIS_R", "TROCHANTER_L": "TROCHANTER_R",
}
_SIDED_LABELS.update({v: k for k, v in list(_SIDED_LABELS.items())})


def _adopt_outward(obj, group, mask, region, contact):
    """Turn a freshly created region (group already filled from a chart
    field) into an outward one from its painted set (#54 Task 7)."""
    fields = _outward_fields_from_contact(
        obj.data, contact, region.feather_mm, region.falloff_type,
        _region_profile(region),
    )
    if fields is None:
        return False
    weights, depth_mm, band_mm = fields
    stale = [
        vertex.index for vertex in obj.data.vertices
        if vertex.index not in weights
        and any(g.group == group.index for g in vertex.groups)
    ]
    if stale:
        group.remove(stale)
    for index, weight in weights.items():
        group.add([index], max(weight, _MASK_EDGE_WEIGHT), "REPLACE")
    _store_distance(obj.data, mask, depth_mm, band_mm)
    _store_contact(obj.data, mask, contact)
    region.feather_outside = True
    region.depth_mm = max(depth_mm.values()) if depth_mm else 0.0
    return True


class RIGO_OT_region_mirror(Operator):
    """Create the coupled opposite-side region across the sagittal plane"""

    bl_idname = "rigo.region_mirror"
    bl_label = "Mirror Region"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_region(_scan(context)) is not None

    def execute(self, context):
        obj = _scan(context)
        src = _active_region(obj)
        if src is None:
            self.report({"ERROR"}, "Add a region first")
            return {"CANCELLED"}
        vg_src = obj.vertex_groups.get(src.surface_mask)
        if vg_src is None:
            self.report({"ERROR"}, f"Mask '{src.surface_mask}' is missing")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        me = obj.data
        coords, eval_normals = _evaluated_positions(obj)
        if coords is None:
            coords = [v.co.copy() for v in me.vertices]
            eval_normals = [v.normal.copy() for v in me.vertices]

        # Anchor: the source anchor reflected across the sagittal plane,
        # re-projected onto the actual opposite surface (evaluated state).
        snapshot = _load_snapshot(obj, src.surface_mask)
        if snapshot and snapshot.get("anchor_world"):
            src_anchor = Vector(snapshot["anchor_world"])
        else:
            src_anchor = obj.matrix_world @ Vector(src.center)
        mirrored_anchor = Vector((-src_anchor.x, src_anchor.y, src_anchor.z))
        target, normal = _target_surface(obj, mirrored_anchor)
        if target is None:
            self.report({"ERROR"}, "Could not find the opposite surface")
            return {"CANCELLED"}

        legacy = False
        weights_m = {}
        if snapshot is not None:
            # Derive the mirrored footprint from the UNdisplaced bake-time
            # snapshot, evaluated through the same continuous-field path the
            # importer uses.  Mirroring the frame flips the side axis, so the
            # chart mirrors as u -> -u.  This replaces the old
            # nearest-vertex transfer, which sampled the CURRENT (possibly
            # displaced) surface and collapsed weights onto a fraction of
            # the vertices (#48 Wave 2: 241 -> 57 unique verts measured).
            samples_m = [
                [-s[0], s[1], s[2]] for s in snapshot["samples"]
            ]
            spacing = float(
                snapshot.get(
                    "spacing_mm",
                    float(snapshot.get("sample_radius_mm", 3.5)) / 1.75,
                )
            )
            entry_m = {
                "samples": samples_m,
                "sample_radius_mm": snapshot.get("sample_radius_mm", 3.0),
                "normal_tolerance_mm": snapshot.get(
                    "normal_tolerance_mm", 15.0
                ),
                "field": _field_from_samples(samples_m, spacing),
                "max_geodesic_mm": snapshot.get("max_geodesic_mm"),
            }
            weights_m, _realized = _weights_from_style(
                obj, entry_m, target, normal, coords
            )
        if len(weights_m) < 3:
            # Legacy region without a usable snapshot: fall back to the old
            # nearest-vertex transfer of the current surface.
            legacy = True
            tree = kdtree.KDTree(len(coords))
            for index, co in enumerate(coords):
                tree.insert(co, index)
            tree.balance()
            gi = vg_src.index
            for v in me.vertices:
                w = 0.0
                for g in v.groups:
                    if g.group == gi:
                        w = g.weight
                        break
                if w <= 0.0:
                    continue
                source_co = coords[v.index]
                _co, idx, _dist = tree.find(
                    Vector((-source_co.x, source_co.y, source_co.z))
                )
                if idx is not None:
                    weights_m[idx] = max(weights_m.get(idx, 0.0), w)
        if len(weights_m) < 3:
            self.report({"ERROR"}, "Mirroring found no opposite-side surface")
            return {"CANCELLED"}

        seq = int(obj.get("rigo_region_seq", 0)) + 1
        obj["rigo_region_seq"] = seq
        mask = f"RIGO_REGION_{seq:03d}"
        vg_new = obj.vertex_groups.new(name=mask)
        for idx, w in weights_m.items():
            vg_new.add([idx], max(w, _MASK_EDGE_WEIGHT), "REPLACE")
        # The mirrored region gets its OWN undisplaced snapshot, so saving
        # it as a style never falls back to displaced-geometry sampling.
        _store_snapshot(
            obj, mask, _style_snapshot(
                obj, weights_m, coords, eval_normals, origin_world=target
            )
        )

        src_index = obj.rigo_region_index
        new = obj.rigo_regions.add()
        new.name = f"{src.name} (mirror)"
        # Sided landmarks map to their counterpart, flagged for review;
        # midline labels are copied untouched (Wave 2 decision 2).
        mapped = _SIDED_LABELS.get(src.anatomical_label)
        new.anatomical_label = mapped or src.anatomical_label
        new.label_auto_mapped = mapped is not None
        new.mirrored_from = src.name
        # The Rigo couple: pressure on one side, expansion room on the other.
        new.kind = "EXPANSION" if src.kind == "PRESSURE" else "PRESSURE"
        new.center = obj.matrix_world.inverted() @ target
        new.direction = (
            obj.matrix_world.to_3x3().inverted() @ normal
        ).normalized()
        new.magnitude_mm = src.magnitude_mm
        new.radius_mm = src.radius_mm
        new.falloff_type = src.falloff_type
        new.feather_mm = src.feather_mm
        new.top_radius_mm = src.top_radius_mm
        new.bottom_radius_mm = src.bottom_radius_mm
        if src.feather_outside:
            # #54 Task 7: mirror the PAD, then re-derive the band on the
            # opposite surface (the mirrored field only names the pad).
            _adopt_outward(obj, vg_new, mask, new,
                           [i for i, w in weights_m.items() if w >= 0.999])
        new.surface_mask = mask
        new.opposing_region = src_index
        obj.rigo_regions[src_index].opposing_region = len(obj.rigo_regions) - 1
        obj.rigo_region_index = len(obj.rigo_regions) - 1
        _sync_preview(obj, new)
        sync_outline(obj)

        # On an asymmetric (scoliotic) body the exact mirror position can lie
        # off-surface; the region is anchored to the closest real surface
        # instead, and a large gap is flagged for review — never hidden.
        asym_mm = (target - mirrored_anchor).length * 1000.0
        if asym_mm > 15.0:
            self.report(
                {"WARNING"},
                f"The opposite surface is {asym_mm:.0f} mm from the exact "
                "mirror position (asymmetric body) — review the placement",
            )
        how = (
            "legacy nearest-vertex transfer — REVIEW the footprint"
            if legacy else "derived from the authored field"
        )
        self.report(
            {"INFO"},
            f"{new.name}: {len(weights_m)} verts ({how}) — review the kind",
        )
        return {"FINISHED"}


def _mark_refined_nonmember(obj, region, n_original):
    """Kept name; see ``extend_region_attributes``."""
    extend_region_attributes(obj, n_original, skip=region)


def extend_region_attributes(obj, n_original, skip=None):
    """Give vertices born after ``n_original`` (commit refinement, Subdivide
    Scan) a consistent place in every OTHER live region's definition.

    A fresh point attribute reads 0.0 / False, which the signed encoding
    would take for a pad vertex at the outline; and the deform layer gives
    those vertices INTERPOLATED group weights, so with NaN distance they
    would keep that weight through every later Feather edit (Codex round
    C, Q1: phantom influence).  Here each new vertex takes its stored
    distance from its original neighbours: a band neighbour -> band (mean
    of their negative distances); only pad neighbours -> pad; nothing known
    -> NaN, non-member.  Legacy regions keep -1 (non-member), as before."""
    me = obj.data
    n = len(me.vertices)
    if n <= n_original:
        return
    neighbours = None
    for other in obj.rigo_regions:
        if other == skip or not other.surface_mask:
            continue
        if obj.get(_committed_key(other), False):
            continue
        depth = _load_distance(me, other.surface_mask)
        if depth is None:
            continue
        contact = _outward_contact(me, other)
        if contact is None:
            depth[n_original:] = -1.0
        else:
            if neighbours is None:
                neighbours = _mesh_neighbours(me)
            for v in range(n_original, n):
                band, pad = [], []
                for j in neighbours(v):
                    if j >= n_original:
                        continue
                    if contact[j]:
                        pad.append(depth[j])
                    elif depth[j] < 0.0:
                        band.append(depth[j])
                if band:
                    depth[v] = float(np.mean(band))
                    contact[v] = False
                elif pad:
                    depth[v] = float(np.mean(pad))
                    contact[v] = True
                else:
                    depth[v] = np.nan
                    contact[v] = False
            me.attributes[_contact_name(other.surface_mask)].data.foreach_set(
                "value", contact
            )
        me.attributes[_dist_name(other.surface_mask)].data.foreach_set(
            "value", depth.astype(np.float32)
        )


class RIGO_OT_region_remove(Operator):
    """Delete the selected region and its mask"""

    bl_idname = "rigo.region_remove"
    bl_label = "Remove Region"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_region(_scan(context)) is not None

    def execute(self, context):
        obj = _scan(context)
        idx = obj.rigo_region_index
        region = _active_region(obj)
        if region is None:
            self.report({"ERROR"}, "No region selected")
            return {"CANCELLED"}

        _remove_preview(obj, region)
        committed_key = _committed_key(region)
        if committed_key in obj:
            del obj[committed_key]
        _drop_snapshot(obj, region.surface_mask)
        _drop_distance(obj.data, region.surface_mask)
        _drop_contact(obj.data, region.surface_mask)
        vg = obj.vertex_groups.get(region.surface_mask)
        if vg is not None:
            obj.vertex_groups.remove(vg)
        name = region.name
        obj.rigo_regions.remove(idx)

        # Re-point opposing links after the index shift.
        for r in obj.rigo_regions:
            if r.opposing_region == idx:
                r.opposing_region = -1
            elif r.opposing_region > idx:
                r.opposing_region -= 1
        obj.rigo_region_index = min(idx, len(obj.rigo_regions) - 1)
        sync_outline(obj)

        self.report({"INFO"}, f"Removed {name}")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_region_add,
    RIGO_OT_region_add_circle,
    RIGO_OT_region_edit,
    RIGO_OT_region_update,
    RIGO_OT_region_style_save,
    RIGO_OT_region_style_import,
    RIGO_OT_region_style_delete,
    RIGO_OT_region_apply,
    RIGO_OT_region_mirror,
    RIGO_OT_region_remove,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
