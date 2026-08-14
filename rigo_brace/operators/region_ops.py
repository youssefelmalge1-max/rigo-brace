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

from ..core import mark_brace_dirty, region_library


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
    # seed / import cursor); painted regions fall back to the weight-weighted
    # core centroid.  The frame NORMAL must be derived exactly the way the
    # import side derives it (_target_surface at the anchor) — any other
    # normal (area mean, weighted mean) shears the projection on creased
    # surfaces and shifts the imported footprint.
    if origin_world is None:
        center = Vector()
        total = 0.0
        for i in indices:
            w = max(weights[i], 1e-6)
            center += (matrix @ coords[i]) * w
            total += w
        center /= total
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
    snapshot = {
        "samples": samples,
        "sample_radius_mm": max(1.0, spacing * 1.75),
        "normal_tolerance_mm": max(15.0, max(normal_offsets) + spacing * 2.0),
        "spacing_mm": spacing,
    }
    if build_field:
        snapshot["field"] = _field_from_samples(samples, spacing)
    return snapshot


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
            # Core plateau: the full requested amount must survive resampling.
            if value >= 0.99:
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


def _repair_folds(obj, weights, pre_face_normals, pre_vertex_normals,
                  adjacency, baseline, affected=None, fold_pairs=()):
    """Remove folded, degenerate or self-intersecting slivers after commit.

    Slides ONLY the vertices of defective faces (plus one ring, never outside
    the mask) toward their one-ring mean, restricted to the pre-commit
    tangent plane — the normal component, i.e. the clinical mm amount, is
    preserved by construction.  ``baseline`` holds face indices that were
    already defective BEFORE the commit (dirty scans) — those are not ours to
    fix and never count.  Deterministic, bounded, self-terminating.
    Returns the number of faces still defective after the pass.
    """
    me = obj.data
    member = {i for i, w in weights.items() if w > 0.0}
    if not member:
        return 0
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
        return bad - baseline

    bad = defective()
    for _ in range(20):
        if not bad:
            return 0
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
            normal = pre_vertex_normals[vi]
            delta -= normal * delta.dot(normal)  # tangential slide only
            me.vertices[vi].co += delta * 0.5
        me.update()
        bad = defective()
    return len(bad)


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
    return _geodesic_trim(scan, weights, coords, target_world, samples)


def _geodesic_trim(scan, weights, coords, target_world, samples):
    """Soft-trim vertices the authored region could never have reached.

    The tangent-plane mapping is extrinsic: it happily assigns weights across
    a concave fold to surface 22 mm away in space but 50 mm away along the
    surface.  The authored region (paint or geodesic circle) is intrinsic, so
    the surface path from the cursor, measured inside the footprint, must not
    exceed the sample span; the excess fades out smoothly, never a cliff.
    """
    if not weights:
        return weights
    limit = max(math.hypot(s[0], s[1]) for s in samples) * 1.35 * 0.001
    if limit <= 0.0:
        return weights
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
    for i, w in weights.items():
        d = dist.get(i)
        if d is None:
            continue
        if d > fade_start:
            t = 1.0 - (d - fade_start) / (limit - fade_start)
            w *= t * t * (3.0 - 2.0 * t)
        if w > 0.005:
            trimmed[i] = w
    return trimmed


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
        _store_snapshot(obj, mask, _style_snapshot(obj, weights))

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
            _store_snapshot(
                obj, region.surface_mask, _style_snapshot(obj, weights)
            )
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
    in a surface-local frame, plus the Amount (mm), Feather and Falloff, the
    Pressure/Expansion kind and the surface orientation (schema v2), so the
    style can be re-applied on any compatible body surface.
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
        weights = _weights_from_style(scan, entry, target, normal, coords)
        if len(weights) < 3:
            self.report({"ERROR"}, "Saved style does not overlap enough scan vertices")
            return {"CANCELLED"}

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
        region.radius_mm = max(
            (Vector((sample[0], sample[1])).length for sample in entry["samples"]),
            default=0.0,
        )
        region.falloff_type = entry.get("falloff", "SMOOTH")
        region.surface_mask = mask
        scan.rigo_region_index = len(scan.rigo_regions) - 1
        _sync_preview(scan, region)
        self.report(
            {"INFO"},
            f"Imported '{entry['label']}' as a live region; orthotist review required",
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
        group = obj.vertex_groups.get(region.surface_mask)
        weights = {}
        for vertex in obj.data.vertices:
            for g in vertex.groups:
                if g.group == group.index:
                    weights[vertex.index] = g.weight
                    break
        me = obj.data
        member = {i for i, w in weights.items() if w > 0.0}
        affected = [
            p for p in me.polygons if any(vi in member for vi in p.vertices)
        ]
        pre_face_normals = {p.index: p.normal.copy() for p in affected}
        zone = set(member)
        for p in affected:
            zone.update(p.vertices)
        pre_vertex_normals = {i: me.vertices[i].normal.copy() for i in zone}
        edge_total = 0.0
        edge_count = 0
        for edge in me.edges:
            a, b = edge.vertices
            if a in member or b in member:
                edge_total += (me.vertices[a].co - me.vertices[b].co).length
                edge_count += 1
        mean_edge = edge_total / edge_count if edge_count else 0.003

        # Pre-existing defects on a dirty scan are not ours to fix or to
        # block on — baseline them out of the repair verdict.
        baseline = _footprint_self_intersections(me, member, affected)
        baseline |= {p.index for p in affected if p.area < 1e-12}
        pre_positions = {i: me.vertices[i].co.copy() for i in member}

        # Commit analytically along FAIRED normals: |displacement| is exactly
        # amount × weight (unit directions), matching the preview magnitude,
        # while the coherent direction field keeps scan creases from
        # shredding the way raw per-vertex normals do (#48).
        faired, adjacency = _faired_normals(me, weights, mean_edge)
        sign = -1.0 if region.kind == "PRESSURE" else 1.0
        offset = sign * region.magnitude_mm * 0.001

        # Wave 1 (P0): the footprint-local checks cannot see the far side of
        # the body.  Predict wall contact BEFORE mutating anything, and
        # baseline the cross-sheet contact state for the post-commit net.
        static_tree, static_faces = _static_faces_bvh(me, member)
        blocked = _wall_blocked_points(me, weights, faired, offset,
                                       static_tree)
        if blocked:
            self.report(
                {"ERROR"},
                f"{region.name}: {region.magnitude_mm:.1f} mm would press "
                f"through or within {_WALL_CLEARANCE_MM:.0f} mm of the "
                f"opposite body surface ({blocked} points). Reduce the "
                "amount — nothing was changed",
            )
            return {"CANCELLED"}
        fold_pairs = _edge_face_pairs(affected)
        pre_cross = _cross_sheet_pairs(me, static_tree, static_faces, affected)

        for i in faired:
            me.vertices[i].co += faired[i] * (offset * weights[i])
        me.update()
        remaining = _repair_folds(
            obj, weights, pre_face_normals, pre_vertex_normals, adjacency,
            baseline, affected, fold_pairs,
        )
        if remaining:
            # State safety (#48 contract 8): never leave a torn commit.
            # Restore bit-exactly and keep the live preview for adjustment.
            for i, co in pre_positions.items():
                me.vertices[i].co = co
            me.update()
            self.report(
                {"ERROR"},
                f"{region.name}: {region.magnitude_mm:.1f} mm folds this area "
                f"({remaining} faces would tear). Reduce the amount, widen "
                "the region, or smooth the scan first — nothing was changed",
            )
            return {"CANCELLED"}
        new_cross = (
            _cross_sheet_pairs(me, static_tree, static_faces, affected)
            - pre_cross
        )
        if new_cross:
            for i, co in pre_positions.items():
                me.vertices[i].co = co
            me.update()
            self.report(
                {"ERROR"},
                f"{region.name}: {region.magnitude_mm:.1f} mm crosses "
                f"another surface of the body ({len(new_cross)} face "
                "pairs). Reduce the amount — nothing was changed",
            )
            return {"CANCELLED"}
        obj.modifiers.remove(modifier)
        obj[_committed_key(region)] = True
        mark_brace_dirty(context, "Pressure/expansion changed the corrected body")
        verb = "pressed in" if region.kind == "PRESSURE" else "expanded out"
        self.report(
            {"INFO"},
            f"{region.name}: committed {verb} {region.magnitude_mm:.1f} mm",
        )
        return {"FINISHED"}


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
        tree = kdtree.KDTree(len(me.vertices))
        for v in me.vertices:
            tree.insert(v.co, v.index)
        tree.balance()

        gi = vg_src.index
        seq = int(obj.get("rigo_region_seq", 0)) + 1
        obj["rigo_region_seq"] = seq
        mask = f"RIGO_REGION_{seq:03d}"
        vg_new = obj.vertex_groups.new(name=mask)

        pairs = 0
        for v in me.vertices:
            w = 0.0
            for g in v.groups:
                if g.group == gi:
                    w = g.weight
                    break
            if w <= 0.0:
                continue
            mirrored = Vector((-v.co.x, v.co.y, v.co.z))
            _co, idx, _dist = tree.find(mirrored)
            if idx is not None:
                vg_new.add([idx], w, "REPLACE")
                pairs += 1

        src_index = obj.rigo_region_index
        new = obj.rigo_regions.add()
        new.name = f"{src.name} (mirror)"
        new.anatomical_label = "NONE"
        # The Rigo couple: pressure on one side, expansion room on the other.
        new.kind = "EXPANSION" if src.kind == "PRESSURE" else "PRESSURE"
        new.center = (-src.center[0], src.center[1], src.center[2])
        new.direction = (-src.direction[0], src.direction[1], src.direction[2])
        new.magnitude_mm = src.magnitude_mm
        new.radius_mm = src.radius_mm
        new.falloff_type = src.falloff_type
        new.surface_mask = mask
        new.opposing_region = src_index
        obj.rigo_regions[src_index].opposing_region = len(obj.rigo_regions) - 1
        obj.rigo_region_index = len(obj.rigo_regions) - 1
        _sync_preview(obj, new)

        self.report({"INFO"}, f"{new.name}: {pairs} verts mirrored — review the kind")
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
