"""The shared acceptance contract, proven over the full edit matrix.

The old batteries were green because each exercised ONE arc. Issue #46 showed
that proves nothing: a 1.03mm Smooth Arc edit at (17,21) destroys a brace that
builds unedited, while a 60mm Straighten elsewhere is fine.

This runs every editing mode over every measured arc and asserts the ONE
contract that must hold regardless of which of them happens to be unbuildable:

  A  Apply & Verify never leaves an accepted-but-unbuildable trimline.
     After Apply, either the trimline is stamped VERIFIED and Generate
     succeeds, or the edit was rejected and the trimline is byte-identical to
     the pre-edit state.
  B  A rejection restores controls, handles, handle types, control count,
     metadata and selection bit-exactly, and leaves the last valid brace alone.
  C  The VERIFIED stamp is signed: changing the body, the trimline or any
     build-affecting setting makes it STALE.

Usage: blender --python trimacceptmatrix.py -- <mode>[:<arc index>]
  mode: SMOOTH | SMOOTH_ARC | STRAIGHTEN | BLEND | SIGNATURE | PAINTED | MANUAL

ONE CELL PER LAUNCH. Seven builds in a single Blender session exhausted this
machine ("Calloc returns null", then a silent crash that wrote no result at
all), so each arc runs in its own process and appends its lines to the mode's
result file. Partial progress therefore survives a crash instead of vanishing.
"""

import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    trimverify_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\trimacceptmatrix_result"
ARCS = [(17, 21), (18, 20), (20, 28), (24, 30), (10, 14), (30, 36), (2, 8)]
TRIES = {"n": 0}
CHECKS = []
LINES = []


def _gate(name, ok, detail):
    CHECKS.append(bool(ok))
    LINES.append(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def _perimeter():
    return bpy.data.objects["Rigo Trim Perimeter"]


def _fingerprint(curve):
    """Controls, handles, handle types, selection and tracked metadata."""
    spline = curve.data.splines[0]
    points = [
        (
            tuple(round(v, 9) for v in p.co),
            tuple(round(v, 9) for v in p.handle_left),
            tuple(round(v, 9) for v in p.handle_right),
            p.handle_left_type,
            p.handle_right_type,
            bool(p.select_control_point),
        )
        for p in spline.bezier_points
    ]
    metadata = {
        key: str(curve.get(key, ""))
        for key in trimverify_ops._TRACKED_METADATA
    }
    return repr((points, metadata))


def _brace_fingerprint():
    brace = bpy.data.objects.get("Rigo Corset")
    if brace is None:
        return "NO BRACE"
    return f"{len(brace.data.vertices)}v/{len(brace.data.polygons)}f"


def _apply():
    try:
        result = bpy.ops.rigo.apply_trimline_edit()
        return result, ""
    except RuntimeError as exc:
        return {"CANCELLED"}, str(exc).strip().splitlines()[0][:90]


def _generate():
    try:
        return bpy.ops.rigo.generate_curve_corset() == {"FINISHED"}, ""
    except RuntimeError as exc:
        return False, str(exc).strip().splitlines()[0][:70]


def _select(curve, arc):
    for index, point in enumerate(curve.data.splines[0].bezier_points):
        point.select_control_point = arc[0] <= index <= arc[1]


def _edit(mode, arc, select=True):
    curve = _perimeter()
    if select and mode != "SMOOTH":
        _select(curve, arc)
    try:
        bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode=mode)
        return True, ""
    except RuntimeError as exc:
        return False, str(exc).strip().splitlines()[0][:70]


def _case(mode, arc, valid_brace, confirm_generate):
    """One matrix cell: edit, Apply, then check the shared contract.

    `confirm_generate` runs an INDEPENDENT Generate on the first verified cell
    of each mode, to prove verification predicts generation. It is not run per
    cell: Apply already executes the same pipeline, and doubling the builds
    exhausted this machine's memory (Calloc returns null) partway through.
    """
    bpy.ops.rigo.auto_trimline()
    curve = _perimeter()
    # Select FIRST, then snapshot. The operator restores the selection the
    # orthotist made, which is correct - they must be able to retry the same
    # arc after a rejection - so a baseline captured before the selection
    # would report a spurious difference.
    if mode != "SMOOTH":
        _select(curve, arc)
    before = _fingerprint(curve)
    edited, edit_error = _edit(mode, arc, select=False)
    if not edited:
        # the operator refused up front (e.g. Straighten's #45 guard)
        _gate(
            f"{mode} {arc}: up-front refusal leaves the curve exact",
            _fingerprint(_perimeter()) == before,
            f"refused: {edit_error[:48]}",
        )
        return False
    result, message = _apply()
    curve = _perimeter()
    state = trimverify_ops.verification_state(bpy.context, curve)
    if result == {"FINISHED"}:
        if confirm_generate:
            built, error = _generate()
            _gate(
                f"{mode} {arc}: a VERIFIED edit really does Generate",
                state == "VERIFIED" and built,
                f"state={state} generate={'OK' if built else 'FAIL ' + error}",
            )
        else:
            _gate(
                f"{mode} {arc}: accepted edit is stamped VERIFIED",
                state == "VERIFIED",
                f"state={state}",
            )
        return True
    else:
        _gate(
            f"{mode} {arc}: rejection restores the trimline bit-exactly",
            _fingerprint(curve) == before,
            f"rejected ({message[:44]})",
        )
        _gate(
            f"{mode} {arc}: last valid brace untouched",
            _brace_fingerprint() == valid_brace,
            f"{_brace_fingerprint()} vs {valid_brace}",
        )
    return False


def _signature_cases():
    bpy.ops.rigo.auto_trimline()
    curve = _perimeter()
    result, message = _apply()
    _gate("baseline template verifies", result == {"FINISHED"}, message or "")
    _gate(
        "state is VERIFIED after a passing Apply",
        trimverify_ops.verification_state(bpy.context, curve) == "VERIFIED",
        trimverify_ops.verification_state(bpy.context, curve),
    )
    settings = bpy.context.scene.rigo_brace
    for name, delta in (
        ("corset_thickness", 1.0),
        ("trim_fillet_radius", 0.2),
        ("corset_offset", 0.5),
    ):
        original = getattr(settings, name)
        setattr(settings, name, original + delta)
        _gate(
            f"changing {name} makes the stamp STALE",
            trimverify_ops.verification_state(bpy.context, curve) == "STALE",
            trimverify_ops.verification_state(bpy.context, curve),
        )
        setattr(settings, name, original)
    _gate(
        "restoring the settings makes it VERIFIED again",
        trimverify_ops.verification_state(bpy.context, curve) == "VERIFIED",
        trimverify_ops.verification_state(bpy.context, curve),
    )
    # body change must invalidate it too (LM-0039)
    scan = settings.scan_object
    modifier = scan.modifiers.new(name="Signature Probe", type="SIMPLE_DEFORM")
    modifier.deform_method = "TWIST"
    modifier.angle = 0.2
    bpy.context.view_layer.update()
    _gate(
        "deforming the body makes the stamp STALE",
        trimverify_ops.verification_state(bpy.context, curve) == "STALE",
        trimverify_ops.verification_state(bpy.context, curve),
    )
    scan.modifiers.remove(modifier)
    # editing the trimline must clear the stamp outright
    bpy.context.view_layer.update()
    _edit("SMOOTH", (0, 0))
    _gate(
        "an edit clears the stamp",
        trimverify_ops.verification_state(bpy.context, _perimeter())
        == "UNVERIFIED",
        trimverify_ops.verification_state(bpy.context, _perimeter()),
    )


def _painted_cases():
    """The PAINTED authoring path through the same contract.

    Painted trimlines come from `custom_trim_ops`, a different generator with
    a different control density, and #43 records that they have their own
    boundary-resample failure. The acceptance contract must not care: an edit
    on a painted line either verifies or rolls back, exactly as on a template.
    """
    import math

    from bl_ext.user_default.rigo_brace.operators import design_ops
    from bl_ext.user_default.rigo_brace.operators.custom_trim_ops import (
        _ensure_mask,
    )
    from bl_ext.user_default.rigo_brace.operators.design_ops import (
        _inside_unwrapped_polygon,
        _theta_of,
    )

    def _inside_span(sample, polygon):
        """`_trim_perimeter_uv` returns an UNWRAPPED polygon, so a plain
        odd-even test is wrong past the front seam (same helper as
        customtrimtest; `_inside_span` is not a design_ops symbol)."""
        angles = [angle for angle, _height in polygon]
        return _inside_unwrapped_polygon(
            sample, polygon, min(angles), max(angles)
        )

    settings = bpy.context.scene.rigo_brace
    scan = settings.scan_object
    polygon, axis_x, axis_y, front_x, front_y = design_ops._trim_perimeter_uv(
        bpy.context
    )
    attribute = _ensure_mask(scan)
    painted = 0
    for vertex, color in zip(scan.data.vertices, attribute.data):
        world = scan.matrix_world @ vertex.co
        angle = _theta_of(world.x, world.y, axis_x, axis_y, front_x, front_y)
        inside = _inside_span((angle % math.tau, world.z), polygon)
        color.color = (0.0, 0.0, 0.0, 1.0) if inside else (1.0, 1.0, 1.0, 1.0)
        painted += int(inside)
    scan.data.update()
    settings.trim_source_mode = "CUSTOM_PAINT"
    bpy.ops.rigo.clear_trimlines()
    settings.trim_custom_spacing = 6.0
    result = bpy.ops.rigo.custom_trim_from_paint()
    _gate("painted trimline is created", result == {"FINISHED"},
          f"{result}, {painted} painted vertices")
    curve = _perimeter()
    _gate("painted source is recorded",
          curve.get("rigo_trim_source") == "CUSTOM_PAINT",
          str(curve.get("rigo_trim_source")))
    controls = len(curve.data.splines[0].bezier_points)
    LINES.append(f"  painted controls={controls}")
    for mode, arc in (("SMOOTH", None), ("SMOOTH_ARC", (4, 10))):
        before = _fingerprint(_perimeter())
        edited, edit_error = _edit(mode, arc or (0, 0))
        if not edited:
            _gate(f"painted {mode}: refusal leaves the curve exact",
                  _fingerprint(_perimeter()) == before, edit_error[:50])
            continue
        applied, message = _apply()
        curve = _perimeter()
        state = trimverify_ops.verification_state(bpy.context, curve)
        if applied == {"FINISHED"}:
            _gate(f"painted {mode}: accepted edit is stamped VERIFIED",
                  state == "VERIFIED", f"state={state}")
        else:
            _gate(
                f"painted {mode}: rejection restores the curve bit-exactly",
                _fingerprint(curve) == before,
                f"rejected ({message[:44]})",
            )


def _manual_cases():
    """The MANUAL authoring path: a template line whose controls were dragged.

    Manual handles carry their own provenance (`rigo_trim_manual_handles`) and
    must survive a rollback, so this drags controls, edits, and checks that a
    rejection restores the manual record along with the geometry.
    """
    bpy.ops.rigo.auto_trimline()
    curve = _perimeter()
    spline = curve.data.splines[0]
    # a manual drag: move three controls outward along their own radius
    for index in (6, 7, 8):
        point = spline.bezier_points[index]
        delta = point.co.copy()
        delta.z = 0.0
        if delta.length > 1.0e-9:
            offset = delta.normalized() * 0.004
            point.co += offset
            point.handle_left += offset
            point.handle_right += offset
    curve["rigo_trim_manual_handles"] = [6, 7, 8]
    before = _fingerprint(curve)
    _gate("manual edit recorded", "rigo_trim_manual_handles" in curve,
          str(list(curve.get("rigo_trim_manual_handles", []))))
    edited, edit_error = _edit("SMOOTH_ARC", (10, 14))
    if not edited:
        _gate("manual: refusal leaves the curve exact",
              _fingerprint(_perimeter()) == before, edit_error[:50])
        return
    applied, message = _apply()
    curve = _perimeter()
    state = trimverify_ops.verification_state(bpy.context, curve)
    if applied == {"FINISHED"}:
        _gate("manual: accepted edit is stamped VERIFIED",
              state == "VERIFIED", f"state={state}")
        _gate("manual-handle provenance survives acceptance",
              list(curve.get("rigo_trim_manual_handles", [])) != [],
              str(list(curve.get("rigo_trim_manual_handles", []))))
    else:
        _gate("manual: rejection restores geometry AND provenance",
              _fingerprint(curve) == before,
              f"rejected ({message[:44]})")


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    argument = sys.argv[-1]
    mode, _, index = argument.partition(":")
    try:
        prepare_reference_design()
        if mode == "SIGNATURE":
            _signature_cases()
        elif mode == "PAINTED":
            _painted_cases()
        elif mode == "MANUAL":
            _manual_cases()
        else:
            # a known-good brace to prove rejections leave it alone
            bpy.ops.rigo.auto_trimline()
            built, error = _generate()
            _gate("baseline brace builds", built, error)
            valid_brace = _brace_fingerprint()
            LINES.append(f"  baseline brace = {valid_brace}")
            position = int(index) if index.isdigit() else 0
            # The independent Generate only needs to run once per mode: Apply
            # already executes the same pipeline, and re-running it for all
            # seven arcs tripled the build count for no extra evidence.
            _case(mode, ARCS[position], valid_brace, position == 0)
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
        CHECKS.append(False)
    LINES.append(f"PASS={all(CHECKS)}")
    # ONE FILE PER CELL. Sharing a per-mode file meant each arc's launch
    # overwrote the previous one, so a seven-arc sweep left only the last arc's
    # result behind and looked like a one-arc run. Per-cell files also survive
    # a crashed cell.
    suffix = f"_{index}" if index.isdigit() else ""
    with open(f"{OUT}_{mode}{suffix}.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
