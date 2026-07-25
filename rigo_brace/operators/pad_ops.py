"""Pressure / Relief shape library — LeoSpinal-style modification shapes.

A pad is a CLOSED EDITABLE OUTLINE draped on the scan surface (a Bezier curve
tube, like the trim-line tool).  The orthotist:

    1. picks a shape from the library drop-down (favourite depth/size/kind
       pre-fill automatically),
    2. clicks on the scan to place it,
    3. optionally drags the control points to fit the patient (Edit Boundary),
    4. hits Apply: the surface inside the outline is displaced along its
       normals — pressure pushes in, expansion builds out — with a smooth
       feather to zero at the outline boundary.

Any fitted outline can be RECORDED into the library under a name, with the
current depth as its favourite, and reused on every patient (the library is a
per-PC json file — see core/pad_library.py).
"""

import json
import math

import bpy
from bpy.props import BoolProperty, FloatVectorProperty, StringProperty
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Vector, kdtree
from mathutils.geometry import interpolate_bezier

from ..core import PAD_COLLECTION, PAD_PREFIX, pad_library

# Pads sit this far above the surface so the tube reads clearly.
_SURFACE_LIFT = 0.0015
_BOUNDARY_PREVIEW_NAME = "Rigo Boundary Preview"


def _scan_of(context):
    settings = context.scene.rigo_brace
    obj = settings.scan_object or context.active_object
    if obj is None or obj.type != "MESH":
        return None
    return obj


def _modifier_block_msg(scan):
    """Live modifiers make draping/applying slow (each raycast re-evaluates
    the modified mesh — observed multi-minute UI freezes) and would be baked
    incorrectly. Refuse EARLY with the modifiers named, or return None."""
    if not scan.modifiers:
        return None
    names = ", ".join(m.name for m in scan.modifiers)
    return (
        f"The scan has live modifier(s): {names} — apply or remove them "
        "first (Bend/Twist/Stretch: press Apply or Reset)"
    )


def _warn_if_corset_hides_result(context, operator):
    """Shapes modify the BODY SCAN (the mold). If a generated corset is
    visible it hides the scan, so the effect looks like nothing happened."""
    corset = bpy.data.objects.get("Rigo Corset")
    if corset is not None and not corset.hide_get():
        operator.report(
            {"WARNING"},
            "Shapes modify the body scan under the corset — press Generate "
            "again afterwards to see them in the shell",
        )


def _ensure_object_mode(context):
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _pad_collection(context):
    coll = bpy.data.collections.get(PAD_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(PAD_COLLECTION)
        context.scene.collection.children.link(coll)
    return coll


def _pad_color(kind):
    return (0.9, 0.1, 0.1, 1.0) if kind == "PRESSURE" else (0.1, 0.4, 0.9, 1.0)


def _iter_pads():
    """All placed pad outlines — identified by custom prop, never by name."""
    for obj in bpy.data.objects:
        if obj.type == "CURVE" and obj.get("rigo_pad_id"):
            yield obj


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def _surface_frame(normal):
    """(u, v, w): w = surface normal, u = world-up projected in-plane.
    Keeps every shape's 'up' consistent wherever it is placed."""
    w = normal.normalized()
    u = Vector((0.0, 0.0, 1.0)) - w * w.z
    if u.length < 0.1:  # near-horizontal surface: fall back to world Y
        u = Vector((0.0, 1.0, 0.0)) - w * w.y
    u.normalize()
    v = w.cross(u)
    return u, v, w


def _drape_closest(scan, depsgraph, target_world):
    """Snap a point to the nearest scan surface (used when there is no
    meaningful ray direction, e.g. mirroring to the opposite body side)."""
    inv = scan.matrix_world.inverted()
    ok, loc, normal, _i = scan.closest_point_on_mesh(
        inv @ target_world, depsgraph=depsgraph
    )
    if not ok:
        return target_world.copy()
    n_world = (scan.matrix_world.to_3x3() @ normal).normalized()
    return scan.matrix_world @ loc + n_world * _SURFACE_LIFT


def _drape_point(scan, depsgraph, target_world, w, max_jump):
    """Project a point onto the scan surface: raycast from outside along -w,
    falling back to closest-point when the ray misses OR grazes the silhouette
    and lands far away (``max_jump`` bounds the accepted travel — without it a
    ray skimming the body's edge drapes points way down the torso).  Returns
    (location, normal) in world space, lifted slightly off the surface."""
    inv = scan.matrix_world.inverted()
    mw3 = scan.matrix_world.to_3x3()
    hit, loc, normal, _i = scan.ray_cast(
        inv @ (target_world + w * 0.15),
        (inv.to_3x3() @ (-w)).normalized(),
        depsgraph=depsgraph,
    )
    if hit and (scan.matrix_world @ loc - target_world).length > max_jump:
        hit = False
    if not hit:
        ok, loc, normal, _i = scan.closest_point_on_mesh(
            inv @ target_world, depsgraph=depsgraph
        )
        if not ok:
            return target_world.copy(), w.copy()
    n_world = (mw3 @ normal).normalized()
    return scan.matrix_world @ loc + n_world * _SURFACE_LIFT, n_world


def _make_pad_curve(context, name, points, pad_id, kind, depth):
    """Closed Bezier outline through ``points`` (world) — the visible pad."""
    curve = bpy.data.curves.new(name, type="CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.002  # visible tube, like the trim line
    curve.resolution_u = 6

    spline = curve.splines.new("BEZIER")
    spline.use_cyclic_u = True
    spline.bezier_points.add(len(points) - 1)
    for bp, co in zip(spline.bezier_points, points):
        bp.co = co
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"

    obj = bpy.data.objects.new(name, curve)
    obj["rigo_pad_id"] = pad_id
    obj["rigo_kind"] = kind
    obj["rigo_depth"] = depth
    obj.color = _pad_color(kind)
    obj.show_name = True
    _pad_collection(context).objects.link(obj)
    return obj


def _show_object_colors(context):
    """Solid-mode shading must use per-object colors so the red/blue pad
    colour coding is visible."""
    try:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.color_type = "OBJECT"
    except Exception:
        pass


def _spawn_pad(context, scan, entry, hit_world, hit_normal):
    """Drape the library entry's shape onto the scan around the hit point."""
    settings = context.scene.rigo_brace
    depsgraph = context.evaluated_depsgraph_get()
    u, v, w = _surface_frame(hit_normal)
    radius = settings.pad_size * 0.0005  # size = full width, mm

    points = []
    for a, b in entry["points"]:
        target = hit_world + (u * a + v * b) * radius
        loc, _n = _drape_point(scan, depsgraph, target, w, max_jump=radius * 1.5)
        points.append(loc)

    handles = None
    saved_handles = entry.get("handles")
    if isinstance(saved_handles, dict):
        left = saved_handles.get("left", ())
        right = saved_handles.get("right", ())
        if len(left) == len(points) and len(right) == len(points):
            handles = []
            for left_2d, right_2d in zip(left, right):
                left_target = hit_world + (u * left_2d[0] + v * left_2d[1]) * radius
                right_target = hit_world + (u * right_2d[0] + v * right_2d[1]) * radius
                left_world, _ = _drape_point(
                    scan, depsgraph, left_target, w, max_jump=radius * 1.5
                )
                right_world, _ = _drape_point(
                    scan, depsgraph, right_target, w, max_jump=radius * 1.5
                )
                handles.append((left_world, right_world))

    pad = _make_pad_curve(
        context,
        f"{PAD_PREFIX}{entry['id']}",
        points,
        entry["id"],
        settings.pad_kind,
        settings.pad_depth,
    )
    _set_pad_handles(pad, handles)
    settings.active_pad = pad
    _show_object_colors(context)
    return pad


def _sample_pad_boundary(pad, depsgraph):
    """Dense world-space polyline of the outline (honours edited handles).

    Reads the EVALUATED curve: AUTO handle positions are only computed during
    depsgraph evaluation — on the raw datablock they are still (0,0,0), which
    would bend every sampled segment toward the object origin."""
    pad_ev = pad.evaluated_get(depsgraph)
    mw = pad_ev.matrix_world
    samples = []
    for spline in pad_ev.data.splines:
        bps = spline.bezier_points
        n = len(bps)
        for i in range(n):
            a, b = bps[i], bps[(i + 1) % n]
            seg = interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, 12)
            samples.extend(mw @ p for p in seg[:-1])
    return samples


def _newell_normal(points):
    n = Vector((0.0, 0.0, 0.0))
    count = len(points)
    for i in range(count):
        p, q = points[i], points[(i + 1) % count]
        n.x += (p.y - q.y) * (p.z + q.z)
        n.y += (p.z - q.z) * (p.x + q.x)
        n.z += (p.x - q.x) * (p.y + q.y)
    return n.normalized() if n.length > 1e-12 else Vector((0.0, 0.0, 1.0))


def _inside_2d(px, py, poly):
    """Even-odd point-in-polygon — winding-agnostic (mirrored shapes free)."""
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py):
            if px < xi + (py - yi) / (yj - yi) * (xj - xi):
                inside = not inside
        j = i
    return inside


def _control_points_world(pad):
    mw = pad.matrix_world
    pts = []
    for spline in pad.data.splines:
        pts.extend(mw @ bp.co for bp in spline.bezier_points)
    return pts


def _bezier_geometry_world(pad, depsgraph):
    evaluated = pad.evaluated_get(depsgraph)
    matrix = evaluated.matrix_world
    geometry = []
    for spline in evaluated.data.splines:
        for point in spline.bezier_points:
            geometry.append(
                (
                    matrix @ point.co,
                    matrix @ point.handle_left,
                    matrix @ point.handle_right,
                )
            )
    return geometry


def _set_pad_handles(pad, handles):
    if handles is None:
        return
    points = pad.data.splines[0].bezier_points
    if len(points) != len(handles):
        raise ValueError("Saved boundary handle count does not match its point count")
    inverse = pad.matrix_world.inverted()
    for point, (left, right) in zip(points, handles):
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = inverse @ left
        point.handle_right = inverse @ right


def _ray_scan_surface(scan, region, region_3d, event):
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    if not (0 <= coord[0] <= region.width and 0 <= coord[1] <= region.height):
        return None, None
    direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coord)
    origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coord)
    inverse = scan.matrix_world.inverted()
    hit, location, normal, _index = scan.ray_cast(
        inverse @ origin, (inverse.to_3x3() @ direction).normalized()
    )
    if not hit:
        return None, None
    world_location = scan.matrix_world @ location
    world_normal = (scan.matrix_world.to_3x3() @ normal).normalized()
    return world_location + world_normal * _SURFACE_LIFT, world_normal


def _remove_boundary_preview():
    preview = bpy.data.objects.get(_BOUNDARY_PREVIEW_NAME)
    if preview is None:
        return
    curve = preview.data
    bpy.data.objects.remove(preview, do_unlink=True)
    if curve.users == 0:
        bpy.data.curves.remove(curve)


def _update_boundary_preview(context, points, kind):
    _remove_boundary_preview()
    if not points:
        return
    curve = bpy.data.curves.new(_BOUNDARY_PREVIEW_NAME, type="CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.0015
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for spline_point, location in zip(spline.points, points):
        spline_point.co = (*location, 1.0)
    spline.use_cyclic_u = len(points) >= 3
    preview = bpy.data.objects.new(_BOUNDARY_PREVIEW_NAME, curve)
    preview.color = _pad_color(kind)
    _pad_collection(context).objects.link(preview)


def _create_drawn_boundary(context, points):
    settings = context.scene.rigo_brace
    boundary = _make_pad_curve(
        context,
        f"{PAD_PREFIX}UNSAVED_BOUNDARY",
        points,
        "UNSAVED_BOUNDARY",
        settings.pad_kind,
        settings.pad_depth,
    )
    boundary["rigo_unsaved_boundary"] = True
    settings.active_pad = boundary
    _show_object_colors(context)
    # Iterating ``context.view_layer.objects`` can yield a transient null RNA
    # entry after the modal preview curve is removed (Blender 5.0).  Blender's
    # selection operator handles that dependency-graph transition safely.
    bpy.ops.object.select_all(action="DESELECT")
    boundary.select_set(True)
    context.view_layer.objects.active = boundary
    return boundary


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #
class RIGO_OT_draw_boundary(Operator):
    """Click surface points to create a new closed pressure/expansion boundary"""

    bl_idname = "rigo.draw_boundary"
    bl_label = "Draw New Boundary"
    bl_options = {"REGISTER", "UNDO"}

    points_json: StringProperty(options={"HIDDEN"})

    _scan = None
    _region = None
    _region_3d = None
    _points = None

    def _restore_ui(self, context):
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)

    def _cancel(self, context):
        _remove_boundary_preview()
        self._restore_ui(context)
        return {"CANCELLED"}

    def _finish(self, context):
        if len(self._points) < 3:
            self.report({"WARNING"}, "Add at least 3 boundary points")
            return {"RUNNING_MODAL"}
        _remove_boundary_preview()
        _create_drawn_boundary(context, self._points)
        self._restore_ui(context)
        self.report({"INFO"}, "Boundary created — use Edit Boundary to refine it")
        return {"FINISHED"}

    def invoke(self, context, event):
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"WARNING"}, "Open this from the 3D viewport")
            return {"CANCELLED"}
        self._scan = _scan_of(context)
        if self._scan is None:
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}
        blocked = _modifier_block_msg(self._scan)
        if blocked:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        self._region = next(
            (region for region in context.area.regions if region.type == "WINDOW"), None
        )
        self._region_3d = context.area.spaces.active.region_3d
        if self._region is None or self._region_3d is None:
            self.report({"WARNING"}, "Open this from the 3D viewport")
            return {"CANCELLED"}
        _ensure_object_mode(context)
        _remove_boundary_preview()
        self._points = []
        context.window.cursor_modal_set("CROSSHAIR")
        context.workspace.status_text_set(
            "Left-click points on scan | Enter closes | Backspace removes | Esc cancels"
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scan = _scan_of(context)
        if scan is None:
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}
        try:
            raw_points = json.loads(self.points_json)
            points = [Vector(point) for point in raw_points]
        except (json.JSONDecodeError, TypeError, ValueError):
            self.report({"ERROR"}, "Boundary test points are invalid")
            return {"CANCELLED"}
        if len(points) < 3:
            self.report({"ERROR"}, "Boundary needs at least 3 points")
            return {"CANCELLED"}
        _ensure_object_mode(context)
        _create_drawn_boundary(context, points)
        return {"FINISHED"}

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return self._cancel(context)
        if event.type == "BACK_SPACE" and event.value == "PRESS":
            if self._points:
                self._points.pop()
                _update_boundary_preview(
                    context, self._points, context.scene.rigo_brace.pad_kind
                )
            return {"RUNNING_MODAL"}
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._finish(context)
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            location, _normal = _ray_scan_surface(
                self._scan, self._region, self._region_3d, event
            )
            if location is None:
                self.report({"WARNING"}, "Click on the scan surface")
                return {"RUNNING_MODAL"}
            self._points.append(location)
            _update_boundary_preview(
                context, self._points, context.scene.rigo_brace.pad_kind
            )
            return {"RUNNING_MODAL"}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}


class RIGO_OT_add_pad(Operator):
    """Place the selected library shape at the 3D cursor (snapped to the scan)"""

    bl_idname = "rigo.add_pad"
    bl_label = "Add Shape at Cursor"
    bl_options = {"REGISTER", "UNDO"}

    location: FloatVectorProperty(subtype="TRANSLATION", options={"HIDDEN"})
    use_location: BoolProperty(default=False, options={"HIDDEN"})

    def execute(self, context):
        settings = context.scene.rigo_brace
        scan = _scan_of(context)
        if scan is None:
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}
        _ensure_object_mode(context)

        blocked = _modifier_block_msg(scan)
        if blocked:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}

        entry = pad_library.get_entry(settings.pad_type)
        if entry is None:
            self.report({"ERROR"}, "No library shape selected")
            return {"CANCELLED"}

        target = (
            Vector(self.location)
            if self.use_location
            else context.scene.cursor.location.copy()
        )
        depsgraph = context.evaluated_depsgraph_get()
        ok, loc, normal, _i = scan.closest_point_on_mesh(
            scan.matrix_world.inverted() @ target, depsgraph=depsgraph
        )
        if not ok:
            self.report({"ERROR"}, "Could not find the scan surface")
            return {"CANCELLED"}
        hit = scan.matrix_world @ loc
        snap_mm = (hit - target).length * 1000.0
        n_world = (scan.matrix_world.to_3x3() @ normal).normalized()
        scan.hide_set(False)
        _spawn_pad(context, scan, entry, hit, n_world)
        _warn_if_corset_hides_result(context, self)
        if snap_mm > 200.0:
            self.report(
                {"WARNING"},
                f"3D cursor was {snap_mm:.0f} mm from the scan — the shape "
                "snapped to the nearest surface. Shift+Right-Click on the "
                "scan to aim, or use Place on Scan",
            )
        else:
            self.report({"INFO"}, f"Placed: {entry['label']}")
        return {"FINISHED"}


class RIGO_OT_place_pad(Operator):
    """Click on the scan to place the selected library shape there"""

    bl_idname = "rigo.place_pad"
    bl_label = "Place Shape on Scan"

    _region = None
    _rv3d = None
    _scan = None

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        self._scan = _scan_of(context)
        if self._scan is None:
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}
        blocked = _modifier_block_msg(self._scan)
        if blocked:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        self._scan.hide_set(False)
        _ensure_object_mode(context)
        for region in context.area.regions:
            if region.type == "WINDOW":
                self._region = region
                break
        self._rv3d = context.area.spaces.active.region_3d
        if self._region is None or self._rv3d is None:
            self.report({"WARNING"}, "Open this from the 3D viewport")
            return {"CANCELLED"}
        context.window.cursor_modal_set("EYEDROPPER")
        context.workspace.status_text_set(
            "Click on the scan to place the shape  |  Right-click / Esc to finish"
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _ray(self, context, event):
        """Raycast the SCAN only — placed pad tubes must not swallow clicks."""
        return _ray_scan_surface(self._scan, self._region, self._rv3d, event)

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            context.window.cursor_modal_restore()
            context.workspace.status_text_set(None)
            return {"FINISHED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit, normal = self._ray(context, event)
            if hit is None:
                self.report({"WARNING"}, "Click on the scan surface")
                return {"RUNNING_MODAL"}
            entry = pad_library.get_entry(context.scene.rigo_brace.pad_type)
            if entry is None:
                self.report({"ERROR"}, "No library shape selected")
                return {"RUNNING_MODAL"}
            _spawn_pad(context, self._scan, entry, hit, normal)
            self.report({"INFO"}, f"Placed: {entry['label']}")
            return {"RUNNING_MODAL"}
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}


# --------------------------------------------------------------------------- #
# Shape editing / per-pad settings
# --------------------------------------------------------------------------- #
class RIGO_OT_edit_pad(Operator):
    """Show draggable control points so the shape can be fitted to the patient"""

    bl_idname = "rigo.edit_pad"
    bl_label = "Edit Boundary"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "rigo_brace", None)
        if settings is None:
            return False
        pad = settings.active_pad
        obj = context.active_object
        return (pad is not None and pad.get("rigo_pad_id")) or (
            obj is not None and obj.get("rigo_pad_id")
        )

    def execute(self, context):
        settings = context.scene.rigo_brace
        pad = settings.active_pad
        if pad is None or not pad.get("rigo_pad_id"):
            pad = context.active_object
        if pad is None or not pad.get("rigo_pad_id"):
            self.report({"ERROR"}, "Place a shape first")
            return {"CANCELLED"}

        _ensure_object_mode(context)
        for obj in context.view_layer.objects:
            obj.select_set(False)
        pad.hide_set(False)
        pad.select_set(True)
        context.view_layer.objects.active = pad
        settings.active_pad = pad
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.curve.select_all(action="SELECT")
        self.report(
            {"INFO"},
            "Drag the blue points to fit the shape, green handles to round it",
        )
        return {"FINISHED"}


class RIGO_OT_update_pad(Operator):
    """Push the current Depth / Effect onto the active shape"""

    bl_idname = "rigo.update_pad"
    bl_label = "Update Shape"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.rigo_brace
        pad = settings.active_pad
        if pad is None or not pad.get("rigo_pad_id"):
            self.report({"ERROR"}, "No active shape")
            return {"CANCELLED"}
        pad["rigo_depth"] = settings.pad_depth
        pad["rigo_kind"] = settings.pad_kind
        pad.color = _pad_color(settings.pad_kind)
        self.report({"INFO"}, "Shape updated")
        return {"FINISHED"}


class RIGO_OT_mirror_pads(Operator):
    """Mirror every placed shape across X=0, re-draped onto the body"""

    bl_idname = "rigo.mirror_pads"
    bl_label = "Mirror L/R Shapes"
    bl_options = {"REGISTER", "UNDO"}

    @staticmethod
    def _twin_id(ident):
        if ident.endswith("_L"):
            return ident[:-2] + "_R"
        if ident.endswith("_R"):
            return ident[:-2] + "_L"
        return ident

    def execute(self, context):
        scan = _scan_of(context)
        if scan is None:
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}
        _ensure_object_mode(context)
        depsgraph = context.evaluated_depsgraph_get()

        sources = [p for p in _iter_pads() if not p.get("rigo_twin_of")]
        # Re-running replaces previous twins instead of stacking them.
        for old in [p for p in _iter_pads() if p.get("rigo_twin_of")]:
            data = old.data
            bpy.data.objects.remove(old, do_unlink=True)
            if data.users == 0:
                bpy.data.curves.remove(data)

        made = 0
        for pad in sources:
            points = [
                _drape_closest(scan, depsgraph, Vector((-p.x, p.y, p.z)))
                for p in _control_points_world(pad)
            ]
            twin_ident = self._twin_id(pad["rigo_pad_id"])
            twin = _make_pad_curve(
                context,
                f"{PAD_PREFIX}{twin_ident}",
                points,
                twin_ident,
                pad.get("rigo_kind", "PRESSURE"),
                pad.get("rigo_depth", 8.0),
            )
            twin["rigo_twin_of"] = pad.name
            made += 1
        self.report({"INFO"}, f"Mirrored {made} shape(s)")
        return {"FINISHED"}


class RIGO_OT_clear_pads(Operator):
    """Remove all placed shapes"""

    bl_idname = "rigo.clear_pads"
    bl_label = "Clear All Shapes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = 0
        for obj in list(_iter_pads()):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data.users == 0:
                bpy.data.curves.remove(data)
            removed += 1
        # Legacy point pads from older scenes.
        for obj in list(bpy.data.objects):
            if obj.type == "EMPTY" and obj.name.startswith(PAD_PREFIX):
                bpy.data.objects.remove(obj, do_unlink=True)
                removed += 1
        context.scene.rigo_brace.active_pad = None
        self.report({"INFO"}, f"Removed {removed} shape(s)")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Library: record / favourites
# --------------------------------------------------------------------------- #
class RIGO_OT_record_pad_shape(Operator):
    """Save the active fitted shape into the library under a new name.
    The current Depth / Size / Effect become its favourites.
    (Stored on disk — not removed by Undo.)"""

    bl_idname = "rigo.record_pad_shape"
    bl_label = "Save Boundary to Library"

    name: StringProperty(name="Shape Name", default="My Shape")

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "rigo_brace", None)
        return settings is not None and settings.active_pad is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        settings = context.scene.rigo_brace
        pad = settings.active_pad
        if pad is None or not pad.get("rigo_pad_id"):
            self.report({"ERROR"}, "Place and fit a shape first")
            return {"CANCELLED"}
        label = self.name.strip()
        if not label:
            self.report({"ERROR"}, "Type a name for the shape")
            return {"CANCELLED"}
        _ensure_object_mode(context)

        depsgraph = context.evaluated_depsgraph_get()
        bezier_geometry = _bezier_geometry_world(pad, depsgraph)
        points = [point for point, _left, _right in bezier_geometry]
        if len(points) < 3:
            self.report({"ERROR"}, "Shape needs at least 3 points")
            return {"CANCELLED"}

        # Canonical 2D frame: best-fit plane, normal oriented outward (agree
        # with the scan surface), u = world-up in plane.
        center = sum(points, Vector()) / len(points)
        normal = _newell_normal(points)
        scan = _scan_of(context)
        if scan is not None:
            ok, _loc, surf_n, _i = scan.closest_point_on_mesh(
                scan.matrix_world.inverted() @ center
            )
            if ok and (scan.matrix_world.to_3x3() @ surf_n).dot(normal) < 0:
                normal = -normal
        u, v, _w = _surface_frame(normal)

        pts2 = [((p - center).dot(u), (p - center).dot(v)) for p in points]
        cx = sum(p[0] for p in pts2) / len(pts2)
        cy = sum(p[1] for p in pts2) / len(pts2)
        pts2 = [(x - cx, y - cy) for x, y in pts2]
        r = max(math.hypot(x, y) for x, y in pts2)
        if r < 1e-6:
            self.report({"ERROR"}, "Shape is degenerate")
            return {"CANCELLED"}

        def normalized_2d(world_point):
            relative = world_point - center
            return [(relative.dot(u) - cx) / r, (relative.dot(v) - cy) / r]

        handles = {
            "left": [normalized_2d(left) for _point, left, _right in bezier_geometry],
            "right": [normalized_2d(right) for _point, _left, right in bezier_geometry],
        }
        ident = pad_library.entry_id_from_label(label)
        pad_library.upsert_entry(
            {
                "id": ident,
                "label": label,
                "kind": settings.pad_kind,
                "depth_mm": settings.pad_depth,
                "size_mm": 2.0 * r * 1000.0,
                "builtin": False,
                "points": [[x / r, y / r] for x, y in pts2],
                "handles": handles,
                "handle_mode": "FREE",
            }
        )
        pad_library.save_library()
        pad["rigo_pad_id"] = ident
        pad["rigo_unsaved_boundary"] = False
        settings.pad_type = ident  # "record and select"
        self.report({"INFO"}, f"Recorded '{label}' in the library")
        return {"FINISHED"}


class RIGO_OT_set_pad_favourite(Operator):
    """Save the current Depth / Size / Effect as this library shape's
    favourites — they pre-fill automatically every time it is selected.
    (Stored on disk — not removed by Undo.)"""

    bl_idname = "rigo.set_pad_favourite"
    bl_label = "Set as Favourite"

    def execute(self, context):
        settings = context.scene.rigo_brace
        entry = pad_library.get_entry(settings.pad_type)
        if entry is None:
            self.report({"ERROR"}, "No library shape selected")
            return {"CANCELLED"}
        entry["depth_mm"] = settings.pad_depth
        entry["size_mm"] = settings.pad_size
        entry["kind"] = settings.pad_kind
        pad_library.upsert_entry(entry)
        pad_library.save_library()
        self.report(
            {"INFO"},
            f"Favourite saved: {entry['label']} = {settings.pad_depth:.1f} mm "
            f"{'in' if settings.pad_kind == 'PRESSURE' else 'out'}",
        )
        return {"FINISHED"}


class RIGO_OT_delete_pad_entry(Operator):
    """Delete the selected recorded shape from the library
    (builtin clinical shapes cannot be deleted)"""

    bl_idname = "rigo.delete_pad_entry"
    bl_label = "Delete Library Shape"

    def execute(self, context):
        settings = context.scene.rigo_brace
        ident = settings.pad_type
        if not pad_library.delete_entry(ident):
            self.report({"WARNING"}, "Builtin shapes cannot be deleted")
            return {"CANCELLED"}
        pad_library.save_library()
        settings.pad_type = pad_library.load_library()[0]["id"]
        self.report({"INFO"}, "Library shape deleted")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Apply — the LeoSpinal effect
# --------------------------------------------------------------------------- #
class RIGO_OT_apply_pads(Operator):
    """Bake every placed shape into the scan: pressure dents in, expansion
    builds out, feathered smoothly to zero at the outline"""

    bl_idname = "rigo.apply_pads"
    bl_label = "Apply Shapes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scan = _scan_of(context)
        if scan is None:
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}
        _ensure_object_mode(context)
        blocked = _modifier_block_msg(scan)
        if blocked:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}

        pads = list(_iter_pads())
        if not pads:
            self.report({"WARNING"}, "No shapes to apply")
            return {"CANCELLED"}

        mesh = scan.data
        mw = scan.matrix_world
        mw3 = mw.to_3x3()
        mw_inv = mw.inverted()
        normals = [v.normal.copy() for v in mesh.vertices]
        world_co = [mw @ v.co for v in mesh.vertices]
        world_n = [(mw3 @ n).normalized() for n in normals]
        depsgraph = context.evaluated_depsgraph_get()

        for pad in pads:
            boundary = _sample_pad_boundary(pad, depsgraph)
            if len(boundary) < 6:
                continue
            center = sum(boundary, Vector()) / len(boundary)
            plane_n = _newell_normal(boundary)

            # Coarse candidate set + orient the plane normal outward.
            r_max = max((b - center).length for b in boundary)
            candidates = [
                i
                for i, co in enumerate(world_co)
                if (co - center).length <= r_max * 1.6
            ]
            if not candidates:
                continue
            avg_n = sum((world_n[i] for i in candidates), Vector())
            if avg_n.length > 1e-9 and plane_n.dot(avg_n) < 0:
                plane_n = -plane_n

            u, v, _w = _surface_frame(plane_n)
            poly = [((b - center).dot(u), (b - center).dot(v)) for b in boundary]
            cx = sum(p[0] for p in poly) / len(poly)
            cy = sum(p[1] for p in poly) / len(poly)
            r_mean = sum(math.hypot(x - cx, y - cy) for x, y in poly) / len(poly)
            feather = min(max(0.5 * r_mean, 0.005), 0.04)

            tree = kdtree.KDTree(len(poly))
            for i, (x, y) in enumerate(poly):
                tree.insert((x, y, 0.0), i)
            tree.balance()

            kind = pad.get("rigo_kind", "PRESSURE")
            depth = pad.get("rigo_depth", 8.0) * 0.001
            sign = -1.0 if kind == "PRESSURE" else 1.0
            plane_cap = max(r_max * 0.75, 0.05)

            for i in candidates:
                co = world_co[i]
                vn = world_n[i]
                # The scan is a hollow shell: keep the deformation on the
                # facing wall only.
                if vn.dot(plane_n) <= 0.0:
                    continue
                offset = co - center
                if abs(offset.dot(plane_n)) > plane_cap:
                    continue
                px, py = offset.dot(u), offset.dot(v)
                if not _inside_2d(px, py, poly):
                    continue
                _co, _idx, dist = tree.find((px, py, 0.0))
                t = min(dist / feather, 1.0)
                weight = t * t * (3.0 - 2.0 * t)  # smoothstep feather
                world_co[i] = co + vn * (sign * depth * weight)

            pad.hide_set(True)

        for i, vert in enumerate(mesh.vertices):
            vert.co = mw_inv @ world_co[i]
        mesh.update()

        _warn_if_corset_hides_result(context, self)
        self.report({"INFO"}, f"Applied {len(pads)} shape(s)")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_draw_boundary,
    RIGO_OT_add_pad,
    RIGO_OT_place_pad,
    RIGO_OT_edit_pad,
    RIGO_OT_update_pad,
    RIGO_OT_mirror_pads,
    RIGO_OT_clear_pads,
    RIGO_OT_record_pad_shape,
    RIGO_OT_set_pad_favourite,
    RIGO_OT_delete_pad_entry,
    RIGO_OT_apply_pads,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
