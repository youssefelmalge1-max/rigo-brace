"""Report mesh-quality metrics for the active object (run inside Blender).

Verts/faces/tris, non-manifold edges, loose verts, open boundaries (watertight?),
zero-area faces, world-space dimensions (mm). Writes mesh_metrics.txt to the repo root.

Run (GUI Blender, select an object first or it uses the active):
  & "<blender>" --app-template rigo_brace --python orthoblender-spine-skill/scripts/mesh_quality_metrics.py
"""

import os
import bpy
import bmesh

_OUT = os.path.join(r"C:\Projects\Blender Add-on Braces", "mesh_metrics.txt")


def _go():
    obj = bpy.context.active_object
    if obj is None or obj.type != "MESH":
        # try the registered scan
        s = getattr(bpy.context.scene, "rigo_brace", None)
        obj = getattr(s, "scan_object", None) if s else None
    lines = []
    if obj is None or obj.type != "MESH":
        lines.append("no mesh object active")
    else:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
        boundary = sum(1 for e in bm.edges if e.is_boundary)
        loose = sum(1 for v in bm.verts if not v.link_edges)
        zero_area = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
        d = obj.dimensions
        lines += [
            f"object={obj.name}",
            f"verts={len(bm.verts)} edges={len(bm.edges)} faces={len(bm.faces)}",
            f"non_manifold_edges={non_manifold}",
            f"boundary_edges={boundary}  watertight={boundary == 0}",
            f"loose_verts={loose}",
            f"zero_area_faces={zero_area}",
            f"dims_mm=({d.x*1000:.1f}, {d.y*1000:.1f}, {d.z*1000:.1f})",
        ]
        bm.free()
    with open(_OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_go, first_interval=0.5)
