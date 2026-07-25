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
import bpy
import bmesh
from bpy.props import StringProperty
from bpy.types import Operator
from mathutils import Vector, kdtree

from ..core import mark_brace_dirty, region_library


_PREVIEW_PREFIX = "RIGO_REGION_PREVIEW_"
_MASK_EDGE_WEIGHT = 1e-6


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


def _target_surface(scan, target_world):
    inverse = scan.matrix_world.inverted()
    found, location, normal, _index = scan.closest_point_on_mesh(inverse @ target_world)
    if not found:
        return None, None
    world_location = scan.matrix_world @ location
    world_normal = (scan.matrix_world.to_3x3() @ normal).normalized()
    return world_location, world_normal


def _weights_from_style(scan, entry, target_world, target_normal):
    side, up, outward = _surface_frame(target_normal)
    sample_tree = kdtree.KDTree(len(entry["samples"]))
    for index, sample in enumerate(entry["samples"]):
        sample_tree.insert((sample[0], sample[1], 0.0), index)
    sample_tree.balance()
    radius = max(
        float(entry["sample_radius_mm"]), _mesh_spacing_mm(scan) * 1.75
    )
    normal_limit = float(entry["normal_tolerance_mm"])
    weights = {}
    for vertex in scan.data.vertices:
        world = scan.matrix_world @ vertex.co
        relative = world - target_world
        normal_offset = abs(relative.dot(outward)) * 1000.0
        if normal_offset > normal_limit:
            continue
        coordinate = (relative.dot(side) * 1000.0, relative.dot(up) * 1000.0, 0.0)
        _nearest, sample_index, distance = sample_tree.find(coordinate)
        if distance <= radius:
            weights[vertex.index] = float(entry["samples"][sample_index][2])
    return weights


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

    # Mean edge length inside the selection -> feather mm to topological rings.
    lengths = [
        e.calc_length() for e in bm.edges if e.verts[0].select and e.verts[1].select
    ]
    avg_edge = (sum(lengths) / len(lengths)) if lengths else 0.01
    feather_rings = max(0, round((feather_mm * 0.001) / max(avg_edge, 1e-6)))

    # BFS ring distance from the region boundary inward.
    sel_set = {v.index for v in sel}
    ring = {}
    frontier = []
    for v in sel:
        for e in v.link_edges:
            o = e.other_vert(v)
            if o.index not in sel_set:
                ring[v.index] = 0
                frontier.append(v)
                break
    if not frontier:  # closed selection (whole mesh) — no boundary anywhere
        weights = {v.index: 1.0 for v in sel}
        return weights, centroid.copy(), normal, radius_mm

    depth = 0
    while frontier:
        depth += 1
        nxt = []
        for v in frontier:
            for e in v.link_edges:
                o = e.other_vert(v)
                if o.index in sel_set and o.index not in ring:
                    ring[o.index] = depth
                    nxt.append(o)
        frontier = nxt
    max_ring = max(ring.values())

    # Feather cannot be wider than the region is deep — normalize so the
    # innermost vertices always reach full weight 1.0.
    f_eff = min(feather_rings, max_ring)
    weights = {}
    for idx in sel_set:
        r = ring.get(idx, max_ring)
        if f_eff <= 0:
            weights[idx] = 1.0
        else:
            weights[idx] = _falloff(min(r, f_eff) / f_eff, falloff_kind)
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

        # Seed = the mesh vertex nearest the 3D cursor (in object space).
        cursor_local = obj.matrix_world.inverted() @ context.scene.cursor.location
        tree = kdtree.KDTree(len(me.vertices))
        for v in me.vertices:
            tree.insert(v.co, v.index)
        tree.balance()
        _co, seed, seed_dist = tree.find(cursor_local)
        radius = settings.region_radius * 0.001
        if seed_dist > radius:
            self.report({"ERROR"}, "Place the 3D cursor ON the scan surface first")
            return {"CANCELLED"}

        # Geodesic (edge-walk Dijkstra) distances from the seed, capped at the
        # radius — surface distance, so the region can NOT bleed through to the
        # far side of the body the way a plain sphere would.
        neighbors = [[] for _ in range(len(me.vertices))]
        for e in me.edges:
            a, b = e.vertices
            length = (me.vertices[a].co - me.vertices[b].co).length
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
            normal += me.vertices[i].normal * w
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

        region = obj.rigo_regions.add()
        region.name = f"Circle {seq}"
        region.kind = settings.region_kind
        region.center = me.vertices[seed].co
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
            region.center = centroid
            region.direction = normal
            region.radius_mm = radius_mm
            region.falloff_type = settings.region_falloff

        _sync_preview(obj, region)
        self.report({"INFO"}, "Preview updated along the body's local normals")
        return {"FINISHED"}


class RIGO_OT_region_style_save(Operator):
    """Save a committed correction mask as a reusable surface-local style"""

    bl_idname = "rigo.region_style_save"
    bl_label = "Save Committed Style"
    bl_options = {"REGISTER"}

    style_name: StringProperty(name="Style Name", default="My Correction Style")

    @classmethod
    def poll(cls, context):
        return _active_region(_scan(context)) is not None

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

        samples, normal_offsets, weights = _style_samples(scan, group)
        spacing = _sample_spacing_mm(scan, set(weights))
        entry = {
            "id": region_library.identifier_from_label(label),
            "label": label,
            "kind": region.kind,
            "magnitude_mm": region.magnitude_mm,
            "falloff": region.falloff_type,
            "samples": samples,
            "sample_radius_mm": max(1.0, spacing * 1.75),
            "normal_tolerance_mm": max(15.0, max(normal_offsets) + spacing * 2.0),
            "requires_orthotist_review": True,
            "schema_version": 1,
        }
        region_library.upsert_entry(entry)
        context.scene.rigo_brace.region_style = entry["id"]
        self.report({"INFO"}, f"Saved style '{label}' for reuse on other scans")
        return {"FINISHED"}


class RIGO_OT_region_style_import(Operator):
    """Place a saved correction mask at the 3D cursor as an editable preview"""

    bl_idname = "rigo.region_style_import"
    bl_label = "Import Style at Cursor"
    bl_options = {"REGISTER", "UNDO"}

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
        target, normal = _target_surface(scan, context.scene.cursor.location)
        if target is None:
            self.report({"ERROR"}, "Place the 3D cursor on the scan surface")
            return {"CANCELLED"}
        weights = _weights_from_style(scan, entry, target, normal)
        if len(weights) < 3:
            self.report({"ERROR"}, "Saved style does not overlap enough scan vertices")
            return {"CANCELLED"}

        sequence = int(scan.get("rigo_region_seq", 0)) + 1
        scan["rigo_region_seq"] = sequence
        mask = f"RIGO_REGION_{sequence:03d}"
        group = scan.vertex_groups.new(name=mask)
        for index, weight in weights.items():
            group.add([index], max(weight, _MASK_EDGE_WEIGHT), "REPLACE")

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
        modifier_name = modifier.name
        bpy.ops.object.modifier_apply(modifier=modifier_name)
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
