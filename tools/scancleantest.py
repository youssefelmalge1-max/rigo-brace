"""Regression gates for the scan-step shaping tools: Smooth Area and Remesh.

Covers, with real geometric assertions rather than "the operator returned
FINISHED":

  registration      rigo.smooth_selection exists; its two settings exist
  smooth.acts       Smooth Area MOVES the surface on every usable patch size
                    (#49g: a fixed 4-row feather ramp swallowed small patches
                    whole - peak strength 0.000, operator cancelled, reported
                    by the orthotist as "no action")
  smooth.blends     Smooth Area's influence reaches BEYOND the painted area so
                    a correction merges with the body instead of ending at a
                    line (#49h), and no cliff is left where it stops
  smooth.bounded    that influence is bounded in millimetres, not unbounded
  smooth.topology   smoothing never changes the face count
  remesh.shading    Auto-Remesh returns a SMOOTH-shaded mesh with crease marks
                    (#49h: a raw REMESH modifier hands back 100% flat faces,
                    and flat shading alone is the dominant reason a corrected
                    area reads as plates - #49c)
  quad.shading      the Quad Remesher hand-off restores shading the same way

Writes scancleantest_result.txt and self-quits.
"""

import bpy
import bmesh
from mathutils import Vector, kdtree

_OUT = r"C:\Projects\Blender Add-on Braces\scancleantest_result.txt"
_SAMPLE = r"C:\Projects\Blender Add-on Braces\Brace Sample.stl"
_TRIES = {"n": 0}
_log = []
_GATES = {}


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _gate(name, ok, detail=""):
    _GATES[name] = bool(ok)
    _mark(f"GATE {name}={'ok' if ok else 'FAIL'} {detail}")


def _import_scan(settings):
    bpy.ops.wm.stl_import(filepath=_SAMPLE)
    scan = bpy.context.active_object
    settings.scan_object = scan
    bpy.context.view_layer.objects.active = scan
    settings.scan_units = "mm"
    bpy.ops.rigo.apply_units()
    return scan


def _select_patch(obj, center, radius):
    """Reproduce the Edit-mode face selection Paint Area leaves behind."""
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bm = bmesh.from_edit_mesh(obj.data)
    faces = 0
    verts = set()
    for face in bm.faces:
        if (face.calc_center_median() - center).length < radius:
            face.select = True
            faces += 1
            for v in face.verts:
                verts.add(v.index)
    bmesh.update_edit_mesh(obj.data)
    return faces, verts


def _shading(me):
    sharp = me.attributes.get("sharp_edge")
    flat = sum(1 for p in me.polygons if not p.use_smooth)
    creases = sum(1 for d in sharp.data if d.value) if sharp is not None else -1
    return flat, creases


def _run():
    _TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and _TRIES["n"] < 25:
        return 0.1
    try:
        _mark("phase=start")
        settings = getattr(bpy.context.scene, "rigo_brace", None)
        _gate(
            "registration",
            hasattr(bpy.ops.rigo, "smooth_selection")
            and settings is not None
            and hasattr(settings, "select_smooth_factor")
            and hasattr(settings, "select_smooth_iters"),
            "rigo.smooth_selection + both settings present",
        )

        # ------------------------------------------------------------------ #
        # Smooth Area — must ACT on every usable patch size (#49g), must blend
        # outward (#49h), must not leave a cliff, must stay bounded.
        # ------------------------------------------------------------------ #
        scan = _import_scan(settings)
        settings.select_smooth_factor = 0.5
        settings.select_smooth_iters = 5
        anchor = max(
            range(len(scan.data.vertices)),
            key=lambda i: scan.data.vertices[i].co.x,
        )
        center = scan.data.vertices[anchor].co.copy()
        box = [Vector(c) for c in scan.bound_box]
        span = (box[6] - box[0]).length

        acted = {}
        for name, fraction in (
            ("micro", 0.006), ("tiny", 0.02), ("small", 0.05),
            ("medium", 0.12), ("large", 0.25),
        ):
            bpy.ops.object.mode_set(mode="OBJECT")
            me = scan.data
            before = [v.co.copy() for v in me.vertices]
            faces, painted = _select_patch(scan, center, span * fraction)
            status = bpy.ops.rigo.smooth_selection()
            bpy.ops.object.mode_set(mode="OBJECT")
            me = scan.data
            moved = [
                i for i in range(len(before))
                if (me.vertices[i].co - before[i]).length > 1e-9
            ]
            shift = max(
                ((me.vertices[i].co - before[i]).length for i in moved),
                default=0.0,
            )
            acted[name] = (faces, len(painted), status, len(moved), shift)
            _mark(
                f"[smooth {name}] painted={faces} faces/{len(painted)} verts "
                f"{status} moved={len(moved)} max_shift={shift*1000.0:.3f}mm"
            )
            for i, co in enumerate(before):
                me.vertices[i].co = co
            me.update()

        # A patch of six painted vertices is already a deliberate act by the
        # orthotist; below that there is nothing to relax.  #49g shipped a
        # ramp that silently swallowed anything small, so the SMALL end is
        # where this gate has to bite.
        usable = [v for k, v in acted.items() if v[1] >= 6]
        _gate(
            "smooth.acts",
            len(usable) >= 4
            and all(
                v[2] == {"FINISHED"} and v[4] * 1000.0 > 0.01 for v in usable
            ),
            "every patch with >=6 painted verts moves the surface: "
            + " ".join(
                f"{k}({v[1]}v)={v[4]*1000.0:.3f}mm/"
                f"{'FIN' if v[2] == {'FINISHED'} else v[2]}"
                for k, v in acted.items() if v[1] >= 6
            ),
        )

        # Blend behaviour, measured on the medium patch.
        bpy.ops.object.mode_set(mode="OBJECT")
        me = scan.data
        before = [v.co.copy() for v in me.vertices]
        faces_before = len(me.polygons)
        _faces, painted = _select_patch(scan, center, span * 0.12)
        bpy.ops.rigo.smooth_selection()
        bpy.ops.object.mode_set(mode="OBJECT")
        me = scan.data
        moved = {
            i for i in range(len(before))
            if (me.vertices[i].co - before[i]).length > 1e-9
        }
        beyond = moved - painted
        cliff = 0.0
        for e in me.edges:
            a, b = e.vertices
            if (a in moved) == (b in moved):
                continue
            inner = a if a in moved else b
            cliff = max(cliff, (me.vertices[inner].co - before[inner]).length)
        tree = kdtree.KDTree(len(painted))
        for i in painted:
            tree.insert(me.vertices[i].co, i)
        tree.balance()
        reach = 0.0
        for i in beyond:
            _co, _idx, d = tree.find(me.vertices[i].co)
            reach = max(reach, d)
        _gate(
            "smooth.blends",
            len(beyond) > 0 and cliff * 1000.0 <= 0.15,
            f"blended {len(beyond)} verts past the paint, cliff where the "
            f"influence stops={cliff*1000.0:.4f}mm",
        )
        _gate(
            "smooth.bounded",
            reach * 1000.0 <= 40.0,
            f"blend reach={reach*1000.0:.1f}mm (ceiling 40)",
        )
        _gate(
            "smooth.topology",
            len(me.polygons) == faces_before,
            f"faces {faces_before} -> {len(me.polygons)}",
        )

        # ------------------------------------------------------------------ #
        # Remesh must hand back a SMOOTH-shaded mesh (#49h).
        # ------------------------------------------------------------------ #
        bpy.data.objects.remove(scan, do_unlink=True)
        scan = _import_scan(settings)
        flat_in, creases_in = _shading(scan.data)
        settings.remesh_voxel = 3.0
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = scan
        bpy.ops.rigo.remesh()
        flat_out, creases_out = _shading(scan.data)
        # Control: what the bare modifier returns, so the gate is anchored to
        # the defect it exists for rather than to today's numbers.
        control = _import_scan(settings)
        mod = control.modifiers.new(name="control", type="REMESH")
        mod.mode = "VOXEL"
        mod.voxel_size = 0.003
        bpy.context.view_layer.objects.active = control
        bpy.ops.object.modifier_apply(modifier=mod.name)
        flat_raw, _creases_raw = _shading(control.data)
        _mark(
            f"[remesh] before flat={flat_in}/creases={creases_in} | "
            f"after flat={flat_out}/creases={creases_out} | "
            f"raw modifier flat={flat_raw}/{len(control.data.polygons)}"
        )
        _gate(
            "remesh.shading",
            flat_out == 0 and creases_out > 0 and flat_raw > 0,
            f"remeshed scan flat_faces={flat_out} creases={creases_out}; "
            f"the bare modifier would have returned {flat_raw} flat faces",
        )
        bpy.data.objects.remove(control, do_unlink=True)

        # ------------------------------------------------------------------ #
        # The Quad Remesher hand-off restores shading the same way.  Exoside
        # is not needed: the operator only adopts whatever object is active.
        # ------------------------------------------------------------------ #
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2)
        stand_in = bpy.context.active_object
        for polygon in stand_in.data.polygons:
            polygon.use_smooth = False
        flat_before, _ = _shading(stand_in.data)
        settings.scan_object = scan
        bpy.context.view_layer.objects.active = stand_in
        status = bpy.ops.rigo.use_quad_remesh_result()
        flat_after, creases_after = _shading(stand_in.data)
        _mark(
            f"[quad hand-off] {status} flat {flat_before} -> {flat_after} "
            f"creases={creases_after}"
        )
        _gate(
            "quad.shading",
            status == {"FINISHED"} and flat_before > 0 and flat_after == 0,
            f"adopted output flat_faces {flat_before} -> {flat_after}",
        )

        failed = sorted(name for name, ok in _GATES.items() if not ok)
        _mark(f"failed_gates={failed}")
        _mark(f"PASS={not failed}")
    except Exception as exc:  # noqa: BLE001
        import traceback

        _mark(f"EXCEPTION={exc!r}\n{traceback.format_exc()}")
        _mark("PASS=False")

    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
