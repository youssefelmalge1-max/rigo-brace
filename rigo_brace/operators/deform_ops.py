"""Mesh-edit derotation tools and the X-ray overlay.

These mirror the LeoSpinal "Mesh edit" deform tools using Blender's Simple
Deform modifier so the result is non-destructive until applied:

    Bend    -> coronal / sagittal correction (BEND)
    Twist   -> transverse-plane derotation (TWIST)
    Stretch -> lengthen / shorten the torso (STRETCH)
    Scale   -> inflate / deflate girth (direct object scale)

Each deform is driven live by the sliders in the panel and can be limited to the
lower part of the body. The X-ray tools bring a coronal radiograph in as an
image empty you can position behind the model.
"""

import math

import bpy
from bpy.types import Operator
from bpy.app.handlers import persistent
from bpy_extras import view3d_utils
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

from ..core import (
    DEFORM_AXIS,
    DEFORM_MODIFIER,
    DEFORM_ORIGIN,
    DEFORM_RING_LOWER,
    DEFORM_RING_MIDDLE,
    DEFORM_RING_UPPER,
    mark_brace_dirty,
)

_DEFORM_COLLECTION = "Rigo Deform"
_SEGMENT_VGROUP = "Rigo Active Deform Segment"
_XRAY_NAME = "Rigo X-ray"
_MASK_UPDATE_BUSY = [False]


def _active_mesh(context):
    obj = context.active_object
    if obj is None or obj.type != "MESH":
        return None
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def _deform_collection(context):
    coll = bpy.data.collections.get(_DEFORM_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(_DEFORM_COLLECTION)
        context.scene.collection.children.link(coll)
    return coll


def _world_bounds(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(c[i] for c in corners) for i in range(3)))
    maxs = Vector((max(c[i] for c in corners) for i in range(3)))
    return mins, maxs


def _make_plane_disc(context, name, center, radius, z, color):
    """A semi-transparent disc with a crisp rim around the body at height
    ``z`` — the LeoSpinal-style deform plane.  One n-gon face, so show_wire
    draws only the rim circle.  Big click target, locked to vertical moves."""
    n = 64
    mesh = bpy.data.meshes.new(name)
    verts = [
        (math.cos(2.0 * math.pi * i / n) * radius,
         math.sin(2.0 * math.pi * i / n) * radius,
         0.0)
        for i in range(n)
    ]
    mesh.from_pydata(verts, [], [tuple(range(n))])

    disc = bpy.data.objects.new(name, mesh)
    disc.color = color                          # shows in Solid + Object color
    disc.show_wire = True                       # crisp rim line
    disc.location = (center[0], center[1], z)
    disc.show_name = True
    disc.lock_location = (True, True, False)    # G only slides it up/down
    disc.lock_rotation = (True, True, True)
    disc.lock_scale = (True, True, True)
    _deform_collection(context).objects.link(disc)
    return disc


def _make_axis_line(context, parent, depth, radius):
    """Thin red bar along Y through the From plane — LeoSpinal's red axis of
    rotation.  Pure indicator: unselectable, rides with its parent disc."""
    half_len = depth * 0.75
    t = max(radius * 0.012, 1e-5)
    mesh = bpy.data.meshes.new(DEFORM_AXIS)
    verts = [
        (-t, -half_len, -t), (t, -half_len, -t), (t, -half_len, t), (-t, -half_len, t),
        (-t, half_len, -t), (t, half_len, -t), (t, half_len, t), (-t, half_len, t),
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
    ]
    mesh.from_pydata(verts, [], faces)
    axis = bpy.data.objects.new(DEFORM_AXIS, mesh)
    axis.color = (1.0, 0.1, 0.1, 1.0)
    axis.hide_select = True
    axis.parent = parent
    _deform_collection(context).objects.link(axis)
    return axis


def _show_object_colors(context):
    """Solid-mode shading must use per-object colors for the plane tints."""
    try:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.color_type = "OBJECT"
    except Exception:
        pass


def _drive_range(scan, origin, plane_lo, plane_hi, z_min, span):
    """Drivers: the rings' world Z positions ARE the deform range.

    limits[0]/[1] take the lower/upper of the two rings (drag order can't break
    them) and the origin empty rides on the lower ring so the body below it
    stays anchored.
    """

    def _add_z_vars(driver):
        for vname, target in (("za", plane_lo), ("zb", plane_hi)):
            var = driver.variables.new()
            var.name = vname
            var.type = "TRANSFORMS"
            tgt = var.targets[0]
            tgt.id = target
            tgt.transform_type = "LOC_Z"
            tgt.transform_space = "WORLD_SPACE"

    for index, pick in ((0, "min"), (1, "max")):
        fcurve = scan.driver_add(f'modifiers["{DEFORM_MODIFIER}"].limits', index)
        drv = fcurve.driver
        drv.type = "SCRIPTED"
        _add_z_vars(drv)
        drv.expression = (
            f"max(0.0,min(1.0,({pick}(za,zb)-({z_min:.6f}))/{span:.6f}))"
        )

    fcurve = origin.driver_add("location", 2)
    drv = fcurve.driver
    drv.type = "SCRIPTED"
    _add_z_vars(drv)
    drv.expression = "min(za,zb)"


def _segment_rings(segment):
    lower = bpy.data.objects.get(DEFORM_RING_LOWER)
    middle = bpy.data.objects.get(DEFORM_RING_MIDDLE)
    upper = bpy.data.objects.get(DEFORM_RING_UPPER)
    if segment == "LOWER":
        return lower, middle
    if segment == "FULL":
        return lower, upper
    return middle, upper


def _segment_weight(z, lower, upper):
    if z <= lower or z >= upper:
        return 0.0
    normalized = (z - lower) / max(upper - lower, 1e-9)
    feather = 0.05
    edge_distance = min(normalized, 1.0 - normalized) / feather
    edge_distance = min(1.0, edge_distance)
    return edge_distance * edge_distance * (3.0 - 2.0 * edge_distance)


def _replace_segment_group(scan, first_ring, second_ring):
    existing = scan.vertex_groups.get(_SEGMENT_VGROUP)
    if existing is not None:
        scan.vertex_groups.remove(existing)
    group = scan.vertex_groups.new(name=_SEGMENT_VGROUP)
    lower, upper = sorted((first_ring.location.z, second_ring.location.z))
    weight_bins = [[] for _index in range(51)]
    maximum_gain = 0.0
    for vertex in scan.data.vertices:
        world_z = (scan.matrix_world @ vertex.co).z
        normalized = (world_z - lower) / max(upper - lower, 1e-9)
        bin_index = round(_segment_weight(world_z, lower, upper) * 50.0)
        if bin_index:
            weight_bins[bin_index].append(vertex.index)
            maximum_gain = max(maximum_gain, normalized * bin_index / 50.0)
    for bin_index, indices in enumerate(weight_bins):
        if indices:
            group.add(indices, bin_index / 50.0, "REPLACE")
    return group, maximum_gain


def _update_segment_mask(scan):
    modifier = scan.modifiers.get(DEFORM_MODIFIER)
    if modifier is None or modifier.deform_method == "BEND":
        return
    segment = scan.get("rigo_deform_segment", "UPPER")
    if segment == "FULL":
        existing = scan.vertex_groups.get(_SEGMENT_VGROUP)
        if existing is not None:
            scan.vertex_groups.remove(existing)
        modifier.vertex_group = ""
        scan["rigo_stretch_gain"] = 1.0
        modifier.factor = float(scan.get("rigo_requested_stretch_mm", 0.0)) * 0.001
        first, second = _segment_rings(segment)
        scan["rigo_mask_ring_z"] = (first.location.z, second.location.z)
        return
    first, second = _segment_rings(segment)
    if first is None or second is None:
        return
    group, maximum_gain = _replace_segment_group(scan, first, second)
    modifier.vertex_group = group.name
    scan["rigo_stretch_gain"] = max(maximum_gain, 1e-6)
    if modifier.deform_method == "STRETCH":
        requested_mm = float(scan.get("rigo_requested_stretch_mm", 0.0))
        modifier.factor = requested_mm * 0.001 / scan["rigo_stretch_gain"]
    scan["rigo_mask_ring_z"] = (first.location.z, second.location.z)


@persistent
def _refresh_segment_mask(scene, _depsgraph):
    if _MASK_UPDATE_BUSY[0]:
        return
    settings = getattr(scene, "rigo_brace", None)
    scan = settings.scan_object if settings is not None else None
    if scan is None or scan.modifiers.get(DEFORM_MODIFIER) is None:
        return
    first, second = _segment_rings(scan.get("rigo_deform_segment", "UPPER"))
    if first is None or second is None:
        return
    current = (first.location.z, second.location.z)
    if tuple(scan.get("rigo_mask_ring_z", ())) == current:
        return
    _MASK_UPDATE_BUSY[0] = True
    try:
        _update_segment_mask(scan)
    finally:
        _MASK_UPDATE_BUSY[0] = False


def _connect_segment(scan, segment):
    origin = bpy.data.objects.get(DEFORM_ORIGIN)
    first, second = _segment_rings(segment)
    if origin is None or first is None or second is None:
        return False
    _remove_range_drivers(scan)
    _drive_range(
        scan,
        origin,
        first,
        second,
        float(scan["rigo_deform_zmin"]),
        float(scan["rigo_deform_zspan"]),
    )
    axis = bpy.data.objects.get(DEFORM_AXIS)
    if axis is not None:
        axis.parent = first
        axis.location = (0.0, 0.0, 0.0)
    scan["rigo_deform_segment"] = segment
    _update_segment_mask(scan)
    return True


def _remove_range_drivers(scan):
    try:
        scan.driver_remove(f'modifiers["{DEFORM_MODIFIER}"].limits', -1)
    except Exception:
        pass


def _remove_range_objects():
    names = (
        DEFORM_ORIGIN,
        DEFORM_AXIS,
        DEFORM_RING_LOWER,
        DEFORM_RING_MIDDLE,
        DEFORM_RING_UPPER,
    )
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Curve):
                    bpy.data.curves.remove(data)


def _clear_deform(scan):
    _remove_range_drivers(scan)
    mod = scan.modifiers.get(DEFORM_MODIFIER)
    if mod is not None:
        scan.modifiers.remove(mod)
    group = scan.vertex_groups.get(_SEGMENT_VGROUP)
    if group is not None:
        scan.vertex_groups.remove(group)
    _remove_range_objects()


def _start_deform(context, method):
    """Create the live Simple Deform modifier set to ``method``."""
    scan = _active_mesh(context)
    if scan is None:
        return None, "Select the scan mesh first"

    settings = context.scene.rigo_brace
    _clear_deform(scan)
    settings.bend_angle = 0.0
    settings.twist_angle = 0.0
    settings.stretch_factor = 0.0
    settings.stretch_mm = 0.0

    # Origin empty at the bottom-centre so bends pivot from the pelvis up.
    # Stash the un-deformed bounds: the From/To plane sliders convert their mm
    # values into modifier limit fractions through these.
    mins, maxs = _world_bounds(scan)
    span = max(maxs.z - mins.z, 1e-6)
    scan["rigo_deform_zmin"] = mins.z
    scan["rigo_deform_zspan"] = span
    origin = bpy.data.objects.new(DEFORM_ORIGIN, None)
    origin.empty_display_type = "ARROWS"
    origin.empty_display_size = 0.1
    origin.location = ((mins.x + maxs.x) * 0.5, (mins.y + maxs.y) * 0.5, mins.z)
    _deform_collection(context).objects.link(origin)

    mod = scan.modifiers.new(name=DEFORM_MODIFIER, type="SIMPLE_DEFORM")
    mod.deform_method = method
    # Axis semantics differ per method. TWIST and STRETCH act ALONG the chosen
    # axis, so Z (the spine) is right. BEND wraps the mesh AROUND the chosen
    # axis: bending around Y tips the upper torso sideways in the coronal plane
    # (the scoliosis correction), while Z would wrap the body around its own
    # vertical axis and flatten it.
    mod.deform_axis = "Y" if method == "BEND" else "Z"
    mod.origin = origin
    if method == "STRETCH":
        # Pure lengthening along the spine: without these locks the stretch
        # also tapers the body in X/Y as it lengthens.
        mod.lock_x = True
        mod.lock_y = True
    # Three draggable rings; the active pair drives the deform interval.
    center = ((mins.x + maxs.x) * 0.5, (mins.y + maxs.y) * 0.5)
    radius = max(maxs.x - mins.x, maxs.y - mins.y) * 0.5 * 1.15
    _make_plane_disc(
        context, DEFORM_RING_LOWER, center, radius, mins.z, (0.1, 0.4, 1.0, 0.65)
    )
    middle = _make_plane_disc(
        context,
        DEFORM_RING_MIDDLE,
        center,
        radius,
        mins.z + span * 0.5,
        (1.0, 1.0, 1.0, 0.65),
    )
    _make_plane_disc(
        context, DEFORM_RING_UPPER, center, radius, maxs.z, (0.1, 0.4, 1.0, 0.65)
    )
    _make_axis_line(context, middle, maxs.y - mins.y, radius)
    _connect_segment(scan, settings.deform_segment)
    _show_object_colors(context)

    settings.scan_object = scan
    return scan, None


class RIGO_OT_deform_start(Operator):
    """Begin a live derotation deform (Bend / Twist / Stretch)"""

    bl_idname = "rigo.deform_start"
    bl_label = "Start Deform"
    bl_options = {"REGISTER", "UNDO"}

    method: bpy.props.EnumProperty(
        items=(
            ("BEND", "Bend", ""),
            ("TWIST", "Twist", ""),
            ("STRETCH", "Stretch", ""),
        ),
        default="BEND",
    )

    def execute(self, context):
        scan, err = _start_deform(context, self.method)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        # World-space height — the scan object often carries an importer
        # rotation, so local dimensions can point along the wrong axis.
        mins, maxs = _world_bounds(scan)
        if max(maxs - mins) > 3.0:
            self.report(
                {"WARNING"},
                "Model is over 3 m across — looks unscaled. Run Apply Units "
                "in the Scan tab first.",
            )
            return {"FINISHED"}
        self.report(
            {"INFO"},
            f"{self.method.title()} ready — choose a ring pair, drag rings with G, "
            "then set the amount",
        )
        return {"FINISHED"}


class RIGO_OT_deform_segment(Operator):
    """Choose which pair of the three rings bounds the live deformation"""

    bl_idname = "rigo.deform_segment"
    bl_label = "Use Deform Segment"
    bl_options = {"REGISTER", "UNDO"}

    segment: bpy.props.EnumProperty(
        items=(
            ("LOWER", "Lower to Middle", "Deform the lower segment"),
            ("UPPER", "Middle to Upper", "Deform the upper segment"),
            ("FULL", "Lower to Upper", "Deform the full model"),
        ),
        default="UPPER",
    )

    def execute(self, context):
        settings = context.scene.rigo_brace
        scan = settings.scan_object or context.active_object
        if scan is None or scan.modifiers.get(DEFORM_MODIFIER) is None:
            self.report({"ERROR"}, "Start Bend, Twist or Stretch first")
            return {"CANCELLED"}
        settings.deform_segment = self.segment
        if not _connect_segment(scan, self.segment):
            self.report({"ERROR"}, "The three deform rings are missing")
            return {"CANCELLED"}
        labels = {
            "LOWER": "Lower–Middle",
            "UPPER": "Middle–Upper",
            "FULL": "Lower–Upper",
        }
        self.report({"INFO"}, f"Active deform interval: {labels[self.segment]}")
        return {"FINISHED"}


class RIGO_OT_deform_apply(Operator):
    """Bake the current deform into the scan"""

    bl_idname = "rigo.deform_apply"
    bl_label = "Apply Deform"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.rigo_brace
        scan = settings.scan_object or context.active_object
        if scan is None or scan.modifiers.get(DEFORM_MODIFIER) is None:
            self.report({"ERROR"}, "No active deform to apply")
            return {"CANCELLED"}
        if context.active_object is not None and context.active_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        context.view_layer.objects.active = scan
        # Freeze the ring-driven values into the modifier and origin BEFORE
        # applying — applying first leaves drivers pointing at a dead path
        # ('Invalid driver' warnings on the next depsgraph pass).
        deps = context.evaluated_depsgraph_get()
        mod = scan.modifiers.get(DEFORM_MODIFIER)
        mod_ev = scan.evaluated_get(deps).modifiers.get(DEFORM_MODIFIER)
        if mod_ev is not None:
            mod.limits[0], mod.limits[1] = mod_ev.limits[0], mod_ev.limits[1]
        _remove_range_drivers(scan)
        origin = bpy.data.objects.get(DEFORM_ORIGIN)
        if origin is not None:
            z_ev = origin.evaluated_get(deps).location.z
            try:
                origin.driver_remove("location", 2)
            except Exception:
                pass
            origin.location.z = z_ev
        bpy.ops.object.modifier_apply(modifier=DEFORM_MODIFIER)
        group = scan.vertex_groups.get(_SEGMENT_VGROUP)
        if group is not None:
            scan.vertex_groups.remove(group)
        _remove_range_objects()
        mark_brace_dirty(context, "The corrected body was deformed")
        self.report({"INFO"}, "Deform baked in")
        return {"FINISHED"}


class RIGO_OT_deform_reset(Operator):
    """Discard the current deform without baking it"""

    bl_idname = "rigo.deform_reset"
    bl_label = "Reset Deform"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.rigo_brace
        scan = settings.scan_object or context.active_object
        if scan is not None:
            _clear_deform(scan)
        settings.bend_angle = 0.0
        settings.twist_angle = 0.0
        settings.stretch_factor = 0.0
        settings.stretch_mm = 0.0
        self.report({"INFO"}, "Deform discarded")
        return {"FINISHED"}


class RIGO_OT_pick_deform_range(Operator):
    """Click the LOWER then the UPPER deform plane directly on the scan.

    Sets the From/To range the live deform acts between (LeoSpinal's movable
    planes).  Right-click or Esc cancels.
    """

    bl_idname = "rigo.pick_deform_range"
    bl_label = "Pick Range on Scan"

    _region = None
    _rv3d = None
    _picked = 0

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        settings = context.scene.rigo_brace
        scan = settings.scan_object or context.active_object
        if scan is None or scan.type != "MESH":
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}
        # Prefer the un-deformed bounds stashed by Start Bend/Twist/Stretch.
        z_min = scan.get("rigo_deform_zmin")
        if z_min is None:
            mins, _maxs = _world_bounds(scan)
            z_min = mins.z
        self._z_min = z_min
        self._scan = scan
        self._picked = 0
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
            "Click the LOWER plane on the body  |  Right-click / Esc to cancel"
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)

    def _ray(self, context, event):
        """Raycast the SCAN only — the semi-transparent plane discs must not
        swallow the click."""
        region, rv3d = self._region, self._rv3d
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        if not (0 <= coord[0] <= region.width and 0 <= coord[1] <= region.height):
            return None
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        inv = self._scan.matrix_world.inverted()
        hit, location, _n, _i = self._scan.ray_cast(
            inv @ origin,
            inv.to_3x3() @ direction,
            depsgraph=context.evaluated_depsgraph_get(),
        )
        return (self._scan.matrix_world @ location) if hit else None

    def modal(self, context, event):
        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._finish(context)
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            location = self._ray(context, event)
            if location is None:
                self.report({"WARNING"}, "Click on the scan surface")
                return {"RUNNING_MODAL"}
            mm = max(0.0, (location.z - self._z_min) * 1000.0)
            settings = context.scene.rigo_brace
            if self._picked == 0:
                settings.deform_from = mm
                self._picked = 1
                context.workspace.status_text_set(
                    "Now click the UPPER plane  |  Right-click / Esc to cancel"
                )
                self.report({"INFO"}, f"From plane: {mm:.0f} mm")
                return {"RUNNING_MODAL"}
            settings.deform_to = mm
            # Keep From below To no matter the click order.
            if settings.deform_to < settings.deform_from:
                settings.deform_from, settings.deform_to = (
                    settings.deform_to,
                    settings.deform_from,
                )
            self._finish(context)
            self.report(
                {"INFO"},
                f"Range: {settings.deform_from:.0f} – {settings.deform_to:.0f} mm",
            )
            return {"FINISHED"}

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}  # let the user orbit/zoom while picking

        return {"RUNNING_MODAL"}


class RIGO_OT_scale_girth(Operator):
    """Inflate or deflate the model's girth by the slider amount"""

    bl_idname = "rigo.scale_girth"
    bl_label = "Apply Inflate / Deflate"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scan = _active_mesh(context)
        if scan is None:
            self.report({"ERROR"}, "Select the scan mesh first")
            return {"CANCELLED"}
        factor = 1.0 + context.scene.rigo_brace.scale_amount
        scan.scale.x *= factor
        scan.scale.y *= factor
        context.view_layer.objects.active = scan
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        self.report({"INFO"}, "Girth adjusted")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# X-ray overlay
# --------------------------------------------------------------------------- #
class RIGO_OT_import_xray(Operator, ImportHelper):
    """Import a coronal X-ray image to overlay behind the model"""

    bl_idname = "rigo.import_xray"
    bl_label = "Import X-ray"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.bmp",
        options={"HIDDEN"},
    )

    def execute(self, context):
        try:
            image = bpy.data.images.load(self.filepath, check_existing=True)
        except RuntimeError:
            self.report({"ERROR"}, "Could not load that image")
            return {"CANCELLED"}

        old = bpy.data.objects.get(_XRAY_NAME)
        if old is not None:
            bpy.data.objects.remove(old, do_unlink=True)

        empty = bpy.data.objects.new(_XRAY_NAME, None)
        empty.empty_display_type = "IMAGE"
        empty.data = image
        empty.use_empty_image_alpha = True
        empty.color[3] = context.scene.rigo_brace.xray_opacity

        # Stand it upright in the coronal plane, behind the model.
        scan = context.scene.rigo_brace.scan_object or context.active_object
        if scan is not None:
            mins, maxs = _world_bounds(scan)
            height = max(maxs.z - mins.z, 0.1)
            empty.location = (
                (mins.x + maxs.x) * 0.5,
                maxs.y + 0.05,
                (mins.z + maxs.z) * 0.5,
            )
            empty.empty_display_size = height
        empty.rotation_euler = (1.5708, 0.0, 0.0)  # face the front (-Y)

        _deform_collection(context).objects.link(empty)
        context.view_layer.objects.active = empty
        self.report({"INFO"}, "X-ray imported — adjust opacity / position")
        return {"FINISHED"}


class RIGO_OT_xray_grab(Operator):
    """Select the X-ray so you can move/scale it with G / S"""

    bl_idname = "rigo.xray_grab"
    bl_label = "Reposition X-ray"

    def execute(self, context):
        empty = bpy.data.objects.get(_XRAY_NAME)
        if empty is None:
            self.report({"ERROR"}, "Import an X-ray first")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        empty.select_set(True)
        context.view_layer.objects.active = empty
        self.report({"INFO"}, "Use G to move, S to scale")
        return {"FINISHED"}


def _select_xray(context):
    empty = bpy.data.objects.get(_XRAY_NAME)
    if empty is None:
        return None
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    empty.select_set(True)
    context.view_layer.objects.active = empty
    return empty


class RIGO_OT_xray_transform(Operator):
    """Move, rotate or scale the X-ray overlay by dragging in the viewport"""

    bl_idname = "rigo.xray_transform"
    bl_label = "Transform X-ray"

    mode: bpy.props.EnumProperty(
        items=(
            ("MOVE", "Move", "Slide the radiograph in its coronal plane"),
            ("ROTATE", "Rotate", "Rotate the radiograph in its plane"),
            ("SCALE", "Scale", "Resize the radiograph uniformly"),
        ),
        default="MOVE",
    )

    def invoke(self, context, event):
        empty = _select_xray(context)
        if empty is None:
            self.report({"ERROR"}, "Import an X-ray first")
            return {"CANCELLED"}
        # Hand over to the native modal transform, constrained so the image
        # stays a coronal overlay: move in its XZ plane, rotate in-plane (Y).
        if self.mode == "MOVE":
            bpy.ops.transform.translate(
                "INVOKE_DEFAULT", constraint_axis=(True, False, True)
            )
        elif self.mode == "ROTATE":
            bpy.ops.transform.rotate("INVOKE_DEFAULT", orient_axis="Y")
        else:
            bpy.ops.transform.resize("INVOKE_DEFAULT")
        return {"FINISHED"}

    def execute(self, context):
        # Non-interactive path (tests/scripts): just select the overlay.
        if _select_xray(context) is None:
            self.report({"ERROR"}, "Import an X-ray first")
            return {"CANCELLED"}
        return {"FINISHED"}


class RIGO_OT_xray_lock(Operator):
    """Lock the X-ray to the model so it follows every later move (toggle)"""

    bl_idname = "rigo.xray_lock"
    bl_label = "Lock X-ray To Model"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        empty = bpy.data.objects.get(_XRAY_NAME)
        if empty is None:
            self.report({"ERROR"}, "Import an X-ray first")
            return {"CANCELLED"}
        scan = context.scene.rigo_brace.scan_object or context.active_object
        if scan is None or scan.type != "MESH" or scan is empty:
            self.report({"ERROR"}, "Import a scan first")
            return {"CANCELLED"}

        if empty.parent is scan:
            # Unlock: keep the current world transform.
            world = empty.matrix_world.copy()
            empty.parent = None
            empty.matrix_world = world
            self.report({"INFO"}, "X-ray unlocked from the model")
        else:
            empty.parent = scan
            empty.matrix_parent_inverse = scan.matrix_world.inverted()
            self.report({"INFO"}, "X-ray locked — it now follows the model")
        return {"FINISHED"}


_CLASSES = (
    RIGO_OT_deform_start,
    RIGO_OT_deform_segment,
    RIGO_OT_deform_apply,
    RIGO_OT_deform_reset,
    RIGO_OT_pick_deform_range,
    RIGO_OT_scale_girth,
    RIGO_OT_import_xray,
    RIGO_OT_xray_grab,
    RIGO_OT_xray_transform,
    RIGO_OT_xray_lock,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if _refresh_segment_mask not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_refresh_segment_mask)


def unregister():
    if _refresh_segment_mask in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_refresh_segment_mask)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
