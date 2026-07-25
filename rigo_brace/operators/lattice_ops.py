"""Lattice cage + multi-section derotation (Patch 5).

Ported and modernized from WASP-Med's waspmed_deform.py (GPL-2-or-later,
wasproject.it — see knowledge/code_provenance.md PROV-0008):
``wm_add_lattice_to_object`` / ``wm_edit_lattice`` / ``wm_rotate_sections``.

Two deliberate corrections over the original (DEC-0019):
- WASP rotated sections with ``transform.rotate`` and NO axis — that spins
  around the *view* axis, so the result depended on where the user was
  looking. We rotate around global Z through the lattice centre, in code.
- Rotating lattice points in local space while the lattice has a non-uniform
  scale (torso: X width != Y depth) SHEARS the body into an ellipse sweep.
  We compensate scale -> rotate -> unscale so the twist stays circular; the
  test asserts radial distance from the spine axis is preserved.

Clinical intent: scoliosis derotation — the pelvis stays anchored (section 1),
each higher slice rotates a little more, freeing the trunk twist. The gradient
dial gives the common case; the per-section dials (redo panel, F9) give double
curves their counter-rotation. Every press ADDS its angles (like WASP).
"""

from math import atan2, degrees, radians

import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector

_LATTICE_NAME = "Rigo Lattice"
_MODIFIER_NAME = "Rigo Lattice"


def _scan(context):
    settings = context.scene.rigo_brace
    obj = settings.scan_object or context.active_object
    if obj is None or obj.type != "MESH":
        return None
    return obj


def _lattice():
    obj = bpy.data.objects.get(_LATTICE_NAME)
    if obj is not None and obj.type == "LATTICE":
        return obj
    return None


def _world_bounds(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(c.x for c in corners), min(c.y for c in corners),
                   min(c.z for c in corners)))
    maxs = Vector((max(c.x for c in corners), max(c.y for c in corners),
                   max(c.z for c in corners)))
    return mins, maxs


def _remove_lattice(scan):
    if scan is not None:
        mod = scan.modifiers.get(_MODIFIER_NAME)
        if mod is not None:
            scan.modifiers.remove(mod)
    lat = _lattice()
    if lat is not None:
        data = lat.data
        bpy.data.objects.remove(lat, do_unlink=True)
        if data.users == 0:
            bpy.data.lattices.remove(data)


class RIGO_OT_lattice_add(Operator):
    """Wrap the scan in a section cage for derotation"""

    bl_idname = "rigo.lattice_add"
    bl_label = "Add Lattice Cage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _scan(context) is not None

    def execute(self, context):
        scan = _scan(context)
        if scan is None:
            self.report({"ERROR"}, "Import and prepare a scan first")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        settings = context.scene.rigo_brace

        _remove_lattice(scan)  # always start clean (WASP behaviour)

        mins, maxs = _world_bounds(scan)
        center = (mins + maxs) * 0.5
        size = maxs - mins

        data = bpy.data.lattices.new(_LATTICE_NAME)
        data.points_u = 3
        data.points_v = 3
        data.points_w = settings.lattice_sections
        data.use_outside = True
        # LINEAR, not the default B-spline: B-spline does not pass through the
        # section values, so a 0->30° dial gradient would smear into ~11->18°.
        # Linear means each slice rotates exactly what its dial says.
        data.interpolation_type_u = "KEY_LINEAR"
        data.interpolation_type_v = "KEY_LINEAR"
        data.interpolation_type_w = "KEY_LINEAR"

        lat = bpy.data.objects.new(_LATTICE_NAME, data)
        lat.location = center
        # Lattice rest points sit at spacing 1.0, centred — the rest span is
        # (points-1) units per axis, NOT 1.0 (verified empirically: 3 pts ->
        # ±1, 5 pts -> ±2). Divide by the span so the cage hugs the scan with
        # a 5% margin; sizing by raw scale left the body in the middle cells
        # only, which crushed the section gradient.
        lat.scale = (
            max(size.x, 1e-4) * 1.05 / max(data.points_u - 1, 1),
            max(size.y, 1e-4) * 1.05 / max(data.points_v - 1, 1),
            max(size.z, 1e-4) * 1.05 / max(data.points_w - 1, 1),
        )
        context.scene.collection.objects.link(lat)

        mod = scan.modifiers.new(name=_MODIFIER_NAME, type="LATTICE")
        mod.object = lat

        context.view_layer.objects.active = lat
        self.report(
            {"INFO"},
            f"Cage added — {settings.lattice_sections} sections. "
            "Twist below, or Edit to drag points by hand",
        )
        return {"FINISHED"}


class RIGO_OT_lattice_edit(Operator):
    """Enter/leave hand-editing of the cage points"""

    bl_idname = "rigo.lattice_edit"
    bl_label = "Edit Cage Points"

    @classmethod
    def poll(cls, context):
        return _lattice() is not None

    def execute(self, context):
        lat = _lattice()
        if lat is None:
            self.report({"ERROR"}, "Add the lattice cage first")
            return {"CANCELLED"}
        if context.mode == "EDIT_LATTICE":
            bpy.ops.object.mode_set(mode="OBJECT")
            return {"FINISHED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        lat.hide_set(False)
        lat.select_set(True)
        context.view_layer.objects.active = lat
        bpy.ops.object.mode_set(mode="EDIT")
        self.report({"INFO"}, "Drag cage points — the body follows live")
        return {"FINISHED"}


class RIGO_OT_lattice_twist(Operator):
    """Derotate: rotate each horizontal section around the spine axis.

    Invoked from the button it seeds a 0→total gradient (pelvis anchored);
    fine-tune each section in the redo panel (F9). Every press adds on top.
    """

    bl_idname = "rigo.lattice_twist"
    bl_label = "Twist Sections"
    bl_options = {"REGISTER", "UNDO"}

    r0: bpy.props.FloatProperty(name="Section 1 (bottom)", default=0.0, soft_min=-180, soft_max=180)
    r1: bpy.props.FloatProperty(name="Section 2", default=0.0, soft_min=-180, soft_max=180)
    r2: bpy.props.FloatProperty(name="Section 3", default=0.0, soft_min=-180, soft_max=180)
    r3: bpy.props.FloatProperty(name="Section 4", default=0.0, soft_min=-180, soft_max=180)
    r4: bpy.props.FloatProperty(name="Section 5", default=0.0, soft_min=-180, soft_max=180)
    r5: bpy.props.FloatProperty(name="Section 6", default=0.0, soft_min=-180, soft_max=180)
    r6: bpy.props.FloatProperty(name="Section 7", default=0.0, soft_min=-180, soft_max=180)
    r7: bpy.props.FloatProperty(name="Section 8", default=0.0, soft_min=-180, soft_max=180)
    r8: bpy.props.FloatProperty(name="Section 9", default=0.0, soft_min=-180, soft_max=180)
    r9: bpy.props.FloatProperty(name="Section 10 (top)", default=0.0, soft_min=-180, soft_max=180)

    @classmethod
    def poll(cls, context):
        return _lattice() is not None

    def draw(self, context):
        col = self.layout.column(align=True)
        lat = _lattice()
        n = min(lat.data.points_w if lat else 10, 10)
        for i in range(n):
            col.prop(self, f"r{i}")

    def invoke(self, context, event):
        # Seed a linear gradient: 0 at the pelvis -> lattice_twist at the top.
        lat = _lattice()
        if lat is None:
            self.report({"ERROR"}, "Add the lattice cage first")
            return {"CANCELLED"}
        total = context.scene.rigo_brace.lattice_twist
        nw = lat.data.points_w
        for i in range(min(nw, 10)):
            setattr(self, f"r{i}", total * (i / max(nw - 1, 1)))
        return self.execute(context)

    def execute(self, context):
        lat = _lattice()
        if lat is None:
            self.report({"ERROR"}, "Add the lattice cage first")
            return {"CANCELLED"}
        data = lat.data
        nu, nv, nw = data.points_u, data.points_v, data.points_w
        angles = [getattr(self, f"r{i}") for i in range(10)]
        scale = lat.scale

        for w in range(nw):
            ang = radians(angles[min(w, 9)])
            if abs(ang) < 1e-9:
                continue
            rot = Matrix.Rotation(ang, 4, "Z")
            for v in range(nv):
                for u in range(nu):
                    p = data.points[w * nu * nv + v * nu + u]
                    # Scale-compensated rotation: lattice local space is
                    # non-uniformly scaled (width != depth) — rotating raw
                    # co_deform would shear the body. Uncompress, rotate,
                    # recompress so the twist is circular in world space.
                    co = p.co_deform
                    world = Vector((co.x * scale.x, co.y * scale.y, co.z * scale.z))
                    world = rot @ world
                    p.co_deform = Vector(
                        (world.x / scale.x, world.y / scale.y, world.z / scale.z)
                    )

        data.update_tag()
        context.view_layer.update()
        top = angles[min(nw - 1, 9)]
        self.report({"INFO"}, f"Twisted {nw} sections — top {top:.1f}°")
        return {"FINISHED"}


class RIGO_OT_lattice_apply(Operator):
    """Bake the cage deformation into the scan and remove the cage"""

    bl_idname = "rigo.lattice_apply"
    bl_label = "Apply Cage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _lattice() is not None

    def execute(self, context):
        scan = _scan(context)
        if scan is None or scan.modifiers.get(_MODIFIER_NAME) is None:
            self.report({"ERROR"}, "No lattice cage on the scan")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        context.view_layer.objects.active = scan
        bpy.ops.object.modifier_apply(modifier=_MODIFIER_NAME)
        _remove_lattice(scan)
        self.report({"INFO"}, "Derotation baked in")
        return {"FINISHED"}


class RIGO_OT_lattice_discard(Operator):
    """Remove the cage without changing the scan"""

    bl_idname = "rigo.lattice_discard"
    bl_label = "Discard Cage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _lattice() is not None

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        _remove_lattice(_scan(context))
        self.report({"INFO"}, "Cage discarded — scan unchanged")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_lattice_add,
    RIGO_OT_lattice_edit,
    RIGO_OT_lattice_twist,
    RIGO_OT_lattice_apply,
    RIGO_OT_lattice_discard,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
