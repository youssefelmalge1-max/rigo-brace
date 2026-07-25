"""Parametric ventilation — a measured hole grid over a painted region
(Patch 7).

The orthotist paints the ventilation zone on the corset (the same Edit-Mode
face selection every region tool uses), sets hole Ø and spacing in mm, and one
button cuts a regular grid of through-holes. Inspired by WASP-Med's
hand-painted holes but parametric per the user's standing "measurable, not
hand-painted" rule (DEC-0014); clean original implementation.

Safety gates baked in:
- bridge width (spacing − Ø) must stay ≥ 3 mm or the print bridges snap
  (knowledge/manufacturing_constraints.md) — the operator refuses;
- grid points falling inside the trim-edge band (RIGO_TRIM_BAND) are skipped
  so holes can never break the shell rim.
"""

from math import ceil

import bpy
import bmesh
from bpy.types import Operator
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from ..core import CORSET_NAME, brace_ready_for_finishing

_MIN_BRIDGE_MM = 3.0
_MAX_HOLES = 400
_CUTTER_NAME = "Rigo Vent Cutter"


def _corset():
    obj = bpy.data.objects.get(CORSET_NAME)
    if obj is not None and obj.type == "MESH":
        return obj
    return None


def _band_weight_lookup(obj):
    vg = obj.vertex_groups.get("RIGO_TRIM_BAND")
    if vg is None:
        return {}
    gi = vg.index
    out = {}
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi and g.weight > 0.0:
                out[v.index] = g.weight
                break
    return out


class RIGO_OT_vent_paint(Operator):
    """Paint the ventilation area on the corset"""

    bl_idname = "rigo.vent_paint"
    bl_label = "Paint Area On Corset"

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
        bpy.ops.object.select_all(action="DESELECT")
        corset.hide_set(False)
        corset.select_set(True)
        context.view_layer.objects.active = corset
        return bpy.ops.rigo.paint_select()


class RIGO_OT_vent_grid(Operator):
    """Cut a measured grid of ventilation holes into the painted area"""

    bl_idname = "rigo.vent_grid"
    bl_label = "Cut Ventilation Grid"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return brace_ready_for_finishing(context)

    def execute(self, context):
        corset = _corset()
        if corset is None:
            self.report({"ERROR"}, "Generate the corset first")
            return {"CANCELLED"}
        settings = context.scene.rigo_brace

        dia = settings.vent_diameter * 0.001
        gap = settings.vent_spacing * 0.001
        bridge_mm = settings.vent_spacing - settings.vent_diameter
        if bridge_mm < _MIN_BRIDGE_MM:
            self.report(
                {"ERROR"},
                f"Bridge between holes would be {bridge_mm:.1f} mm — "
                f"keep spacing − Ø at least {_MIN_BRIDGE_MM:.0f} mm to print safely",
            )
            return {"CANCELLED"}

        # The painted region: live Edit-Mode face selection on the corset.
        if context.mode != "EDIT_MESH" or context.active_object is not corset:
            self.report(
                {"ERROR"},
                "Paint the ventilation area on the corset first (Paint Area)",
            )
            return {"CANCELLED"}
        bm = bmesh.from_edit_mesh(corset.data)
        bm.faces.ensure_lookup_table()
        sel_faces = {f.index for f in bm.faces if f.select}
        sel_verts = [v.co.copy() for v in bm.verts if v.select]
        if not sel_faces:
            self.report({"ERROR"}, "Paint the ventilation area first")
            return {"CANCELLED"}

        normal = Vector()
        for f in bm.faces:
            if f.select:
                normal += f.normal
        if normal.length < 1e-9:
            self.report({"ERROR"}, "Could not read the area's direction")
            return {"CANCELLED"}
        normal.normalize()
        bpy.ops.object.mode_set(mode="OBJECT")

        # Tangent basis of the region plane; grid the projected bounds.
        t1 = normal.cross(Vector((0.0, 0.0, 1.0)))
        if t1.length < 1e-6:
            t1 = normal.cross(Vector((0.0, 1.0, 0.0)))
        t1.normalize()
        t2 = normal.cross(t1)
        center = sum(sel_verts, Vector()) / len(sel_verts)
        us = [(co - center).dot(t1) for co in sel_verts]
        vs = [(co - center).dot(t2) for co in sel_verts]

        bvh = BVHTree.FromObject(
            corset, context.evaluated_depsgraph_get()
        )
        band = _band_weight_lookup(corset)
        me = corset.data

        holes = []
        nu = int(ceil((max(us) - min(us)) / gap)) + 1
        nv = int(ceil((max(vs) - min(vs)) / gap)) + 1
        if nu * nv > 20000:
            self.report({"ERROR"}, "Area too large for this spacing")
            return {"CANCELLED"}
        for i in range(nu):
            for j in range(nv):
                u = min(us) + i * gap
                v = min(vs) + j * gap
                origin = center + t1 * u + t2 * v + normal * 0.25
                loc, nrm, fidx, _d = bvh.ray_cast(origin, -normal, 0.5)
                if loc is None or fidx is None:
                    continue
                if fidx not in sel_faces:
                    continue
                # Never hole the trim rim: skip if the hit face touches the band.
                if band and any(
                    band.get(vi, 0.0) > 0.0 for vi in me.polygons[fidx].vertices
                ):
                    continue
                holes.append((loc, nrm))
                if len(holes) > _MAX_HOLES:
                    self.report(
                        {"ERROR"},
                        f"More than {_MAX_HOLES} holes — increase the spacing",
                    )
                    return {"CANCELLED"}

        if not holes:
            self.report({"ERROR"}, "No grid point landed on the painted area")
            return {"CANCELLED"}

        # One cutter mesh with every hole cylinder, single boolean difference.
        cut_bm = bmesh.new()
        for loc, nrm in holes:
            quat = nrm.to_track_quat("Z", "Y")
            mat = Matrix.Translation(loc) @ quat.to_matrix().to_4x4()
            bmesh.ops.create_cone(
                cut_bm,
                cap_ends=True,
                segments=16,
                radius1=dia * 0.5,
                radius2=dia * 0.5,
                depth=0.06,  # ±30 mm along the surface normal: pierces both walls
                matrix=mat,
            )
        cut_me = bpy.data.meshes.new(_CUTTER_NAME)
        cut_bm.to_mesh(cut_me)
        cut_bm.free()
        cutter = bpy.data.objects.new(_CUTTER_NAME, cut_me)
        cutter.matrix_world = corset.matrix_world.copy()
        context.scene.collection.objects.link(cutter)

        mod = corset.modifiers.new(name="Ventilation", type="BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.solver = "EXACT"
        try:
            # Blender's newer solver guarantees manifold output for manifold
            # inputs — exactly what a printable shell needs.
            mod.solver = "MANIFOLD"
        except TypeError:
            pass
        mod.object = cutter
        context.view_layer.objects.active = corset
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(cutter, do_unlink=True)
        if cut_me.users == 0:
            bpy.data.meshes.remove(cut_me)

        # Post-boolean hygiene: grazing intersections can leave micro-slivers
        # (seen as single non-manifold edges). Merge + dissolve at 1 µm.
        bm2 = bmesh.new()
        bm2.from_mesh(corset.data)
        bmesh.ops.remove_doubles(bm2, verts=bm2.verts[:], dist=1e-6)
        bmesh.ops.dissolve_degenerate(bm2, edges=bm2.edges[:], dist=1e-6)
        bad = sum(1 for e in bm2.edges if not e.is_manifold)
        bm2.to_mesh(corset.data)
        bm2.free()
        corset.data.update()
        if bad:
            self.report(
                {"WARNING"},
                f"{bad} non-manifold edge(s) remain — run Verify Clean-up",
            )

        self.report(
            {"INFO"},
            f"Cut {len(holes)} holes — Ø {settings.vent_diameter:.1f} mm, "
            f"bridge {bridge_mm:.1f} mm",
        )
        return {"FINISHED"}


_CLASSES = (RIGO_OT_vent_paint, RIGO_OT_vent_grid)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
