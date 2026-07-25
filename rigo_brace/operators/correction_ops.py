"""Free-form curve correction using a Lattice cage (FFD).

This is the digital equivalent of the corrective mould: a cage of control points
wraps the scan, and moving those points bends/derotates the body shape to apply
the scoliosis correction. It maps directly to the free-form deformation used by
commercial systems (Rodin4D, Orten) and the published Blender brace research.

Workflow for the orthotist:
    1. Build Cage   -> a lattice is fitted around the scan and linked to it.
    2. Edit Cage    -> grab control points to push the apex, derotate, relieve.
    3. Apply        -> bakes the correction into the mesh and removes the cage.
       Reset        -> throws the correction away (cage + modifier removed).
"""

import bpy
from bpy.types import Operator
from mathutils import Vector

# Names used so we can find our own cage/modifier reliably.
CORRECTION_COLLECTION = "Rigo Correction"
CORRECTION_MODIFIER = "Rigo Correction"
CORRECTION_LATTICE_NAME = "Rigo Correction Cage"

# Extra room left around the scan so the cage fully encloses it.
_CAGE_MARGIN = 1.05


def _world_bounds(obj):
    """Return (center, size) Vectors of obj's world-space bounding box."""
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(c[i] for c in corners) for i in range(3)))
    maxs = Vector((max(c[i] for c in corners) for i in range(3)))
    center = (mins + maxs) * 0.5
    size = maxs - mins
    return center, size


def _get_correction_collection(context):
    coll = bpy.data.collections.get(CORRECTION_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(CORRECTION_COLLECTION)
        context.scene.collection.children.link(coll)
    return coll


class RIGO_OT_build_correction_cage(Operator):
    """Fit a free-form correction cage around the scan"""

    bl_idname = "rigo.build_correction_cage"
    bl_label = "Build Correction Cage"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        settings = context.scene.rigo_brace

        # Remove any previous cage so we always start clean.
        self._remove_existing(context, obj)

        lattice_data = bpy.data.lattices.new(CORRECTION_LATTICE_NAME)
        lattice_data.points_u = settings.correction_div_width
        lattice_data.points_v = settings.correction_div_depth
        lattice_data.points_w = settings.correction_div_height
        lattice_data.interpolation_type_u = "KEY_BSPLINE"
        lattice_data.interpolation_type_v = "KEY_BSPLINE"
        lattice_data.interpolation_type_w = "KEY_BSPLINE"

        lattice_obj = bpy.data.objects.new(CORRECTION_LATTICE_NAME, lattice_data)

        center, size = _world_bounds(obj)
        # Avoid zero scale on flat axes.
        safe_size = Vector((max(size[i], 0.001) for i in range(3))) * _CAGE_MARGIN
        lattice_obj.location = center
        lattice_obj.scale = safe_size

        _get_correction_collection(context).objects.link(lattice_obj)

        mod = obj.modifiers.new(name=CORRECTION_MODIFIER, type="LATTICE")
        mod.object = lattice_obj

        settings.correction_lattice = lattice_obj
        self.report({"INFO"}, "Correction cage built — now Edit Cage")
        return {"FINISHED"}

    @staticmethod
    def _remove_existing(context, obj):
        old_mod = obj.modifiers.get(CORRECTION_MODIFIER)
        if old_mod is not None:
            obj.modifiers.remove(old_mod)
        old_lat = bpy.data.objects.get(CORRECTION_LATTICE_NAME)
        if old_lat is not None:
            bpy.data.objects.remove(old_lat, do_unlink=True)


class RIGO_OT_edit_correction_cage(Operator):
    """Jump into the correction cage to move its control points"""

    bl_idname = "rigo.edit_correction_cage"
    bl_label = "Edit Cage"
    bl_options = {"REGISTER"}

    def execute(self, context):
        lattice = context.scene.rigo_brace.correction_lattice
        if lattice is None:
            self.report({"ERROR"}, "Build the correction cage first")
            return {"CANCELLED"}

        if context.active_object is not None and context.active_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.select_all(action="DESELECT")
        lattice.select_set(True)
        context.view_layer.objects.active = lattice
        bpy.ops.object.mode_set(mode="EDIT")
        self.report({"INFO"}, "Grab points (G) to apply the correction")
        return {"FINISHED"}


class RIGO_OT_apply_correction(Operator):
    """Bake the correction into the scan and remove the cage"""

    bl_idname = "rigo.apply_correction"
    bl_label = "Apply Correction"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.rigo_brace
        lattice = settings.correction_lattice
        scan = settings.scan_object or context.active_object

        if scan is None or scan.type != "MESH":
            self.report({"ERROR"}, "No scan mesh to apply the correction to")
            return {"CANCELLED"}

        mod = scan.modifiers.get(CORRECTION_MODIFIER)
        if mod is None:
            self.report({"ERROR"}, "No correction cage is active")
            return {"CANCELLED"}

        if context.active_object is not None and context.active_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.select_all(action="DESELECT")
        scan.select_set(True)
        context.view_layer.objects.active = scan
        bpy.ops.object.modifier_apply(modifier=CORRECTION_MODIFIER)

        if lattice is not None:
            bpy.data.objects.remove(lattice, do_unlink=True)
        settings.correction_lattice = None
        self.report({"INFO"}, "Correction baked into the scan")
        return {"FINISHED"}


class RIGO_OT_reset_correction(Operator):
    """Discard the correction cage without applying it"""

    bl_idname = "rigo.reset_correction"
    bl_label = "Reset Correction"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.rigo_brace
        scan = settings.scan_object or context.active_object

        if context.active_object is not None and context.active_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        if scan is not None and scan.type == "MESH":
            mod = scan.modifiers.get(CORRECTION_MODIFIER)
            if mod is not None:
                scan.modifiers.remove(mod)

        lattice = settings.correction_lattice or bpy.data.objects.get(
            CORRECTION_LATTICE_NAME
        )
        if lattice is not None:
            bpy.data.objects.remove(lattice, do_unlink=True)
        settings.correction_lattice = None
        self.report({"INFO"}, "Correction discarded")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_build_correction_cage,
    RIGO_OT_edit_correction_cage,
    RIGO_OT_apply_correction,
    RIGO_OT_reset_correction,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
