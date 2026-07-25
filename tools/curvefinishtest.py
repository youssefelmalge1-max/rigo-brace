"""The Curve generator must produce a FINISHABLE brace.

`trim_ops._edge_band_weights` derives the finishing band from OPEN boundary
edges, but a paired shell is closed, so on a curve-built brace it found nothing
and returned `{}`. Consequences before the fix:

  * Smooth Trim Edge refused with "No edge band on this shell",
  * Vents could not keep clear of the rim (`vent_ops._band_weight_lookup`
    reads the same RIGO_TRIM_BAND group).

The band therefore has to be baked from the rim marker at build time, which is
the only moment the rim is still identifiable. This test gates that the
recommended generator hands the finishing tools something they can work with.
"""

import sys
import traceback

import bpy

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators.trim_ops import (  # noqa: E402
    _BAND_GROUP,
)

OUT = r"C:\Projects\Blender Add-on Braces\curvefinishtest_result.txt"
TRIES = {"count": 0}


def _write(lines):
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _group_members(obj, name):
    group = obj.vertex_groups.get(name)
    if group is None:
        return 0, 0.0
    index = group.index
    count = 0
    heaviest = 0.0
    for vertex in obj.data.vertices:
        for entry in vertex.groups:
            if entry.group == index and entry.weight > 0.0:
                count += 1
                heaviest = max(heaviest, entry.weight)
                break
    return count, heaviest


def _open_boundary_edges(obj):
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = sum(edge.is_boundary for edge in bm.edges)
    bm.free()
    return boundary


def _vertex_positions(obj):
    return [tuple(vertex.co) for vertex in obj.data.vertices]


def _run():
    TRIES["count"] += 1
    if not hasattr(bpy.ops.rigo, "generate_curve_corset") and TRIES["count"] < 30:
        return 0.1
    lines = []
    try:
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        settings.trim_fillet_radius = 0.3
        settings.edge_band = 8.0

        generate_result = bpy.ops.rigo.generate_curve_corset()
        brace = bpy.data.objects.get("Rigo Corset")

        closed = _open_boundary_edges(brace) == 0 if brace else False
        band_count, band_max = _group_members(brace, _BAND_GROUP) if brace else (0, 0.0)
        rim_count, _rim_max = (
            _group_members(brace, "RIGO_RIM_BOUNDARY") if brace else (0, 0.0)
        )
        lines.append(
            f"generate={generate_result} closed_shell={closed} "
            f"rim_marker_verts={rim_count} band_verts={band_count} "
            f"band_max_weight={band_max:.4f}"
        )

        # The band must be a feather, not a flat marker: some vertex should sit
        # at full weight on the rim and others part-way in.
        feathered = 0.0 < band_max <= 1.0 and band_count > rim_count

        before = _vertex_positions(brace) if brace else []
        try:
            smooth_result = bpy.ops.rigo.smooth_trim_edge()
            smooth_error = ""
        except RuntimeError as error:
            smooth_result = {"CANCELLED"}
            smooth_error = str(error)
        after = _vertex_positions(brace) if brace else []
        moved = sum(
            1
            for a, b in zip(before, after)
            if (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2 > 1e-14
        )
        lines.append(
            f"smooth_trim_edge={smooth_result} moved_vertices={moved} "
            f"error={smooth_error!r}"
        )

        # Vents read the same group to stay clear of the rim.
        from bl_ext.user_default.rigo_brace.operators.vent_ops import (
            _band_weight_lookup,
        )

        vent_lookup = _band_weight_lookup(brace) if brace else {}
        lines.append(f"vent_band_lookup_entries={len(vent_lookup)}")

        passed = (
            generate_result == {"FINISHED"}
            and brace is not None
            and closed
            and band_count > 0
            and feathered
            and smooth_result == {"FINISHED"}
            and moved > 0
            and len(vent_lookup) > 0
        )
        lines.append(f"PASS={passed}")
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}\nPASS=False")
    _write(lines)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
