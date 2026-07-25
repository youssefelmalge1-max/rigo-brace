"""Experiment: find the Simple Deform BEND configuration for a coronal side-bend.

Stand-in torso: cylinder, height 0.65 m along +Z, base at z=0, facing -Y.
For each candidate (deform_axis, origin rotation) apply BEND 40 deg and measure
where the top-centre goes and whether the base stays.  A correct coronal bend:
top tips sideways in X, base fixed, no wrap/collapse.

Runs headless:  blender --background --factory-startup --python tools/bendexp.py
Writes bendexp_result.txt.
"""

import math

import bpy
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\bendexp_result.txt"
_log = []


def _mark(msg):
    _log.append(str(msg))
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_log))


def _fresh_torso():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.15, depth=0.65, vertices=32, location=(0, 0, 0.325)
    )
    obj = bpy.context.active_object
    # Subdivide along Z so the bend has geometry to work with.
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    for _ in range(5):
        bpy.ops.mesh.subdivide()
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def _measure(obj, rot_euler, axis, angle_deg):
    origin = bpy.data.objects.new("BendOrigin", None)
    origin.location = (0.0, 0.0, 0.0)
    origin.rotation_euler = rot_euler
    bpy.context.scene.collection.objects.link(origin)

    mod = obj.modifiers.new(name="Bend", type="SIMPLE_DEFORM")
    mod.deform_method = "BEND"
    mod.deform_axis = axis
    mod.origin = origin
    mod.angle = math.radians(angle_deg)

    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mesh = ev.to_mesh()

    # Track the vertices that started highest / lowest (top and base rings).
    base = obj.data
    idx_top = max(range(len(base.vertices)), key=lambda i: base.vertices[i].co.z)
    idx_bot = min(range(len(base.vertices)), key=lambda i: base.vertices[i].co.z)
    before_top = base.vertices[idx_top].co.copy()
    before_bot = base.vertices[idx_bot].co.copy()
    after_top = mesh.vertices[idx_top].co.copy()
    after_bot = mesh.vertices[idx_bot].co.copy()
    d_top = after_top - before_top
    d_bot = (after_bot - before_bot).length

    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    spans = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))

    ev.to_mesh_clear()
    obj.modifiers.remove(mod)
    bpy.data.objects.remove(origin, do_unlink=True)
    return d_top, d_bot, spans


def main():
    candidates = (
        ("axis=X rot=0",        (0, 0, 0),                "X"),
        ("axis=Y rot=0",        (0, 0, 0),                "Y"),
        ("axis=Z rot=0",        (0, 0, 0),                "Z"),
        ("axis=X rotX=90",      (math.radians(90), 0, 0), "X"),
        ("axis=Y rotX=90",      (math.radians(90), 0, 0), "Y"),
        ("axis=Z rotX=90",      (math.radians(90), 0, 0), "Z"),
        ("axis=X rotY=90",      (0, math.radians(90), 0), "X"),
        ("axis=Y rotY=90",      (0, math.radians(90), 0), "Y"),
        ("axis=Z rotY=90",      (0, math.radians(90), 0), "Z"),
    )
    obj = _fresh_torso()
    _mark("name | d_top(x,y,z) | d_bot | spans(x,y,z)  [want: top moves in X, "
          "base ~0, spans sane (start 0.30/0.30/0.65)]")
    for name, rot, axis in candidates:
        d_top, d_bot, spans = _measure(obj, rot, axis, 40.0)
        _mark(
            f"{name:16s} | top=({d_top.x:+.3f},{d_top.y:+.3f},{d_top.z:+.3f}) "
            f"| bot={d_bot:.4f} | spans=({spans[0]:.3f},{spans[1]:.3f},{spans[2]:.3f})"
        )
    _mark("DONE")


main()
