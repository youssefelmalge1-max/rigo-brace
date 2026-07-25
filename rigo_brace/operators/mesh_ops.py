"""Core mesh shaping operators: remesh, smooth, thickness.

Each operator works on the active mesh object, applies a modifier so the result
is permanent, and is fully undoable. Values come from Scene.rigo_brace so the
orthotist only ever touches sliders in the side panel.

Note on units: the panel labels say "mm" for clarity to the user. The numbers
are fed to Blender directly, so set your scene unit scale so 1 unit = 1 mm if
you want the labels to match exactly. This is handled in a later phase.
"""

import bpy
import bmesh
from bpy.types import Operator

from ..core import mark_brace_dirty


def _active_mesh(context):
    """Return the active mesh object or None, ensuring we are in OBJECT mode."""
    obj = context.active_object
    if obj is None or obj.type != "MESH":
        return None
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def _apply_modifier(obj, modifier):
    """Apply a modifier on obj by name, making it the active object first."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def _configure_exoside(settings, exoside):
    """Map the Rigo organic-scan preset onto Exoside's scene settings."""
    exoside.target_count = settings.quad_target_faces
    exoside.adaptive_size = settings.quad_adaptive_size
    exoside.adapt_quad_count = False
    exoside.use_vertex_color = False
    exoside.use_materials = False
    exoside.use_normals = False
    exoside.autodetect_hard_edges = False
    exoside.symmetry_x = False
    exoside.symmetry_y = False
    exoside.symmetry_z = False
    exoside.hide_input = True


def _select_exoside_input(context, scan):
    bpy.ops.object.select_all(action="DESELECT")
    scan.hide_set(False)
    scan.hide_viewport = False
    scan.select_set(True)
    context.view_layer.objects.active = scan


class RIGO_OT_remesh(Operator):
    """Rebuild the scan with clean, even topology (voxel remesh)"""

    bl_idname = "rigo.remesh"
    bl_label = "Remesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}

        settings = context.scene.rigo_brace
        mod = obj.modifiers.new(name="Rigo Remesh", type="REMESH")
        mod.mode = "VOXEL"
        # Panel value is in mm; convert to metres-style scene units (x0.001).
        mod.voxel_size = settings.remesh_voxel * 0.001
        _apply_modifier(obj, mod)
        self.report({"INFO"}, "Remesh complete")
        return {"FINISHED"}


class RIGO_OT_quad_remesh(Operator):
    """Rebuild the scan as flow-following quads with the selected engine"""

    bl_idname = "rigo.quad_remesh"
    bl_label = "Quad Remesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scan = _active_mesh(context)
        if scan is None:
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}

        settings = context.scene.rigo_brace
        if settings.quad_remesh_engine == "EXOSIDE":
            return self._start_exoside(context, scan, settings)
        return self._run_quadriflow(context, scan, settings)

    def _start_exoside(self, context, scan, settings):
        if not hasattr(bpy.types, "QREMESHER_OT_remesh"):
            self.report(
                {"ERROR"},
                "Exoside bridge is not enabled; run install.ps1 and restart Blender",
            )
            return {"CANCELLED"}

        _configure_exoside(settings, context.scene.qremesher)
        _select_exoside_input(context, scan)
        bpy.ops.qremesher.remesh("INVOKE_DEFAULT")
        self.report(
            {"INFO"},
            "Quad Remesher started; adopt its new mesh when processing finishes",
        )
        return {"FINISHED"}

    def _run_quadriflow(self, context, scan, settings):
        bm = bmesh.new()
        bm.from_mesh(scan.data)
        boundary = sum(1 for edge in bm.edges if edge.is_boundary)
        nonmanifold = sum(1 for edge in bm.edges if not edge.is_manifold)
        bm.free()
        if boundary or nonmanifold:
            self.report(
                {"ERROR"},
                f"Mesh has {boundary} hole edge(s) / {nonmanifold} non-manifold "
                "edge(s) — run Fill Holes or Auto-Remesh first",
            )
            return {"CANCELLED"}

        context.view_layer.objects.active = scan
        bpy.ops.object.quadriflow_remesh(
            mode="FACES",
            target_faces=settings.quad_target_faces,
            use_mesh_symmetry=False,
        )
        quads = sum(1 for polygon in scan.data.polygons if len(polygon.vertices) == 4)
        self.report(
            {"INFO"},
            f"Quad remesh complete — {len(scan.data.polygons)} faces ({quads} quads)",
        )
        return {"FINISHED"}


class RIGO_OT_use_quad_remesh_result(Operator):
    """Make the active Exoside output the patient scan used by Rigo"""

    bl_idname = "rigo.use_quad_remesh_result"
    bl_label = "Use Remeshed Result"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        active = context.active_object
        return active is not None and active.type == "MESH"

    def execute(self, context):
        settings = context.scene.rigo_brace
        remeshed_scan = context.active_object
        source_scan = settings.scan_object
        if remeshed_scan == source_scan:
            self.report({"ERROR"}, "Select the new Quad Remesher output first")
            return {"CANCELLED"}

        if source_scan is not None:
            source_scan.name = "Patient Scan Before Quad Remesh"
            source_scan.hide_set(True)
            source_scan.hide_viewport = True
            source_scan.hide_render = True
        remeshed_scan.name = "Patient Scan"
        remeshed_scan.hide_set(False)
        remeshed_scan.hide_viewport = False
        remeshed_scan.hide_render = False
        settings.scan_object = remeshed_scan

        mark_brace_dirty(context, "Patient scan was replaced by Quad Remesher output")
        self.report({"INFO"}, "Remeshed mesh is now the active patient scan")
        return {"FINISHED"}


class RIGO_OT_smooth(Operator):
    """Relax the surface to remove scan noise and bumps"""

    bl_idname = "rigo.smooth"
    bl_label = "Smooth"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}

        settings = context.scene.rigo_brace
        mod = obj.modifiers.new(name="Rigo Smooth", type="SMOOTH")
        mod.iterations = settings.smooth_iterations
        mod.factor = settings.smooth_factor
        _apply_modifier(obj, mod)
        self.report({"INFO"}, "Smoothing complete")
        return {"FINISHED"}


class RIGO_OT_thickness(Operator):
    """Give the brace a solid wall thickness (shell)"""

    bl_idname = "rigo.thickness"
    bl_label = "Add Thickness"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "Select the brace mesh first")
            return {"CANCELLED"}

        settings = context.scene.rigo_brace
        mod = obj.modifiers.new(name="Rigo Thickness", type="SOLIDIFY")
        mod.thickness = settings.shell_thickness * 0.001
        mod.offset = 1.0  # grow outward, keep the inner (body-facing) surface
        _apply_modifier(obj, mod)
        self.report({"INFO"}, "Thickness applied")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_remesh,
    RIGO_OT_quad_remesh,
    RIGO_OT_use_quad_remesh_result,
    RIGO_OT_smooth,
    RIGO_OT_thickness,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
