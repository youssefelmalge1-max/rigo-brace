"""Hypothesis: _redepth measures against the RAW scan mesh, not the evaluated one.

trimsmooth_ops._surface_context does `design_ops._source_surface(scan.data)`.
Every other stage of the trimline system uses BVHTree.FromObject(scan,
depsgraph) - the EVALUATED mesh. The patient scan normally carries modifiers
(Rigo Remesh / Rigo Smooth / Rigo Thickness, the derotation SIMPLE_DEFORM, the
Bend-Twist-Stretch lattice, the correction cage). The clean fixture has none,
which is why the defect never showed there.

If the hypothesis holds, one press of Smooth All snaps the whole trimline onto
a surface that is NOT the body the orthotist sees, and the drawn line lands
inside / away from the visible scan - i.e. it "disappears".

Measured here: control displacement and signed distance of both the raw
controls and the DRAWN (modifier-evaluated) line against the EVALUATED body,
before and after Smooth All, with a modifier on the scan.
"""

import sys
import traceback

import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_design  # noqa: E402

OUT = r"C:\Projects\Blender Add-on Braces\trimmoddbg_result.txt"
A_SCAN = r"C:\Projects\Blender Add-on Braces\A type model.stl"
TRIES = {"n": 0}
LINES = []


def _evaluated_bvh(scan):
    return BVHTree.FromObject(scan, bpy.context.evaluated_depsgraph_get())


def _signed_mm(scan, bvh, world_points):
    """Signed distance to the EVALUATED body, in mm (positive = outside)."""
    inverse = scan.matrix_world.inverted()
    rotation = scan.matrix_world.to_3x3()
    out = []
    for point in world_points:
        location, normal, _index, _distance = bvh.find_nearest(inverse @ point)
        if location is None:
            continue
        world_normal = (rotation @ normal).normalized()
        out.append((point - (scan.matrix_world @ location)).dot(world_normal) * 1000.0)
    return out


def _controls(curve):
    spline = curve.data.splines[0]
    return [curve.matrix_world @ p.co.copy() for p in spline.bezier_points]


def _drawn(curve):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = curve.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    points = [evaluated.matrix_world @ v.co.copy() for v in mesh.vertices]
    evaluated.to_mesh_clear()
    return points


def _report(tag, scan, curve):
    bvh = _evaluated_bvh(scan)
    raw = _signed_mm(scan, bvh, _controls(curve))
    drawn = _signed_mm(scan, bvh, _drawn(curve)[::7])
    raw_in = sum(1 for d in raw if d < 0.0)
    drawn_in = sum(1 for d in drawn if d < 0.0)
    LINES.append(f"  [{tag}] vs the body the orthotist SEES")
    LINES.append(
        f"      RAW   controls: min={min(raw):+9.3f}mm max={max(raw):+9.3f}mm "
        f"inside={raw_in}/{len(raw)}"
    )
    LINES.append(
        f"      DRAWN line    : min={min(drawn):+9.3f}mm max={max(drawn):+9.3f}mm "
        f"inside={drawn_in}/{len(drawn)} ({100.0*drawn_in/len(drawn):.1f}%)"
    )


def _case(label, add_modifier):
    LINES.append("=" * 72)
    LINES.append(f"CASE: {label}")
    LINES.append("=" * 72)
    scan, settings = prepare_design(A_SCAN, "RIGO_CHENEAU", opening_width=25.0)
    if add_modifier is not None:
        add_modifier(scan)
        bpy.context.view_layer.update()
        # regenerate against the modified body, as the orthotist would
        bpy.ops.rigo.auto_trimline()
    curve = bpy.data.objects["Rigo Trim Perimeter"]
    LINES.append(f"  scan modifiers: {[m.type for m in scan.modifiers]}")
    before = _controls(curve)
    _report("before Smooth All", scan, curve)

    bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode="SMOOTH")
    after = _controls(curve)
    moved = [(a - b).length * 1000.0 for a, b in zip(after, before)]
    LINES.append(
        f"  control displacement from ONE Smooth All: "
        f"max={max(moved):.2f}mm mean={sum(moved)/len(moved):.2f}mm"
    )
    _report("after Smooth All", scan, curve)


def _lattice(scan):
    """The Bend/Twist/Stretch cage: deforms the body, leaves scan.data alone."""
    data = bpy.data.lattices.new("Dbg Lattice")
    data.points_u = data.points_v = data.points_w = 2
    lattice = bpy.data.objects.new("Dbg Lattice", data)
    bpy.context.scene.collection.objects.link(lattice)
    lattice.location = scan.location
    lattice.scale = (0.6, 0.6, 0.9)
    modifier = scan.modifiers.new(name="Rigo Correction Lattice", type="LATTICE")
    modifier.object = lattice
    # push the cage sideways so the deformed body clearly leaves scan.data
    for index, point in enumerate(data.points):
        if index % 2 == 0:
            point.co_deform.x += 0.35


def _simple_deform(scan):
    """The derotation modifier (deform_ops.py:335)."""
    modifier = scan.modifiers.new(name="Rigo Derotation", type="SIMPLE_DEFORM")
    modifier.deform_method = "TWIST"
    modifier.angle = 0.35
    modifier.deform_axis = "Z"


def _smooth_modifier(scan):
    """Scan-stage noise removal (mesh_ops.py:194)."""
    modifier = scan.modifiers.new(name="Rigo Smooth", type="SMOOTH")
    modifier.factor = 1.5
    modifier.iterations = 30


_CASES = {
    "none": ("no modifier on the scan (the clean fixture)", None),
    "smooth": ("Rigo Smooth modifier on the scan", _smooth_modifier),
    "derotate": ("derotation SIMPLE_DEFORM on the scan", _simple_deform),
    "lattice": ("correction LATTICE on the scan", _lattice),
}


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    key = sys.argv[-1] if sys.argv[-1] in _CASES else "none"
    try:
        _case(*_CASES[key])
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT.replace(".txt", f"_{key}.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
