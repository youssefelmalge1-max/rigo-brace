"""Transactional acceptance for every trimline edit — one shared contract.

Evidence (issue #46) rejected per-mode safety: a 1.03 mm Smooth Arc edit at arc
(17,21) destroys a brace that builds unedited, while a 60 mm Straighten
elsewhere is fine. Failure is neither monotonic in edit size nor confined to
one mode, so no mode-specific guard can be correct. Every editing mode -
Smooth All, Smooth Arc, Straighten Arc, Blend Junction - therefore shares ONE
acceptance path.

Interaction:
  * slider and redo-panel changes stay live preview only; nothing is verified
    and no brace is built, so tweaking stays interactive;
  * Apply runs ONE full buildability verification against a hidden
    transactional candidate - the real pipeline, not a proxy;
  * pass  -> the edited trimline becomes authoritative and is stamped VERIFIED
    for its current signature; the candidate brace is discarded unless the
    workflow asked for generation;
  * fail  -> the previous trimline, handles, control count, metadata and
    selection are restored BIT-EXACTLY, the last valid brace is untouched, and
    the measured stage and local reason are reported.

The verification is signed. Any later change to the body, the trimline, the
edit parameters, the offset, thickness, fillet radius/segments or fairing makes
the stamp stale, so a VERIFIED badge can never outlive its inputs.
"""

import hashlib
import json
import struct

import bpy
from bpy.types import Operator

from ..core import CORSET_NAME
from ..core.signatures import geometry_signature
from . import curve_build_ops, design_ops
from .trimline_ops import TRIM_PERIM_NAME, _scan_of

# Snapshot of the pre-edit trimline, written by every editing mode before it
# mutates anything, so Apply can roll back to it bit-exactly.
PENDING_KEY = "rigo_trim_pending_restore"
# Signature this trimline was proven buildable at.
VERIFIED_KEY = "rigo_trim_verified_signature"
VERIFIED_REPORT_KEY = "rigo_trim_verified_report"

# Every setting that can change the built brace. Adding a build-affecting
# setting WITHOUT adding it here would let a VERIFIED stamp survive a change
# that invalidates it, so this list is part of the contract.
BUILD_SETTINGS = (
    "corset_thickness",
    "corset_offset",
    "corset_smooth",
    "trim_fillet_radius",
    "trim_fillet_segments",
    "trim_transition_width",
    "edge_band",
    "design_style",
    "trim_top",
    "trim_bottom",
    "opening_width",
)

# Metadata that belongs to the trimline's identity and must survive a rollback.
_TRACKED_METADATA = (
    "rigo_trim_handle_model",
    "rigo_trim_refined",
    "rigo_trim_refined_controls",
    "rigo_trim_manual_handles",
    "rigo_trim_dense_controls",
    "rigo_trim_axis",
    "rigo_trim_front",
    "rigo_trim_type",
    "rigo_trim_source",
    "rigo_trim_opening_mm",
    "rigo_trim_opening_deg",
    # the handle-solve fingerprint. Named `rigo_trim_solved_signature` in
    # trimline_ops; restoring the wrong key would leave a rolled-back curve
    # reporting stale handles.
    "rigo_trim_solved_signature",
    # the edit parameters and the verification stamp itself: a rejected edit
    # must put the orthotist back exactly where they were, INCLUDING a proof
    # the trimline had already earned before this edit.
    "rigo_trim_edit_params",
    VERIFIED_KEY,
    VERIFIED_REPORT_KEY,
)


# --------------------------------------------------------------------------
# snapshot / restore

def capture_trimline(curve):
    """Everything needed to restore this trimline bit-exactly."""
    spline = curve.data.splines[0]
    return {
        "points": [
            [
                list(point.co),
                list(point.handle_left),
                list(point.handle_right),
                point.handle_left_type,
                point.handle_right_type,
                bool(point.select_control_point),
                bool(point.select_left_handle),
                bool(point.select_right_handle),
            ]
            for point in spline.bezier_points
        ],
        "cyclic": bool(spline.use_cyclic_u),
        "metadata": {
            key: _plain(curve[key])
            for key in _TRACKED_METADATA
            if key in curve
        },
    }


def _plain(value):
    """JSON-safe copy of an ID property.

    Scalars and STRINGS must pass through untouched. A bare `list(value)` also
    succeeds on a string - `list("C2_PERIODIC")` returns eleven single
    characters - which silently rewrote every string metadata value on capture
    and restored it as a character list. The rollback gate caught it: the
    geometry came back bit-exact while `rigo_trim_handle_model` came back as
    ['C','2','_','P',...].
    """
    if isinstance(value, (str, bytes, bool, int, float)):
        return value
    try:
        return list(value)
    except TypeError:
        return value


def restore_trimline(curve, snapshot):
    """Put the curve back exactly: geometry, handle types, metadata, selection.

    The spline is rebuilt when the control count differs, because an Apply may
    follow an edit that refined the curve, and a partial restore would leave
    the orthotist with a trimline that is neither the old one nor the new one.
    """
    points = snapshot["points"]
    curve_data = curve.data
    spline = curve_data.splines[0]
    if len(spline.bezier_points) != len(points):
        curve_data.splines.remove(spline)
        spline = curve_data.splines.new("BEZIER")
        spline.use_cyclic_u = snapshot.get("cyclic", True)
        spline.bezier_points.add(len(points) - 1)
    for point, record in zip(spline.bezier_points, points):
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.co = record[0]
        point.handle_left = record[1]
        point.handle_right = record[2]
        point.handle_left_type = record[3]
        point.handle_right_type = record[4]
        point.select_control_point = record[5]
        point.select_left_handle = record[6]
        point.select_right_handle = record[7]
    for key in _TRACKED_METADATA:
        if key in curve:
            del curve[key]
    for key, value in snapshot.get("metadata", {}).items():
        curve[key] = value
    curve_data.update_tag()


def stash_pre_edit(curve):
    """Record the pre-edit state, once per edit session.

    Called by every editing mode before it mutates the curve. Blender's redo
    undoes the operator and re-executes it, so each execution genuinely sees
    the pre-edit curve and re-stashing is correct - the snapshot always
    describes the state Apply must return to.
    """
    curve[PENDING_KEY] = json.dumps(capture_trimline(curve))
    # an edit invalidates any previous proof
    for key in (VERIFIED_KEY, VERIFIED_REPORT_KEY):
        if key in curve:
            del curve[key]


# --------------------------------------------------------------------------
# signature

def _pack(digest, value):
    digest.update(struct.pack("<q", round(float(value) * 1.0e9)))


def verification_signature(context, curve):
    """What the VERIFIED stamp is bound to.

    Includes the evaluated body, the raw trimline controls and handles, and
    every build-affecting setting. `geometry_signature` hashes the EVALUATED
    scan, so a lattice, derotation or remesh change invalidates the stamp - the
    same lesson as LM-0039.
    """
    settings = context.scene.rigo_brace
    scan = _scan_of(context)
    digest = hashlib.sha256()
    digest.update(geometry_signature(context, scan).encode("ascii"))
    # raw controls and handles, not the shrinkwrapped display curve
    for point in curve.data.splines[0].bezier_points:
        for vector in (point.co, point.handle_left, point.handle_right):
            for value in vector:
                _pack(digest, value)
        digest.update(point.handle_left_type.encode("ascii"))
        digest.update(point.handle_right_type.encode("ascii"))
    for name in BUILD_SETTINGS:
        value = getattr(settings, name, None)
        if value is None:
            digest.update(b"\x00")
        elif isinstance(value, str):
            digest.update(value.encode("utf-8"))
        elif isinstance(value, bool):
            digest.update(struct.pack("<?", value))
        else:
            _pack(digest, value)
    # the edit parameters that produced this shape
    digest.update(str(curve.get("rigo_trim_edit_params", "")).encode("utf-8"))
    return digest.hexdigest()


def verification_state(context, curve):
    """'VERIFIED', 'STALE' or 'UNVERIFIED' for the trimline as it stands.

    Authoritative and exact - it recomputes the full signature. Panels must
    call `verification_state_cached` instead; see below.
    """
    if curve is None or not curve.data.splines:
        return "UNVERIFIED"
    stamped = str(curve.get(VERIFIED_KEY, ""))
    if not stamped:
        return "UNVERIFIED"
    return (
        "VERIFIED"
        if stamped == verification_signature(context, curve)
        else "STALE"
    )


# The badge is drawn on every panel redraw, including mouse-over, while
# `verification_signature` hashes every vertex and triangle of the evaluated
# scan - roughly 60k struct packs on the reference body. Recomputing that per
# redraw makes the N-panel visibly laggy, so the result is cached and
# recomputed only when the scene actually changed.
_STATE_CACHE = {"key": None, "state": "UNVERIFIED"}
_GEOMETRY_DIRTY = {"value": True}


def _cheap_key(context, curve):
    """Everything that can change the state WITHOUT a depsgraph update."""
    settings = context.scene.rigo_brace
    return (
        curve.name,
        str(curve.get(VERIFIED_KEY, "")),
        len(curve.data.splines[0].bezier_points),
        tuple(str(getattr(settings, name, "")) for name in BUILD_SETTINGS),
    )


def verification_state_cached(context, curve):
    """Same answer as `verification_state`, cheap enough to draw with."""
    if curve is None or not curve.data.splines:
        return "UNVERIFIED"
    key = _cheap_key(context, curve)
    if not _GEOMETRY_DIRTY["value"] and _STATE_CACHE["key"] == key:
        return _STATE_CACHE["state"]
    state = verification_state(context, curve)
    _STATE_CACHE["key"] = key
    _STATE_CACHE["state"] = state
    _GEOMETRY_DIRTY["value"] = False
    return state


@bpy.app.handlers.persistent
def _mark_geometry_dirty(_scene, _depsgraph):
    """Any real scene change may move the body or the trimline."""
    _GEOMETRY_DIRTY["value"] = True


# --------------------------------------------------------------------------
# the verification itself

class VerificationFailure(RuntimeError):
    """A named stage plus the pipeline's own local reason."""

    def __init__(self, stage, reason):
        self.stage = stage
        self.reason = reason
        super().__init__(f"{stage}: {reason}")


def verify_buildable(context, curve):
    """Build a hidden transactional candidate and validate it end to end.

    Runs the REAL pipeline - offset mold, projection, cut, boundary resample,
    rim, wall join, manifold validation and QA - because a proxy check is
    exactly what let a 1.03mm edit reach the orthotist as an accepted design.
    Returns a report dict; raises VerificationFailure with the stage that
    failed.

    The candidate is ALWAYS discarded. It is built under
    `_CORSET_CANDIDATE_NAME`, never `CORSET_NAME`, so a committed brace is
    untouched whichever way verification goes - that is what lets a rejection
    promise the last valid brace is unchanged. Generation stays a separate,
    explicitly requested step.
    """
    settings = context.scene.rigo_brace
    scan = _scan_of(context)
    if scan is None:
        raise VerificationFailure("setup", "no patient scan is assigned")
    base = None
    candidate = None
    report = {}
    try:
        try:
            base = design_ops._prepare_candidate_base(context, scan, settings)
        except Exception as error:  # noqa: BLE001
            raise VerificationFailure("offset mold", str(error)[:180])
        try:
            candidate, projected = curve_build_ops._build_curve_corset(
                context, settings, base, curve
            )
        except design_ops.TrimRimQualityError as error:
            raise VerificationFailure("rim construction", str(error)[:180])
        except design_ops.TrimPerimeterWindingError as error:
            raise VerificationFailure("trimline winding", str(error)[:180])
        except design_ops.OuterWallIntersectionError as error:
            raise VerificationFailure("wall join", str(error)[:180])
        except design_ops.InnerSurfaceFoldError as error:
            raise VerificationFailure("inner surface", str(error)[:180])
        except RuntimeError as error:
            raise VerificationFailure("cutter projection", str(error)[:180])
        report["rim_intersections"] = int(
            candidate.get("rigo_generation_rim_intersections", -1)
        )
        report["trim_max_error_mm"] = float(
            candidate.get("rigo_trim_curve_max_error_mm", 0.0)
        )
        report["verts"] = len(candidate.data.vertices)
        manifold = _manifold_counts(candidate)
        report.update(manifold)
        if manifold["boundary_edges"] or manifold["nonmanifold_edges"]:
            raise VerificationFailure(
                "manifold check",
                f"{manifold['boundary_edges']} open and "
                f"{manifold['nonmanifold_edges']} non-manifold edge(s)",
            )
        return report
    finally:
        for obj in (candidate, base):
            if obj is not None and design_ops._object_is_registered(obj):
                design_ops._remove_object_and_orphan_mesh(obj)


def _manifold_counts(obj):
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    nonmanifold = sum(1 for edge in bm.edges if len(edge.link_faces) > 2)
    loose = sum(1 for vertex in bm.verts if not vertex.link_edges)
    bm.free()
    return {
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "loose_verts": loose,
    }


# --------------------------------------------------------------------------
# the operator

class RIGO_OT_apply_trimline_edit(Operator):
    """Verify the edited trimline builds, then accept it — or restore it exactly"""

    bl_idname = "rigo.apply_trimline_edit"
    bl_label = "Apply & Verify Trimline"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            bpy.data.objects.get(TRIM_PERIM_NAME) is not None
            and _scan_of(context) is not None
        )

    def execute(self, context):
        curve = bpy.data.objects.get(TRIM_PERIM_NAME)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        pending = str(curve.get(PENDING_KEY, ""))
        try:
            report = verify_buildable(context, curve)
        except VerificationFailure as failure:
            restored = False
            if pending:
                try:
                    # restores geometry, handle types, selection AND metadata,
                    # including any verification the trimline held beforehand
                    restore_trimline(curve, json.loads(pending))
                    restored = True
                except Exception:  # noqa: BLE001
                    restored = False
            if not restored:
                # nothing trustworthy to fall back to; never leave a stamp on
                # a curve we could not put back
                for key in (VERIFIED_KEY, VERIFIED_REPORT_KEY):
                    if key in curve:
                        del curve[key]
            if PENDING_KEY in curve:
                del curve[PENDING_KEY]
            self.report(
                {"ERROR"},
                f"Trimline edit REJECTED at {failure.stage}: {failure.reason} "
                + (
                    "The previous trimline has been restored exactly and the "
                    "last valid brace is unchanged."
                    if restored
                    else "No pre-edit snapshot was available, so the trimline "
                         "was left as it is - regenerate before accepting it."
                ),
            )
            return {"CANCELLED"}

        curve[VERIFIED_KEY] = verification_signature(context, curve)
        curve[VERIFIED_REPORT_KEY] = json.dumps(report)
        if PENDING_KEY in curve:
            del curve[PENDING_KEY]
        self.report(
            {"INFO"},
            "Trimline VERIFIED: builds cleanly "
            f"({report.get('rim_intersections', 0)} rim overlaps, "
            f"{report.get('nonmanifold_edges', 0)} non-manifold, "
            f"trim error {report.get('trim_max_error_mm', 0.0):.2f} mm)",
        )
        return {"FINISHED"}


_CLASSES = (RIGO_OT_apply_trimline_edit,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if _mark_geometry_dirty not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_mark_geometry_dirty)


def unregister():
    if _mark_geometry_dirty in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_mark_geometry_dirty)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
