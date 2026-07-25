"""Trim-edge finishing: see-through view, edge smoothing, safe-edge flare
(Patch 6).

Concepts learned from WASP-Med (GPL-2+, knowledge/code_provenance.md
PROV-0009): viewport ``show_xray`` while editing trims, and CorrectiveSmooth
restricted to a vertex group. Clean original implementation for the corset:

- The exact trim cut can retain triangle-scale scan texture. "Smooth Trim Edge"
  relaxes ONLY an edge band (explicit rim + feathered
  rings inward) with a CorrectiveSmooth modifier, then bakes it.
- "Flare Edge" bends the edge band radially outward (away from the body) by a
  measured mm amount — the classic safe edge so the shell rim cannot dig in.
"""

import bpy
import bmesh
from bpy.types import Operator
from mathutils import Vector

from ..core import CORSET_NAME, brace_ready_for_finishing

_BAND_GROUP = "RIGO_TRIM_BAND"


def _corset():
    obj = bpy.data.objects.get(CORSET_NAME)
    if obj is not None and obj.type == "MESH":
        return obj
    return None


def _edge_band_weights(obj, band_mm):
    """Boundary verts (weight 1) feathered inward to 0 over ``band_mm``.

    Ring distance from the open edge, converted to rings via the mean edge
    length — same topological-feather approach as region_ops (LM-0013).
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()

    boundary = {v.index for v in bm.verts if any(e.is_boundary for e in v.link_edges)}
    if not boundary:
        bm.free()
        return {}

    lengths = [e.calc_length() for e in bm.edges]
    avg_edge = (sum(lengths) / len(lengths)) if lengths else 0.01
    rings = max(1, round((band_mm * 0.001) / max(avg_edge, 1e-6)))

    ring_of = {i: 0 for i in boundary}
    frontier = [bm.verts[i] for i in boundary]
    depth = 0
    while frontier and depth < rings:
        depth += 1
        nxt = []
        for v in frontier:
            for e in v.link_edges:
                o = e.other_vert(v)
                if o.index not in ring_of:
                    ring_of[o.index] = depth
                    nxt.append(o)
        frontier = nxt
    bm.free()

    weights = {}
    for idx, ring in ring_of.items():
        t = 1.0 - ring / rings
        weights[idx] = t * t * (3.0 - 2.0 * t)  # smoothstep, 1 at the edge
    return weights


def _bake_band_group(obj, band_mm):
    old = obj.vertex_groups.get(_BAND_GROUP)
    if old is not None:
        obj.vertex_groups.remove(old)
    weights = _edge_band_weights(obj, band_mm)
    if not weights:
        return None
    vg = obj.vertex_groups.new(name=_BAND_GROUP)
    for idx, w in weights.items():
        if w > 0.0:
            vg.add([idx], w, "REPLACE")
    return vg


def _vertex_group_members(obj, group_name):
    group = obj.vertex_groups.get(group_name)
    if group is None:
        return set()
    return {
        vertex.index
        for vertex in obj.data.vertices
        if any(
            membership.group == group.index and membership.weight > 0.01
            for membership in vertex.groups
        )
    }


def _ring_depths(bm, seed_indices, maximum_depth):
    depths = {index: 0 for index in seed_indices}
    frontier = [bm.verts[index] for index in seed_indices if index < len(bm.verts)]
    for depth in range(1, maximum_depth + 1):
        following = []
        for vertex in frontier:
            for edge in vertex.link_edges:
                neighbour = edge.other_vert(vertex)
                if neighbour.index not in depths:
                    depths[neighbour.index] = depth
                    following.append(neighbour)
        frontier = following
        if not frontier:
            break
    return depths


def _weights_from_rim(obj, rim_vertices, band_mm):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    lengths = [edge.calc_length() for edge in bm.edges]
    average_edge = sum(lengths) / len(lengths) if lengths else 0.01
    rings = max(1, round((band_mm * 0.001) / max(average_edge, 1.0e-6)))
    depths = _ring_depths(bm, rim_vertices, rings)
    bm.free()
    weights = {}
    for vertex_index, depth in depths.items():
        fraction = 1.0 - depth / rings
        weight = fraction * fraction * (3.0 - 2.0 * fraction)
        if weight > 0.0:
            weights[vertex_index] = weight
    return weights


def _bake_band_from_vertex_group(obj, source_group_name, band_mm):
    """Rebuild the finishing band on a closed paired shell from its rim marker."""
    rim_vertices = _vertex_group_members(obj, source_group_name)
    if not rim_vertices:
        return None
    old = obj.vertex_groups.get(_BAND_GROUP)
    if old is not None:
        obj.vertex_groups.remove(old)
    band = obj.vertex_groups.new(name=_BAND_GROUP)
    for vertex_index, weight in _weights_from_rim(
        obj, rim_vertices, band_mm
    ).items():
        band.add([vertex_index], weight, "REPLACE")
    return band


class RIGO_OT_toggle_seethrough(Operator):
    """See through the shell while checking the trim lines (X-ray shading)"""

    bl_idname = "rigo.toggle_seethrough"
    bl_label = "See-Through"

    def execute(self, context):
        done = False
        for area in context.screen.areas:
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.show_xray = not space.shading.show_xray
                    done = True
        if not done:
            self.report({"WARNING"}, "No 3D view found")
            return {"CANCELLED"}
        return {"FINISHED"}


def _band_vgroup(obj, band_mm):
    """Return the finishing band rebuilt from the paired shell's explicit rim."""
    vg = obj.vertex_groups.get(_BAND_GROUP)
    if vg is not None:
        return vg
    return _bake_band_group(obj, band_mm)  # Legacy open meshes still work.


def _band_weights_from_group(obj, vg):
    gi = vg.index
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi and g.weight > 0.0:
                out[v.index] = g.weight
                break
    return out


class RIGO_OT_smooth_trim_edge(Operator):
    """Relax the jagged cut edge of the shell (edge band only)"""

    bl_idname = "rigo.smooth_trim_edge"
    bl_label = "Smooth Trim Edge"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return brace_ready_for_finishing(context)

    def execute(self, context):
        corset = _corset()
        if corset is None:
            self.report({"ERROR"}, "Generate the corset first")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        settings = context.scene.rigo_brace

        vg = _band_vgroup(corset, settings.edge_band)
        if vg is None:
            self.report(
                {"ERROR"},
                "No edge band on this shell — press Generate again "
                "(the band is baked with the corset)",
            )
            return {"CANCELLED"}

        mod = corset.modifiers.new(name="Trim Smooth", type="CORRECTIVE_SMOOTH")
        mod.vertex_group = _BAND_GROUP
        mod.use_only_smooth = True
        mod.use_pin_boundary = False  # the boundary IS what we smooth
        mod.iterations = settings.trim_smooth_iters
        mod.factor = 1.0
        context.view_layer.objects.active = corset
        bpy.ops.object.modifier_apply(modifier=mod.name)

        self.report(
            {"INFO"},
            f"Trim edge relaxed ({settings.trim_smooth_iters} passes, "
            f"{settings.edge_band:.0f} mm band)",
        )
        return {"FINISHED"}


class RIGO_OT_flare_edge(Operator):
    """Bend the shell edge away from the body (safe edge, measured in mm)"""

    bl_idname = "rigo.flare_edge"
    bl_label = "Flare Edge"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return brace_ready_for_finishing(context)

    def execute(self, context):
        corset = _corset()
        if corset is None:
            self.report({"ERROR"}, "Generate the corset first")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        settings = context.scene.rigo_brace

        vg = _band_vgroup(corset, settings.edge_band)
        if vg is None:
            self.report(
                {"ERROR"},
                "No edge band on this shell — press Generate again "
                "(the band is baked with the corset)",
            )
            return {"CANCELLED"}
        weights = _band_weights_from_group(corset, vg)

        # Radially outward from the shell's vertical axis (XY centroid): the
        # edge lifts AWAY from the skin by flare_mm, feathered over the band.
        me = corset.data
        xs = [v.co.x for v in me.vertices]
        ys = [v.co.y for v in me.vertices]
        cx = (min(xs) + max(xs)) * 0.5
        cy = (min(ys) + max(ys)) * 0.5
        flare = settings.edge_flare * 0.001

        moved = 0
        for idx, w in weights.items():
            v = me.vertices[idx]
            radial = Vector((v.co.x - cx, v.co.y - cy, 0.0))
            if radial.length < 1e-9:
                continue
            radial.normalize()
            v.co += radial * flare * w
            moved += 1
        me.update()

        self.report(
            {"INFO"},
            f"Edge flared {settings.edge_flare:.1f} mm outward ({moved} verts)",
        )
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_toggle_seethrough,
    RIGO_OT_smooth_trim_edge,
    RIGO_OT_flare_edge,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
