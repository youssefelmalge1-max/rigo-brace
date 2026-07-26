"""Why does the rim silhouette still facet at tight corners?

Ranks the boundary ring by how hard it turns, then reports for the worst
regions everything that could be responsible: the delivered radius and WHICH
ceiling produced it, the chords allocated to each quarter arc, the boundary
spacing, the per-edge turn angle (which is what a silhouette actually shows),
the deviation of the polyline from a smoothed version of itself, and the
local triangle quality.
"""

import math
import statistics
import sys
import traceback

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
)

OUT = r"C:\Projects\Blender Add-on Braces\rimcornerdbg_result.txt"
TRIES = {"n": 0}
CAP = {}
WORST = 12

_orig_profiles = curve_build_ops._rim_profiles
_orig_safe = curve_build_ops._safe_rim_radii


def _safe_spy(coordinates, boundary, requested):
    radii = _orig_safe(coordinates, boundary, requested)
    if "ceilings" not in CAP:
        # Recompute each ceiling separately so we can say which one BINDS.
        linked = curve_build_ops._boundary_neighbours(boundary)
        spacing_ceiling, spacings = {}, {}
        for index, neighbours in linked.items():
            spacing = min(
                (coordinates[index] - coordinates[neighbour]).length
                for neighbour in neighbours
            )
            spacings[index] = spacing
            spacing_ceiling[index] = (
                curve_build_ops._RIM_SPACING_RADIUS_CEILING * spacing
            )
        turn_ceiling, turns = {}, {}
        ring = curve_build_ops._ordered_boundary_ring(boundary)
        for position, index in enumerate(ring):
            turn = curve_build_ops._local_turn_radius(
                coordinates, ring, position
            )
            turns[index] = turn
            turn_ceiling[index] = 0.5 * turn
        CAP.update(
            ceilings=dict(radii),
            requested=requested,
            spacing_ceiling=spacing_ceiling,
            spacings=spacings,
            turn_ceiling=turn_ceiling,
            turns=turns,
            ring=ring,
            coords=[c.copy() for c in coordinates],
        )
    return radii


def _profiles_spy(coordinates, topology, radius):
    profiles, radii = _orig_profiles(coordinates, topology, radius)
    CAP.setdefault("segments", topology.segments)
    CAP.setdefault("vertex_count", topology.vertex_count)
    CAP.setdefault("profiles", {k: list(v) for k, v in profiles.items()})
    return profiles, radii


def _smoothed(points, passes=6):
    smooth = [p.copy() for p in points]
    count = len(smooth)
    for _ in range(passes):
        smooth = [
            (smooth[i - 1] + smooth[(i + 1) % count] + smooth[i] * 2.0) * 0.25
            for i in range(count)
        ]
    return smooth


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 30:
        return 0.1
    lines = []
    try:
        curve_build_ops._safe_rim_radii = _safe_spy
        curve_build_ops._rim_profiles = _profiles_spy
        scan, settings = prepare_reference_design()
        settings.corset_thickness = 4.0
        settings.corset_offset = 3.0
        result = bpy.ops.rigo.generate_curve_corset()
        lines.append(
            f"generate={result} segments={CAP.get('segments')} "
            f"requested_mm={CAP.get('requested', 0) * 1000:.3f}"
        )

        thickness = settings.corset_thickness * 0.001
        radii = CAP["ceilings"]
        ring = CAP["ring"]
        coords = CAP["coords"]
        count = len(ring)

        # 4 - chord allocation, which is global unless the flat vanishes.
        segments = CAP["segments"]
        with_flat = curve_build_ops._cap_chord_budget(segments, True)
        without = curve_build_ops._cap_chord_budget(segments, False)
        lines.append(
            f"chord budget: with_flat={with_flat} (arc chords "
            f"{with_flat[0]}/{with_flat[2]}, junction "
            f"{45.0 / max(1, with_flat[0]):.1f} deg) "
            f"no_flat={without} (junction {45.0 / max(1, without[0]):.1f} deg)"
        )
        flatless = sum(
            1 for r in radii.values() if thickness - 2.0 * r <= 1.0e-9
        )
        lines.append(
            f"rim points whose cap loses its flat (r >= t/2): {flatless}"
            f"/{len(radii)}"
        )

        # 6 - per-edge turn angle along the ring IS the silhouette faceting.
        turn_angle = {}
        for position, index in enumerate(ring):
            before = coords[ring[position - 1]]
            here = coords[index]
            after = coords[ring[(position + 1) % count]]
            entering, leaving = here - before, after - here
            if min(entering.length, leaving.length) > 1.0e-12:
                turn_angle[index] = math.degrees(entering.angle(leaving))
        values = sorted(turn_angle.values())
        lines.append(
            f"ring edge turn angle (deg): median={values[len(values)//2]:.2f} "
            f"p95={values[int(0.95*(len(values)-1))]:.2f} max={values[-1]:.2f}"
        )

        # 3 - silhouette deviation: polyline against a smoothed copy.
        smooth = _smoothed([coords[i] for i in ring])
        deviation = {
            index: (coords[index] - smooth[position]).length
            for position, index in enumerate(ring)
        }
        dev = sorted(deviation.values())
        lines.append(
            f"silhouette deviation (mm): median={dev[len(dev)//2]*1000:.4f} "
            f"p95={dev[int(0.95*(len(dev)-1))]*1000:.4f} "
            f"max={dev[-1]*1000:.4f}"
        )

        # 7 - local triangle quality near the rim
        brace = bpy.data.objects.get("Rigo Corset")
        bm = bmesh.new()
        bm.from_mesh(brace.data)
        group = brace.vertex_groups.get(design_ops._RIM_BOUNDARY_GROUP)
        rim_indices = {
            v.index
            for v in brace.data.vertices
            if any(e.group == group.index for e in v.groups)
        }
        bm.verts.index_update()
        rim_faces = [
            face
            for face in bm.faces
            if any(v.index in rim_indices for v in face.verts)
        ]
        aspects = sorted(
            max(el) / min(el)
            for f in rim_faces
            for el in [[e.calc_length() for e in f.edges]]
            if min(el) > 1e-12
        )
        shortest = min(
            e.calc_length()
            for f in rim_faces
            for e in f.edges
        )
        bm.free()
        lines.append(
            f"rim-local triangles: n={len(rim_faces)} "
            f"aspect_p95={aspects[int(0.95*(len(aspects)-1))]:.2f} "
            f"p99={aspects[int(0.99*(len(aspects)-1))]:.2f} "
            f"max={aspects[-1]:.2f} min_edge_mm={shortest*1000:.4f}"
        )

        # 1/2/5 - the worst-turning locations, with the binding ceiling named
        lines.append("")
        lines.append(
            "WORST-TURNING RIM POINTS "
            "(turn=per-edge silhouette angle, dev=deviation from smooth)"
        )
        lines.append(
            "  turn°  dev_mm  radius_mm  binds        spacing_mm  turnR_mm  "
            "location"
        )
        ranked = sorted(
            turn_angle.items(), key=lambda item: -item[1]
        )[:WORST]
        for index, angle in ranked:
            radius = radii.get(index, 0.0)
            spacing_c = CAP["spacing_ceiling"].get(index, math.inf)
            turn_c = CAP["turn_ceiling"].get(index, math.inf)
            request = CAP["requested"]
            binds = min(
                (abs(radius - request), "request"),
                (abs(radius - spacing_c), "spacing"),
                (abs(radius - turn_c), "curvature"),
            )[1]
            turn_r = CAP["turns"].get(index, math.inf)
            point = coords[index]
            lines.append(
                f"  {angle:5.1f}  {deviation[index]*1000:6.3f}  "
                f"{radius*1000:8.3f}  {binds:11s}  "
                f"{CAP['spacings'].get(index, 0)*1000:9.3f}  "
                f"{(turn_r*1000 if turn_r < math.inf else -1):8.2f}  "
                f"({point.x:.3f},{point.y:.3f},{point.z:.3f})"
            )

        binding = {}
        for index, radius in radii.items():
            request = CAP["requested"]
            spacing_c = CAP["spacing_ceiling"].get(index, math.inf)
            turn_c = CAP["turn_ceiling"].get(index, math.inf)
            name = min(
                (abs(radius - request), "request"),
                (abs(radius - spacing_c), "spacing"),
                (abs(radius - turn_c), "curvature"),
            )[1]
            binding[name] = binding.get(name, 0) + 1
        lines.append("")
        lines.append(f"which ceiling binds, whole rim: {binding}")
        lines.append(
            f"delivered radius (mm): min={min(radii.values())*1000:.3f} "
            f"median={statistics.median(radii.values())*1000:.3f} "
            f"max={max(radii.values())*1000:.3f}"
        )
    except Exception as error:  # noqa: BLE001
        lines.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    finally:
        curve_build_ops._safe_rim_radii = _orig_safe
        curve_build_ops._rim_profiles = _orig_profiles
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
