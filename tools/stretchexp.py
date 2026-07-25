"""Experiment: Simple Deform STRETCH + limits semantics on a standing body.

Cylinder height 0.65 along +Z, base z=0.  Questions:
1. STRETCH axis=Z factor 0.3 — does it taper X/Y (the 'works on Y' complaint)?
2. Do lock_x/lock_y keep the cross-section intact (pure height change)?
3. limits (1/3, 2/3) with origin at the lower plane — is geometry below the
   lower plane frozen, the middle stretched, the top carried rigidly?
4. Same limits applied to BEND — does the bend start at the lower plane?

Runs headless:  blender --background --factory-startup --python tools/stretchexp.py
Writes stretchexp_result.txt.
"""

import math

import bpy
from mathutils import Vector

_OUT = r"C:\Projects\Blender Add-on Braces\stretchexp_result.txt"
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
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    for _ in range(5):
        bpy.ops.mesh.subdivide()
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def _probe(obj, method, factor_or_angle, locks, limits, origin_z):
    origin = bpy.data.objects.new("DefOrigin", None)
    origin.location = (0.0, 0.0, origin_z)
    bpy.context.scene.collection.objects.link(origin)

    mod = obj.modifiers.new(name="Def", type="SIMPLE_DEFORM")
    mod.deform_method = method
    mod.deform_axis = "Y" if method == "BEND" else "Z"
    mod.origin = origin
    if method == "BEND":
        mod.angle = math.radians(factor_or_angle)
    else:
        mod.factor = factor_or_angle
    if locks:
        mod.lock_x = True
        mod.lock_y = True
    if limits is not None:
        mod.limits[0], mod.limits[1] = limits

    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mesh = ev.to_mesh()

    base = obj.data
    # Representative vertices: lowest, ~1/6 height (below lower plane),
    # middle, and highest.
    def nearest_to_z(z):
        return min(range(len(base.vertices)), key=lambda i: abs(base.vertices[i].co.z - z))

    probes = {
        "bot":  nearest_to_z(0.0),
        "low":  nearest_to_z(0.11),
        "mid":  nearest_to_z(0.325),
        "top":  nearest_to_z(0.65),
    }
    moves = {}
    for name, i in probes.items():
        d = mesh.vertices[i].co - base.vertices[i].co
        moves[name] = f"({d.x:+.3f},{d.y:+.3f},{d.z:+.3f})"

    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    spans = f"({max(xs)-min(xs):.3f},{max(ys)-min(ys):.3f},{max(zs)-min(zs):.3f})"

    ev.to_mesh_clear()
    obj.modifiers.remove(mod)
    bpy.data.objects.remove(origin, do_unlink=True)
    return moves, spans


def main():
    obj = _fresh_torso()
    _mark("case | d(bot) d(low z=0.11) d(mid) d(top) | spans  [start spans 0.30,0.30,0.65]")
    cases = (
        ("STRETCH 0.3 no-lock no-limit", "STRETCH", 0.3, False, None, 0.0),
        ("STRETCH 0.3 locked no-limit",  "STRETCH", 0.3, True,  None, 0.0),
        ("STRETCH 0.3 locked lim 1/3-2/3 org@lo", "STRETCH", 0.3, True, (1/3, 2/3), 0.65/3),
        ("BEND 30 lim 1/3-2/3 org@lo",   "BEND",   30.0, False, (1/3, 2/3), 0.65/3),
    )
    for name, method, val, locks, limits, oz in cases:
        moves, spans = _probe(obj, method, val, locks, limits, oz)
        _mark(f"{name} | bot={moves['bot']} low={moves['low']} mid={moves['mid']} "
              f"top={moves['top']} | spans={spans}")
    _mark("DONE")


main()
