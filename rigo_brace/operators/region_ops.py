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
from bpy.props import StringProperty
from bpy.types import Operator
from mathutils import Vector, kdtree

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
                    build_field=False, origin_world=None):
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
        strong = [i for i in indices if weights[i] >= 0.3] or indices
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
    ring1 = set(member)
    for edge in me.edges:
        a, b = edge.vertices
        if a in member or b in member:
            ring1.add(a)
            ring1.add(b)
    adjacency = {}
    for edge in me.edges:
        a, b = edge.vertices
        if a in ring1 or b in ring1:
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


def _footprint_self_intersections(me, member, faces=None):
    """Indices of footprint faces that intersect a non-adjacent face."""
    from mathutils.bvhtree import BVHTree

    if faces is None:
        faces = [
            p for p in me.polygons if any(vi in member for vi in p.vertices)
        ]
    if not faces:
        return set()
    # Local vertex table: only the footprint-face vertices, not the whole scan.
    used = sorted({vi for p in faces for vi in p.vertices})
    local = {vi: n for n, vi in enumerate(used)}
    verts = [me.vertices[vi].co for vi in used]
    polys = [tuple(local[vi] for vi in p.vertices) for p in faces]
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=True)
    bad = set()
    for a, b in tree.overlap(tree):
        if a == b or set(polys[a]) & set(polys[b]):
            continue
        bad.add(faces[a].index)
        bad.add(faces[b].index)
    return bad


def _static_faces_bvh(me, member):
    """BVH of the body's faces that hold NO footprint vertex (they never move
    during a commit).  These are exactly the faces the footprint-local checks
    cannot see — the opposite body wall, adjacent anatomical sheets (#48
    Wave 1, P0)."""
    from mathutils.bvhtree import BVHTree

    faces = [
        p for p in me.polygons if not any(vi in member for vi in p.vertices)
    ]
    if not faces:
        return None, []
    used = sorted({vi for p in faces for vi in p.vertices})
    local = {vi: n for n, vi in enumerate(used)}
    verts = [me.vertices[vi].co.copy() for vi in used]
    polys = [tuple(local[vi] for vi in p.vertices) for p in faces]
    return BVHTree.FromPolygons(verts, polys, all_triangles=True), faces


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
    from mathutils.bvhtree import BVHTree

    if static_tree is None or not affected:
        return set()
    used = sorted({vi for p in affected for vi in p.vertices})
    local = {vi: n for n, vi in enumerate(used)}
    verts = [me.vertices[vi].co.copy() for vi in used]
    polys = [tuple(local[vi] for vi in p.vertices) for p in affected]
    moved = BVHTree.FromPolygons(verts, polys, all_triangles=True)
    pairs = set()
    for a, b in moved.overlap(static_tree):
        face_a = affected[a]
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
    for a, b in fold_pairs:
        if pre_face_normals[a].dot(pre_face_normals[b]) <= _FOLD_PRE_DOT:
            continue  # already creased shut before us — not ours
        if me.polygons[a].normal.dot(me.polygons[b].normal) < _FOLD_DOT:
            folded.add(a)
            folded.add(b)
    return folded


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
            for e in sorted(v.link_edges, key=lambda e: e.calc_length()):
                n = e.other_vert(v)
                if n in plan_set or not n.is_valid:
                    continue
                if n.index >= n_start:
                    # prefer an ORIGINAL target if one is also safe
                    better = None
                    for e3 in sorted(v.link_edges,
                                     key=lambda e3: e3.calc_length()):
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
                      curved=True, harmonic=True):
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
    """
    weights = {}
    for v in temp_me.vertices:
        for g in v.groups:
            if g.group == group_index:
                weights[v.index] = g.weight
                break
    if not weights:
        return 0, 0.0
    edge_total = 0.0
    edge_count = 0
    for e in temp_me.edges:
        a, b = e.vertices
        if a in weights or b in weights:
            edge_total += (
                temp_me.vertices[a].co - temp_me.vertices[b].co
            ).length
            edge_count += 1
    if not edge_count:
        return 0, 0.0
    mean_edge = edge_total / edge_count
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

    # New-vertex weights come from a smooth 3D IDW over the ORIGINAL
    # vertices' authored weights.  Parent-edge interpolation provably keeps
    # the staircase; a chart-space field disagrees with the authored
    # per-vertex weights exactly at creases (measured: fold-scale weight
    # jumps).  k-NN IDW in 3D is smooth, exactly consistent with the
    # surviving original weights, and needs no snapshot (legacy regions
    # refine too).
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
            h_req = h_required(g)
            if h_req is None:
                continue
            predicted = math.hypot(length, abs(offset) * abs(wa - wb))
            if predicted > 1.4 * h_req:
                h_target = min(h_target, h_req)
                marked.append(e)
        if not marked:
            break
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
        bmesh.ops.subdivide_edges(
            bm, edges=marked, cuts=1, use_grid_fill=False,
        )
        ngons = [f for f in bm.faces if len(f.verts) > 3]
        if ngons:
            bmesh.ops.triangulate(bm, faces=ngons)
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
            for e in sorted(v.link_edges, key=lambda e: e.calc_length()):
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
            # Deterministic input order (sets iterate by pointer): flips
            # must be bit-reproducible run to run.
            bm.faces.index_update()
            seen = set()
            faces = []
            for e in interior:
                for f in e.link_faces:
                    if f not in seen:
                        seen.add(f)
                        faces.append(f)
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
        for f in cap_faces:
            if len(f.verts) != 3:
                continue
            els = [(e.calc_length(), e) for e in f.edges]
            longest, e_long = max(els, key=lambda t: t[0])
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
            try:
                bmesh.ops.rotate_edges(bm, edges=unique, use_ccw=False)
            except RuntimeError:
                pass
        # Sliver purge: any residual refinement-born triangle thinner than
        # the sampling target has a numerically unstable normal that folds
        # under displacement (measured: every stubborn fold was such a
        # sliver).  Collapse its shortest new-vertex edge — deterministic,
        # never moves an original vertex, repeated until clean.
        for _purge in range(2):
            new_set = {v for v in new_set if v.is_valid}
            purge_seen = set()
            purge_faces = []
            for v in sorted(new_set, key=lambda v: v.index):
                for f in v.link_faces:
                    if f not in purge_seen:
                        purge_seen.add(f)
                        purge_faces.append(f)
            any_collapsed = False
            for f in purge_faces:
                if not f.is_valid or len(f.verts) != 3:
                    continue
                els = [(e.calc_length(), e) for e in f.edges]
                longest = max(length for length, _e in els)
                if longest < 1e-9 or 2.0 * f.calc_area() / longest \
                        >= 0.3 * h_target:
                    continue
                done = False
                for _length, e in sorted(els, key=lambda t: t[0]):
                    if not e.is_valid:
                        continue
                    va, vb = e.verts
                    if va in new_set and _link_safe_collapse(bm, va, vb):
                        done = True
                        break
                    if vb in new_set and _link_safe_collapse(bm, vb, va):
                        done = True
                        break
                if not done:
                    # No link-safe collapse: rotate the sliver's long edge
                    # instead — position-preserving, manifold-safe, and the
                    # classical escape for an uncollapsible thin triangle
                    # (#49d: one such survivor displaced into an inverted
                    # face on the decim065 fixture).
                    _l, e_long = max(els, key=lambda t: t[0])
                    if e_long.is_valid and len(e_long.link_faces) == 2:
                        try:
                            bmesh.ops.rotate_edges(
                                bm, edges=[e_long], use_ccw=False
                            )
                            done = True
                        except RuntimeError:
                            pass
                if done:
                    any_collapsed = True
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
    bmesh.ops.weld_verts(bm, targetmap={v: n})
    return True


def _nonmanifold_count(me):
    """Edges not shared by exactly two faces (#49d transactional guard):
    dissolution welds are the commit's only topology-editing step and must
    never change the mesh's manifoldness — a fin or duplicate face that the
    local weld cleanup missed must never ship."""
    counts = [0] * len(me.edges)
    edge_indices = [0] * len(me.loops)
    me.loops.foreach_get("edge_index", edge_indices)
    for i in edge_indices:
        counts[i] += 1
    return sum(1 for c in counts if c != 2)


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
        affected = [
            p for p in me.polygons if any(vi in member for vi in p.vertices)
        ]

    def defective():
        bad = {
            p.index for p in affected
            if p.normal.dot(pre_face_normals[p.index]) <= 1e-9
            or p.area < 1e-12
        }
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
    return bad


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


def _region_weights_from_selection(obj, feather_mm, falloff_kind):
    """Read the Edit-Mode selection and compute per-vertex falloff weights.

    Weight rises from 0 at the painted boundary to 1 at ``feather_mm`` deep
    (topological rings converted via the mean selected edge length), so the
    core of the region gets the full mm amount and the edge blends to zero.
    Returns (weights {vert_index: w}, centroid, mean_normal, radius_mm).
    """
    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    bm.verts.ensure_lookup_table()

    sel = [v for v in bm.verts if v.select]
    if not sel:
        return None, None, None, 0.0

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
        return None, None, None, 0.0
    normal.normalize()

    # Geodesic (edge-walk Dijkstra) distance in METRES from the boundary
    # inward.  Integer topological rings quantized the feather into visible
    # terraces on irregular scan triangles (#48 RC4); real surface distance
    # keeps the falloff continuous whatever the triangulation.
    sel_set = {v.index for v in sel}
    boundary = [
        v for v in sel
        if any(e.other_vert(v).index not in sel_set for e in v.link_edges)
    ]
    if not boundary:  # closed selection (whole mesh) — no boundary anywhere
        weights = {v.index: 1.0 for v in sel}
        return weights, centroid.copy(), normal, radius_mm

    depth = {v.index: 0.0 for v in boundary}
    heap = [(0.0, v.index) for v in boundary]
    heapq.heapify(heap)
    while heap:
        d, idx = heapq.heappop(heap)
        if d > depth.get(idx, 1e30):
            continue
        for e in bm.verts[idx].link_edges:
            o = e.other_vert(bm.verts[idx])
            if o.index not in sel_set:
                continue
            nd = d + e.calc_length()
            if nd < depth.get(o.index, 1e30):
                depth[o.index] = nd
                heapq.heappush(heap, (nd, o.index))
    max_depth = max(depth.values())

    # Feather cannot be wider than the region is deep — normalize so the
    # innermost vertices always reach full weight 1.0.
    f_eff = min(feather_mm * 0.001, max_depth)
    weights = {}
    for idx in sel_set:
        d = depth.get(idx, max_depth)
        if f_eff <= 1e-9:
            weights[idx] = 1.0
        else:
            weights[idx] = _falloff(min(d, f_eff) / f_eff, falloff_kind)
    return weights, centroid.copy(), normal, radius_mm


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

        weights, centroid, normal, radius_mm = _region_weights_from_selection(
            obj, settings.region_feather, settings.region_falloff
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
        # Snapshot against the EVALUATED surface (what the user painted on),
        # like the circle path — the last raw-vs-evaluated mixed-state path
        # (#48 Wave 2); falls back to raw coords when a modifier changes the
        # vertex count.
        coords_e, normals_e = _evaluated_positions(obj)
        _store_snapshot(
            obj, mask, _style_snapshot(obj, weights, coords_e, normals_e)
        )

        region = obj.rigo_regions.add()
        region.name = f"Region {seq}"
        region.kind = settings.region_kind
        region.center = centroid
        region.direction = normal
        region.magnitude_mm = settings.region_magnitude
        region.radius_mm = radius_mm
        region.falloff_type = settings.region_falloff
        region.surface_mask = mask
        obj.rigo_region_index = len(obj.rigo_regions) - 1
        _sync_preview(obj, region)

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
        weights = {
            i: _falloff(1.0 - d / radius, falloff) for i, d in dist.items()
        }
        weights = {i: w for i, w in weights.items() if w > 0.0}
        weights[seed] = 1.0
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
            vg.add([idx], w, "REPLACE")
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
        region.falloff_type = falloff
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
        included = set()
        for vertex in obj.data.vertices:
            vertex.select = False
            if any(g.group == group_index and g.weight > 0.0 for g in vertex.groups):
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
            settings = context.scene.rigo_brace
            weights, centroid, normal, radius_mm = _region_weights_from_selection(
                obj, settings.region_feather, settings.region_falloff
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
                _style_snapshot(obj, weights, coords_e, normals_e),
            )
            if own_preview is not None:
                own_preview.show_viewport = shown
            region.center = centroid
            region.direction = normal
            region.radius_mm = radius_mm
            region.falloff_type = settings.region_falloff

        _sync_preview(obj, region)
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
        _store_snapshot(
            scan, mask, _style_snapshot(
                scan, weights, coords, eval_normals, origin_world=target
            )
        )

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
        clinical = entry.get("clinical") or {}
        if clinical.get("anatomical_label"):
            try:
                region.anatomical_label = clinical["anatomical_label"]
            except TypeError:
                pass
        region.surface_mask = mask
        scan.rigo_region_index = len(scan.rigo_regions) - 1
        _sync_preview(scan, region)
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
        refined_me = me.copy()
        added0, refine_mm0 = _refine_footprint(refined_me, group.index,
                                               offset)
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
                affected = [
                    p for p in temp.polygons
                    if any(vi in member for vi in p.vertices)
                ]
                pre_face_normals = {
                    p.index: p.normal.copy() for p in affected
                }
                zone = set(member)
                for p in affected:
                    zone.update(p.vertices)
                pre_vertex_normals = {
                    i: temp.vertices[i].normal.copy() for i in zone
                }
                edge_total = 0.0
                edge_count = 0
                for edge in temp.edges:
                    a, b = edge.vertices
                    if a in member or b in member:
                        edge_total += (
                            temp.vertices[a].co - temp.vertices[b].co
                        ).length
                        edge_count += 1
                mean_edge = edge_total / edge_count if edge_count else 0.003

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
        new.surface_mask = mask
        new.opposing_region = src_index
        obj.rigo_regions[src_index].opposing_region = len(obj.rigo_regions) - 1
        obj.rigo_region_index = len(obj.rigo_regions) - 1
        _sync_preview(obj, new)

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
