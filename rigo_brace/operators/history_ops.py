"""Legacy single-mesh checkpoint operators, retained for migration only.

Ported and modernized (Blender 2.91 -> 5.0) from WASP-Med's wm_next / wm_back
(waspmed_scan.py, GPL-2-or-later; see knowledge/code_provenance.md PROV-0005).

Each major brace stage is saved as a frozen version object named
``NN_<patient>_<STAGE>`` inside a per-patient collection.  Moving to the next
stage duplicates the current work into a new version and freezes the old one;
Back reveals the previous version; Rollback jumps to any saved stage.  The
These operators are intentionally no longer exposed in the UI: they copy only one
mesh and cannot restore the complete multi-object brace design. Keep them until the
patient-project checkpoint prototype replaces them, then remove this module.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ..core import BRACE_STAGE_IDS, brace_stage_index, brace_stage_label


def _active_brace_obj(context):
    """The mesh being worked on: the registered scan, else the active mesh."""
    settings = context.scene.rigo_brace
    obj = settings.scan_object
    if obj is not None and obj.type == "MESH":
        return obj
    obj = context.active_object
    if obj is not None and obj.type == "MESH":
        return obj
    return None


def _ensure_object_mode(context):
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _patient_collection(context, patient):
    coll = bpy.data.collections.get(patient)
    if coll is None:
        coll = bpy.data.collections.new(patient)
        context.scene.collection.children.link(coll)
    return coll


def _move_to_collection(obj, coll):
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    for other in list(obj.users_collection):
        if other is not coll:
            try:
                other.objects.unlink(obj)
            except Exception:
                pass


def _patient_versions(patient):
    """Map stage-index -> version object for ``patient``."""
    out = {}
    if not patient:
        return out
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.get("rigo_patient") == patient:
            out[int(obj.get("rigo_stage", 0))] = obj
    return out


def _version_name(patient, idx):
    return f"{idx:02d}_{patient}_{BRACE_STAGE_IDS[idx]}"


def _init_history(context, obj):
    """Stamp a fresh scan as version 00 (the FILE stage) and file it under a
    per-patient collection.  Returns the patient name."""
    patient = obj.get("rigo_patient")
    if patient:
        return patient
    # The orthotist's typed patient name wins; fall back to the object name.
    patient = (context.scene.rigo_brace.brace_patient or "").strip() or obj.name
    obj["rigo_patient"] = patient
    obj["rigo_stage"] = 0
    coll = _patient_collection(context, patient)
    _move_to_collection(obj, coll)
    obj.name = _version_name(patient, 0)
    obj.data.name = obj.name
    context.scene.rigo_brace.brace_patient = patient
    return patient


def _activate(context, obj):
    for o in context.view_layer.objects:
        o.select_set(False)
    obj.hide_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


class RIGO_OT_stage_next(Operator):
    """Save the current stage as a version and advance to the next stage"""

    bl_idname = "rigo.stage_next"
    bl_label = "Next Stage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_brace_obj(context) is not None

    def execute(self, context):
        obj = _active_brace_obj(context)
        if obj is None:
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}
        _ensure_object_mode(context)

        patient = _init_history(context, obj)
        cur = int(obj.get("rigo_stage", 0))
        if cur >= len(BRACE_STAGE_IDS) - 1:
            self.report({"INFO"}, "Already at the final stage")
            return {"CANCELLED"}

        # Re-doing Next after a rollback rebuilds forward history: drop any
        # versions beyond the current stage.
        for idx, ver in list(_patient_versions(patient).items()):
            if idx > cur:
                data = ver.data
                bpy.data.objects.remove(ver, do_unlink=True)
                if data.users == 0:
                    bpy.data.meshes.remove(data)

        nidx = cur + 1
        new = obj.copy()
        new.data = obj.data.copy()
        new["rigo_patient"] = patient
        new["rigo_stage"] = nidx
        new.name = _version_name(patient, nidx)
        new.data.name = new.name
        _move_to_collection(new, _patient_collection(context, patient))

        # Freeze the old stage as history, edit the new one.
        obj.hide_set(True)
        obj.select_set(False)
        _activate(context, new)

        settings = context.scene.rigo_brace
        if settings.scan_object is obj:
            settings.scan_object = new
        settings.brace_stage = BRACE_STAGE_IDS[nidx]
        self.report({"INFO"}, f"Stage: {brace_stage_label(BRACE_STAGE_IDS[nidx])}")
        return {"FINISHED"}


class RIGO_OT_stage_back(Operator):
    """Go back to the previous saved stage version"""

    bl_idname = "rigo.stage_back"
    bl_label = "Previous Stage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = _active_brace_obj(context)
        return obj is not None and int(obj.get("rigo_stage", 0)) > 0

    def execute(self, context):
        obj = _active_brace_obj(context)
        if obj is None:
            self.report({"ERROR"}, "No design in progress")
            return {"CANCELLED"}
        _ensure_object_mode(context)

        patient = obj.get("rigo_patient")
        cur = int(obj.get("rigo_stage", 0))
        if not patient or cur <= 0:
            self.report({"INFO"}, "Already at the first stage")
            return {"CANCELLED"}

        prev = _patient_versions(patient).get(cur - 1)
        if prev is None:
            self.report({"WARNING"}, "No previous version found")
            return {"CANCELLED"}

        obj.hide_set(True)
        obj.select_set(False)
        _activate(context, prev)

        settings = context.scene.rigo_brace
        if settings.scan_object is obj:
            settings.scan_object = prev
        settings.brace_stage = BRACE_STAGE_IDS[cur - 1]
        self.report({"INFO"}, f"Stage: {brace_stage_label(BRACE_STAGE_IDS[cur - 1])}")
        return {"FINISHED"}


class RIGO_OT_rollback(Operator):
    """Jump to a saved stage version, hiding the others"""

    bl_idname = "rigo.rollback"
    bl_label = "Roll Back to Stage"
    bl_options = {"REGISTER", "UNDO"}

    stage: StringProperty()

    def execute(self, context):
        settings = context.scene.rigo_brace
        patient = settings.brace_patient
        if not patient:
            obj = _active_brace_obj(context)
            patient = obj.get("rigo_patient") if obj else None
        if not patient:
            self.report({"ERROR"}, "No design history yet")
            return {"CANCELLED"}
        _ensure_object_mode(context)

        versions = _patient_versions(patient)
        target = versions.get(brace_stage_index(self.stage))
        if target is None:
            self.report({"WARNING"}, f"No saved version for {self.stage}")
            return {"CANCELLED"}

        for ver in versions.values():
            ver.hide_set(True)
            ver.select_set(False)
        _activate(context, target)

        settings.scan_object = target
        settings.brace_stage = self.stage
        self.report({"INFO"}, f"Rolled back to {brace_stage_label(self.stage)}")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_stage_next,
    RIGO_OT_stage_back,
    RIGO_OT_rollback,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
