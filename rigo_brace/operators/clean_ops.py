"""Clean stage: center the model and verify the cleanup before closing the mesh.

Auto-Remesh, Fill Holes, Smooth and Box-Erase already live in mesh_ops/scan_ops;
this module adds the two pieces the Clean stage was missing:

    Center Model   -> drop the scan onto the world origin so it's easy to work on
                      (WASP auto_origin idea; distinct from Align's drop-to-floor).
    Verify Clean   -> highlight likely problems (non-manifold edges, holes/boundary,
                      loose verts) so the orthotist checks before committing
                      (uFit "Verify Clean Up" / WASP check-differences idea, clean
                      reimplementation — see knowledge/code_provenance.md PROV-0007).
"""

import bmesh
import bpy
from bpy.types import Operator


def _active_mesh(context):
    """The mesh to clean: the registered scan, else the active mesh (OBJECT mode)."""
    settings = context.scene.rigo_brace
    obj = settings.scan_object
    if obj is None or obj.type != "MESH":
        obj = context.active_object
    if obj is None or obj.type != "MESH":
        return None
    context.view_layer.objects.active = obj
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    return obj


class RIGO_OT_center_model(Operator):
    """Center the scan on the world origin so it is easy to work on"""

    bl_idname = "rigo.center_model"
    bl_label = "Center Model"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}
        # Origin to the geometry's bounding-box centre, then sit that on (0,0,0).
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
        obj.location = (0.0, 0.0, 0.0)
        self.report({"INFO"}, "Model centered on the origin")
        return {"FINISHED"}


class RIGO_OT_verify_clean(Operator):
    """Highlight likely problems (holes, non-manifold edges, loose verts) so you
    can check the scan before closing the mesh"""

    bl_idname = "rigo.verify_clean"
    bl_label = "Verify Clean-up"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = _active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}

        # Count first (object-mode bmesh snapshot).
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
        boundary = sum(1 for e in bm.edges if e.is_boundary)
        loose = sum(1 for v in bm.verts if not v.link_edges)
        bm.free()

        # Stash for the panel + tests.
        obj["rigo_nonmanifold"] = non_manifold
        obj["rigo_boundary"] = boundary
        obj["rigo_loose"] = loose
        clean = (non_manifold == 0 and boundary == 0 and loose == 0)
        obj["rigo_verify_ok"] = clean

        # Highlight the problems in Edit Mode so the user can see them.
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="EDGE")
        bpy.ops.mesh.select_all(action="DESELECT")
        try:
            bpy.ops.mesh.select_non_manifold()
        except RuntimeError:
            pass

        if clean:
            self.report({"INFO"}, "Looks clean — no holes or non-manifold edges")
        else:
            self.report(
                {"WARNING"},
                f"Holes/boundary: {boundary}  •  Non-manifold: {non_manifold}  "
                f"•  Loose: {loose} (highlighted)",
            )
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_center_model,
    RIGO_OT_verify_clean,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
