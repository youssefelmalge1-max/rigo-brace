"""Why does the trimline vanish after Smooth All / Smooth Arc? Full state dump.

Reproduces the user's exact conditions: template trimline visible, NO brace in
the scene, then Smooth All and Smooth Arc (twice each, plus a redo-style
re-execution, since the defect may depend on the second invocation).

After every press this records everything that can make an object stop being
drawn, because the previous probe only checked hide_get()/spline count and
found nothing:

  hide_get / hide_viewport / hide_render / visible_get
  collection membership + collection hide_viewport + view-layer exclude
  presence in view_layer.objects
  active object + selection
  settings.design_view_mode
  spline count, control count, cyclic flag
  modifier stack (name, type, show_viewport, target)
  evaluated vertex count and world bbox
  signed distance of the EVALUATED line to the scan surface  <-- the one that
      matters: ABOVE_SURFACE is supposed to keep the drawn line outside the
      body, and an evaluated line that has sunk inside is invisible because
      the perimeter is drawn with show_in_front = False.
"""

import sys
import traceback

import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import design_ops  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\trimvisdbg_result.txt"
TRIES = {"n": 0}
LINES = []
SURFACE = {}


def _surface():
    if "src" not in SURFACE:
        scan = bpy.context.scene.rigo_brace.scan_object
        SURFACE["src"] = design_ops._source_surface(scan.data)
        SURFACE["inv"] = scan.matrix_world.inverted()
        SURFACE["mw"] = scan.matrix_world
        SURFACE["rot"] = scan.matrix_world.to_3x3()
        SURFACE["scan"] = scan
    return SURFACE


def _signed_mm(world_points):
    """Signed distance to the scan along interpolated vertex normals, in mm."""
    ctx = _surface()
    out = []
    for point in world_points:
        hit = ctx["src"].bvh.find_nearest(ctx["inv"] @ point)
        if hit[0] is None:
            continue
        normal = (ctx["rot"] @ design_ops._surface_normal_at(
            ctx["src"], hit[0])).normalized()
        out.append((point - (ctx["mw"] @ hit[0])).dot(normal) * 1000.0)
    return out


def _evaluated_world(curve):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = curve.evaluated_get(depsgraph)
    try:
        mesh = evaluated.to_mesh()
    except Exception:
        return []
    if mesh is None:
        return []
    matrix = evaluated.matrix_world
    points = [matrix @ v.co.copy() for v in mesh.vertices]
    evaluated.to_mesh_clear()
    return points


def _state(tag):
    curve = bpy.data.objects.get("Rigo Trim Perimeter")
    settings = bpy.context.scene.rigo_brace
    view_layer = bpy.context.view_layer
    if curve is None:
        LINES.append(f"  [{tag}] OBJECT MISSING")
        return
    spline = curve.data.splines[0] if curve.data.splines else None
    in_layer = curve.name in view_layer.objects
    colls = [c.name for c in curve.users_collection]
    coll_hidden = [
        f"{c.name}:hide_viewport={c.hide_viewport}" for c in curve.users_collection
    ]
    excluded = []
    for layer_coll in view_layer.layer_collection.children:
        if layer_coll.name in colls:
            excluded.append(
                f"{layer_coll.name}:exclude={layer_coll.exclude}"
                f",hide={layer_coll.hide_viewport}"
            )
    mods = [
        f"{m.name}({m.type},show_viewport={m.show_viewport},"
        f"target={getattr(getattr(m, 'target', None), 'name', None)!r},"
        f"mode={getattr(m, 'wrap_mode', '-')},off={getattr(m, 'offset', 0.0):.4f})"
        for m in curve.modifiers
    ]
    evaluated = _evaluated_world(curve)
    raw = (
        [curve.matrix_world @ p.co for p in spline.bezier_points]
        if spline else []
    )
    eval_mm = _signed_mm(evaluated[::7]) if evaluated else []
    raw_mm = _signed_mm(raw) if raw else []
    active = view_layer.objects.active
    selected = [o.name for o in bpy.context.selected_objects]
    scan = settings.scan_object

    LINES.append(f"  [{tag}]")
    LINES.append(
        f"      visible_get={curve.visible_get()} hide_get={curve.hide_get()} "
        f"hide_viewport={curve.hide_viewport} hide_render={curve.hide_render} "
        f"in_view_layer={in_layer}"
    )
    LINES.append(f"      collections={coll_hidden} layer={excluded}")
    LINES.append(
        f"      splines={len(curve.data.splines)} "
        f"controls={len(spline.bezier_points) if spline else 0} "
        f"cyclic={spline.use_cyclic_u if spline else None} "
        f"bevel={curve.data.bevel_depth:.5f} "
        f"show_in_front={curve.show_in_front}"
    )
    LINES.append(f"      modifiers={mods}")
    LINES.append(
        f"      design_view_mode={settings.design_view_mode!r} "
        f"active={active.name if active else None!r} selected={selected} "
        f"mode={bpy.context.mode} "
        f"scan_visible={scan.visible_get() if scan else None}"
    )
    if evaluated:
        xs = [p.x for p in evaluated]
        zs = [p.z for p in evaluated]
        LINES.append(
            f"      evalverts={len(evaluated)} "
            f"bbox x[{min(xs):.4f},{max(xs):.4f}] z[{min(zs):.4f},{max(zs):.4f}]"
        )
    else:
        LINES.append("      evalverts=0  <-- NOTHING DRAWN")
    if eval_mm:
        inside = sum(1 for d in eval_mm if d < 0.0)
        LINES.append(
            f"      DRAWN line vs body: min={min(eval_mm):+.3f}mm "
            f"max={max(eval_mm):+.3f}mm inside={inside}/{len(eval_mm)} "
            f"({100.0*inside/len(eval_mm):.1f}%)"
        )
    if raw_mm:
        inside = sum(1 for d in raw_mm if d < 0.0)
        LINES.append(
            f"      RAW controls vs body: min={min(raw_mm):+.3f}mm "
            f"max={max(raw_mm):+.3f}mm inside={inside}/{len(raw_mm)}"
        )


def _press(mode, label):
    LINES.append(f"PRESS {label}")
    try:
        result = bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode=mode)
        LINES.append(f"      -> {result}")
    except RuntimeError as exc:
        LINES.append(f"      -> RuntimeError: {str(exc).strip()[:120]}")
    _state(f"after {label}")


def _select_arc(first, last):
    curve = bpy.data.objects["Rigo Trim Perimeter"]
    for index, point in enumerate(curve.data.splines[0].bezier_points):
        point.select_control_point = first <= index <= last


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    try:
        prepare_reference_design()
        LINES.append(
            f"brace in scene: {bpy.data.objects.get('Rigo Corset') is not None}"
        )
        _state("baseline (template trimline, no brace)")

        _press("SMOOTH", "'Smooth All' #1")
        _press("SMOOTH", "'Smooth All' #2")

        # redo-panel re-execution: Blender undoes then re-runs execute()
        LINES.append("REDO-PANEL SIMULATION (undo + re-execute)")
        try:
            window = bpy.context.window_manager.windows[0]
            area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
            region = next(r for r in area.regions if r.type == "WINDOW")
            with bpy.context.temp_override(
                window=window, screen=window.screen, area=area, region=region
            ):
                bpy.ops.ed.undo()
            _state("after undo")
            bpy.ops.rigo.smooth_trimline(mode="SMOOTH", smoothness=14.0)
            _state("after redo re-execute (smoothness 14)")
        except Exception as exc:  # noqa: BLE001
            LINES.append(f"      redo sim failed: {exc!r}")

        _select_arc(20, 28)
        _state("after selecting controls 20..28")
        _press("SMOOTH_ARC", "'Smooth Arc' #1 (20..28)")
        _select_arc(20, 28)
        _press("SMOOTH_ARC", "'Smooth Arc' #2 (20..28)")

        # and from EDIT mode, which is how the arc really gets selected
        curve = bpy.data.objects["Rigo Trim Perimeter"]
        bpy.ops.object.select_all(action="DESELECT")
        curve.select_set(True)
        bpy.context.view_layer.objects.active = curve
        bpy.ops.object.mode_set(mode="EDIT")
        _select_arc(20, 28)
        _state("in EDIT mode, arc selected")
        _press("SMOOTH_ARC", "'Smooth Arc' FROM EDIT MODE")
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        _state("back in object mode")
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
