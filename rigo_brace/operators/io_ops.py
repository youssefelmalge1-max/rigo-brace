"""Import / export operators."""

import os

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from ..core import CORSET_NAME, mark_brace_dirty
from .qa_ops import evaluate_brace_qa, store_qa_result


_PATIENT_TRIM_OBJECTS = (
    "Rigo Trim Top",
    "Rigo Trim Bottom",
    "Rigo Trim Perimeter",
)


def _remove_patient_trimlines():
    """Discard trim geometry that belongs to the previously loaded patient."""
    for name in _PATIENT_TRIM_OBJECTS:
        trimline = bpy.data.objects.get(name)
        if trimline is None:
            continue
        curve = trimline.data if trimline.type == "CURVE" else None
        bpy.data.objects.remove(trimline, do_unlink=True)
        if curve is not None and curve.users == 0:
            bpy.data.curves.remove(curve)


class RIGO_OT_import_scan(Operator, ImportHelper):
    """Import a patient body scan (STL or OBJ) and set it as the working object"""

    bl_idname = "rigo.import_scan"
    bl_label = "Import Scan"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.stl;*.obj", options={"HIDDEN"})
    file_format: EnumProperty(
        items=(
            ("STL", "STL", "Import an STL patient scan"),
            ("OBJ", "OBJ", "Import an OBJ patient scan"),
        ),
        default="STL",
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        self.filter_glob = "*.stl" if self.file_format == "STL" else "*.obj"
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        path = self.filepath
        ext = os.path.splitext(path)[1].lower()
        expected_ext = ".stl" if self.file_format == "STL" else ".obj"
        if ext != expected_ext:
            self.report({"ERROR"}, f"Choose a {expected_ext.upper()} file")
            return {"CANCELLED"}

        existing = set(bpy.data.objects)

        if ext == ".stl":
            bpy.ops.wm.stl_import(filepath=path)
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=path)
        new_objects = [o for o in bpy.data.objects if o not in existing]
        mesh_objects = [o for o in new_objects if o.type == "MESH"]
        if not mesh_objects:
            self.report({"ERROR"}, "No mesh was found in that file")
            return {"CANCELLED"}

        scan = mesh_objects[0]
        scan.name = "Patient Scan"

        # Make it the one and only active selection so the next steps target it.
        bpy.ops.object.select_all(action="DESELECT")
        scan.select_set(True)
        context.view_layer.objects.active = scan

        context.scene.rigo_brace.scan_object = scan
        _remove_patient_trimlines()
        mark_brace_dirty(context, "A different patient scan was imported")
        from .design_ops import _set_design_view

        _set_design_view(context, "TRIM")
        self.report({"INFO"}, f"Imported scan: {scan.name}")
        return {"FINISHED"}


class RIGO_OT_export_brace(Operator, ExportHelper):
    """Save the generated brace, and only the brace, as an STL file"""

    bl_idname = "rigo.export_brace"
    bl_label = "Export Brace (STL)"
    bl_options = {"REGISTER"}

    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={"HIDDEN"})

    def execute(self, context):
        brace = bpy.data.objects.get(CORSET_NAME)
        if brace is None or brace.type != "MESH":
            self.report({"ERROR"}, "Generate the brace in Step 5 before exporting")
            return {"CANCELLED"}

        # Export is the manufacturing boundary. Always re-run QA here rather
        # than trusting a green result from before the last edit or boolean.
        qa_result = evaluate_brace_qa(context, brace)
        store_qa_result(brace, qa_result)
        if not qa_result["passed"]:
            self.report({"ERROR"}, f"Export blocked: {qa_result['reasons'][0]}")
            return {"CANCELLED"}

        filepath = bpy.path.abspath(bpy.path.ensure_ext(self.filepath, self.filename_ext))
        folder = os.path.dirname(filepath)
        if not filepath or not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, "Choose an existing folder for the STL file")
            return {"CANCELLED"}

        # STL export uses selection, so isolate the named final brace.  The scan,
        # trim curves, rings and other helpers must never leak into the file.
        previous_active = context.view_layer.objects.active
        previous_selection = [obj for obj in context.selected_objects]
        previous_mode = context.object.mode if context.object is not None else "OBJECT"
        brace_was_hidden = brace.hide_get()
        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        brace.hide_set(False)
        brace.select_set(True)
        context.view_layer.objects.active = brace

        try:
            result = bpy.ops.wm.stl_export(
                filepath=filepath,
                export_selected_objects=True,
            )
        finally:
            brace.hide_set(brace_was_hidden)
            bpy.ops.object.select_all(action="DESELECT")
            for obj in previous_selection:
                if obj.name in context.view_layer.objects:
                    obj.select_set(True)
            if previous_active is not None and previous_active.name in context.view_layer.objects:
                context.view_layer.objects.active = previous_active
                if previous_mode != "OBJECT":
                    bpy.ops.object.mode_set(mode=previous_mode)

        if result != {"FINISHED"} or not os.path.isfile(filepath) or os.path.getsize(filepath) == 0:
            self.report({"ERROR"}, "Blender did not create a valid STL file")
            return {"CANCELLED"}

        context.scene.rigo_brace.export_path = folder
        self.report({"INFO"}, f"Exported: {filepath}")
        return {"FINISHED"}


_CLASSES = (RIGO_OT_import_scan, RIGO_OT_export_brace)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
