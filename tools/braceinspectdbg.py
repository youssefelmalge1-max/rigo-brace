"""Controlled regeneration of the standard template case, with full metadata.

Answers: does the CURRENTLY INSTALLED build reproduce a corrupted brace on the
same template/scan/settings we have been using all along?

Reports every rigo_ key on the generated corset plus independent mesh
diagnostics, so stored metadata and measured geometry can be compared rather
than trusted.
"""

import hashlib
import sys
import traceback

import bmesh
import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import design_ops  # noqa: E402
from bl_ext.user_default.rigo_brace.operators.mesh_intersections import (  # noqa: E402
    triangle_intersection_pairs,
)

OUT = r"C:\Projects\Blender Add-on Braces\braceinspectdbg_result.txt"
TRIES = {"n": 0}


def _mesh_report(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = [e for e in bm.edges if e.is_boundary]
    nonmanifold = [e for e in bm.edges if len(e.link_faces) > 2]
    loose = [v for v in bm.verts if not v.link_faces]
    # boundary loops
    remaining = set(boundary)
    loops = 0
    while remaining:
        loops += 1
        stack = [remaining.pop()]
        while stack:
            edge = stack.pop()
            for vert in edge.verts:
                for other in vert.link_edges:
                    if other in remaining:
                        remaining.discard(other)
                        stack.append(other)
    bm.free()
    obj.data.calc_loop_triangles()
    coords = [v.co.copy() for v in obj.data.vertices]
    tris = [tuple(t.vertices) for t in obj.data.loop_triangles]
    pairs = triangle_intersection_pairs(coords, tris)
    components = design_ops._connected_component_count(tris, len(coords))
    digest = hashlib.sha256(
        repr([tuple(round(c, 9) for c in v) for v in coords]).encode()
    ).hexdigest()[:16]
    return {
        "verts": len(obj.data.vertices),
        "faces": len(obj.data.polygons),
        "tris": len(tris),
        "boundary_edges": len(boundary),
        "boundary_loops": loops,
        "nonmanifold_edges": len(nonmanifold),
        "loose_verts": len(loose),
        "components": components,
        "self_intersections": len(pairs),
        "hash": digest,
    }


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        lines.append("=== INPUTS (the standard repeated setup) ===")
        lines.append(f"  scan object        : {scan.name!r}")
        lines.append(f"  scan verts         : {len(scan.data.vertices)}")
        lines.append(f"  trim_source_mode   : {settings.trim_source_mode}")
        lines.append(f"  trim_type          : {settings.trim_type}")
        lines.append(f"  opening_width      : {settings.opening_width} mm")
        lines.append(f"  corset_offset      : {settings.corset_offset} mm")
        lines.append(f"  corset_thickness   : {settings.corset_thickness} mm")
        lines.append(f"  corset_smooth      : {settings.corset_smooth}")
        lines.append(f"  trim_fillet_radius : {settings.trim_fillet_radius} mm")
        lines.append(f"  trim_fillet_segs   : {settings.trim_fillet_segments}")
        perimeter = bpy.data.objects.get("Rigo Trim Perimeter")
        if perimeter:
            lines.append(
                f"  trimline           : {len(perimeter.data.splines[0].bezier_points)} "
                f"controls, source={perimeter.get('rigo_trim_source', 'TEMPLATE')}, "
                f"handle_model={perimeter.get('rigo_trim_handle_model')}"
            )
        lines.append("")

        try:
            result = bpy.ops.rigo.generate_curve_corset()
            error = ""
        except RuntimeError as exc:
            result, error = {"CANCELLED"}, str(exc).strip()
        lines.append(f"=== GENERATE: {result} ===")
        if error:
            lines.append(f"  {error}")
        lines.append("")

        corset = bpy.data.objects.get("Rigo Corset")
        if corset is None:
            lines.append("NO CORSET PRODUCED")
        else:
            lines.append("=== STORED METADATA (every rigo_ key) ===")
            for key in sorted(k for k in corset.keys() if k.startswith("rigo_")):
                value = corset[key]
                try:
                    value = list(value) if hasattr(value, "__len__") and not isinstance(value, str) else value
                except Exception:
                    pass
                lines.append(f"  {key:<42} = {value}")
            lines.append("")
            lines.append("=== INDEPENDENT MESH DIAGNOSTICS ===")
            for key, value in _mesh_report(corset).items():
                lines.append(f"  {key:<20} = {value}")
            lines.append("")
            base = bpy.data.objects.get("Rigo Corset Base")
            if base is not None:
                lines.append("=== INNER SURFACE (Rigo Corset Base) ===")
                for key in sorted(
                    k for k in base.keys() if k.startswith("rigo_")
                ):
                    lines.append(f"  {key:<42} = {base[key]}")
                base.data.calc_loop_triangles()
                pairs = triangle_intersection_pairs(
                    [v.co.copy() for v in base.data.vertices],
                    [tuple(t.vertices) for t in base.data.loop_triangles],
                )
                lines.append(f"  measured self_intersections            = {len(pairs)}")
            lines.append("")
            lines.append("=== SCENE OBJECTS ===")
            for obj in sorted(bpy.data.objects, key=lambda o: o.name):
                lines.append(
                    f"  {obj.name!r:<34} {obj.type:<6} "
                    f"{'HIDDEN' if obj.hide_get() else 'visible'}"
                )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
