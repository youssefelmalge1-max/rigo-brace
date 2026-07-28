"""#46 EVIDENCE-ONLY prototype: validate and repair the WHOLE shell after the
rim fan exists.

Production order A          existing wall repair -> rim -> validate
Prototype order B          existing wall repair -> rim -> full-shell detect ->
                           local post-rim repair -> validate
Order C (bounded)          detect -> repair -> detect ... until zero, until no
                           measurable progress, or a hard iteration limit.

The existing pre-rim outer-wall repair is NOT removed; this runs after it.

REPAIR RULE. Only the per-station rim RADIUS is reduced, and only at stations
whose fan is involved in an intersection. `_rim_profile` builds a profile as
[inner wall vertex, ...interior points..., outer wall vertex], and only the
interior points are new indices >= 2*vertex_count. Changing a radius therefore
moves rim-fan points ONLY - the patient-contact inner wall and the outer wall
cannot move, by construction, and the clearance is never touched. That is
checked and reported, not assumed.

This does NOT raise the rim-radius ceiling (#47 unchanged); it only ever
lowers a delivered radius that is already far below the request.

Usage: blender --python postrimrepairdbg.py -- <a17|a24|none> <label>
"""

import math
import sys
import traceback

import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Projects\Blender Add-on Braces\tools")
from bracefixture import prepare_reference_design  # noqa: E402

from bl_ext.user_default.rigo_brace.operators import (  # noqa: E402
    curve_build_ops,
    design_ops,
    mesh_intersections,
)

OUT = r"C:\Projects\Blender Add-on Braces\postrimrepairdbg"
ARCS = {"a17": (17, 21), "a24": (24, 30), "none": None}
MAX_PASSES = 6
SHRINK = 0.6           # (retired: radius shrink was falsified)
CLEARANCE_MARGIN = 0.00005   # 0.05 mm clear of the inner wall
FRAME_VOTE_TOLERANCE = 0.0   # correct a station only if its own vote disagrees
NEIGHBOUR_SPAN = 2     # also relax immediate neighbours, matching the smoothing
TRIES = {"n": 0}
LINES = []
STATE = {}

_original_geometry = curve_build_ops._shell_geometry


def _triangulate(faces):
    triangles = []
    for face in faces:
        for corner in range(1, len(face) - 1):
            triangles.append((face[0], face[corner], face[corner + 1]))
    return triangles


def _classify(indices, vertex_count):
    kinds = set()
    for index in indices:
        if index < vertex_count:
            kinds.add("inner")
        elif index < 2 * vertex_count:
            kinds.add("outer")
        else:
            kinds.add("rim")
    return "+".join(sorted(kinds))


def _detect(coordinates, faces):
    triangles = _triangulate(faces)
    pairs = mesh_intersections.triangle_intersection_pairs(
        coordinates, triangles
    )
    return pairs, triangles


def _stations_of(pair, triangles, rim_owner, vertex_count, boundary_vertices):
    """Which boundary stations does this offending pair implicate?"""
    stations = set()
    for triangle_index in pair:
        for index in triangles[triangle_index]:
            if index >= 2 * vertex_count:
                owner = rim_owner.get(index)
                if owner is not None:
                    stations.add(owner)
            else:
                base = index if index < vertex_count else index - vertex_count
                if base in boundary_vertices:
                    stations.add(base)
    return stations


def _geometry_metrics(before, after, vertex_count):
    """Displacement split by provenance. Inner wall MUST be exactly zero."""
    inner_max = inner_sq = 0.0
    outer_max = 0.0
    rim_max = rim_sq = 0.0
    moved = 0
    shared = min(len(before), len(after))
    for index in range(shared):
        delta = (after[index] - before[index]).length
        if delta > 0.0:
            moved += 1
        if index < vertex_count:
            inner_max = max(inner_max, delta)
            inner_sq += delta * delta
        elif index < 2 * vertex_count:
            outer_max = max(outer_max, delta)
        else:
            rim_max = max(rim_max, delta)
            rim_sq += delta * delta
    rim_count = max(1, shared - 2 * vertex_count)
    return {
        "moved_vertices": moved,
        "inner_max_mm": inner_max * 1000.0,
        "inner_rms_mm": math.sqrt(inner_sq / max(1, vertex_count)) * 1000.0,
        "outer_max_mm": outer_max * 1000.0,
        "rim_max_mm": rim_max * 1000.0,
        "rim_rms_mm": math.sqrt(rim_sq / rim_count) * 1000.0,
        "vertex_count_before": len(before),
        "vertex_count_after": len(after),
    }


def _mesh_health(coordinates, faces, vertex_count):
    """Degenerate/inverted triangles, edge manifoldness, watertightness."""
    triangles = _triangulate(faces)
    degenerate = 0
    areas = []
    for tri in triangles:
        a, b, c = (coordinates[i] for i in tri)
        area = (b - a).cross(c - a).length * 0.5
        areas.append(area)
        if area <= 1.0e-14:
            degenerate += 1
    edges = {}
    for face in faces:
        count = len(face)
        for corner in range(count):
            key = tuple(sorted((face[corner], face[(corner + 1) % count])))
            edges[key] = edges.get(key, 0) + 1
    boundary = sum(1 for n in edges.values() if n == 1)
    nonmanifold = sum(1 for n in edges.values() if n > 2)
    return {
        "faces": len(faces),
        "triangles": len(triangles),
        "degenerate_triangles": degenerate,
        "min_triangle_area_mm2": min(areas, default=0.0) * 1.0e6,
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "watertight": boundary == 0 and nonmanifold == 0,
    }


def _min_wall_thickness_mm(coordinates, vertex_count):
    worst = math.inf
    for index in range(vertex_count):
        worst = min(
            worst,
            (coordinates[index + vertex_count] - coordinates[index]).length,
        )
    return worst * 1000.0


def _prototype_geometry(source, settings, topology):
    """Order B / C: build as production does, then detect and repair."""
    thickness = settings.corset_thickness * 0.001
    coordinates, repair = design_ops._paired_coordinates(
        source, topology.triangles, thickness
    )
    requested = settings.trim_fillet_radius * 0.001
    radius = min(requested, thickness * 0.45)

    directions = curve_build_ops._stable_outward_directions(
        coordinates, topology.triangles, topology.boundary,
        topology.vertex_count,
    )
    radii = curve_build_ops._safe_rim_radii(
        coordinates, topology.boundary, radius
    )
    # ---- CANDIDATE FIX: per-station frame correction.
    # `_stable_outward_directions` decides orientation by a GLOBAL majority
    # vote and deliberately prevents any single vertex from inverting its own
    # frame. Measured: the failing arc has exactly ONE station (26116) whose
    # local vote says its frame points INTO the surface, and the passing arc
    # has none. Such a station builds its fan bulging into the wall, so its
    # first quad folds over the adjacent wall triangle at ANY radius - which
    # is why shrinking the radius and lifting the fan points both changed
    # nothing. Correct only those stations, leaving the global decision alone.
    adjacency = design_ops._vertex_adjacency(
        topology.vertex_count, topology.triangles
    )
    inner_coords = coordinates[: topology.vertex_count]
    corrected = []
    for station, outward in directions.items():
        normal = (
            coordinates[station + topology.vertex_count] - coordinates[station]
        )
        if normal.length <= 1.0e-12:
            continue
        normal = normal.normalized()
        interior = Vector()
        for neighbour in adjacency[station]:
            interior += inner_coords[neighbour] - inner_coords[station]
        interior -= normal * interior.dot(normal)
        if interior.length <= 1.0e-12:
            continue
        if outward.dot(interior.normalized()) > FRAME_VOTE_TOLERANCE:
            directions[station] = -outward
            corrected.append(station)
    STATE["frame_corrected"] = corrected

    curve_build_ops._corner_spike_limits(directions, radii, topology.boundary)
    baseline_radii = dict(radii)
    boundary_vertices = {i for edge in topology.boundary for i in edge}
    # adjacency straight from the boundary edge pairs. `design_ops.
    # _boundary_neighbours` wants a bmesh, not a tuple of index pairs.
    neighbours = {}
    for first, second in topology.boundary:
        neighbours.setdefault(first, set()).add(second)
        neighbours.setdefault(second, set()).add(first)

    wall_coordinates = list(coordinates[: 2 * topology.vertex_count])
    STATE["passes"] = []
    STATE["baseline_radii"] = baseline_radii

    from mathutils.bvhtree import BVHTree

    inner_tree = BVHTree.FromPolygons(
        [c.copy() for c in coordinates[: topology.vertex_count]],
        [tuple(t) for t in topology.triangles],
        all_triangles=True, epsilon=0.0,
    )
    previous_count = None
    carried = None
    for attempt in range(MAX_PASSES):
        build = list(carried) if carried is not None else list(wall_coordinates)
        if carried is not None:
            # keep the repaired positions from the previous pass; the profile
            # index layout is unchanged because no points are added or removed
            profiles = STATE["carried_profiles"]
        else:
            profiles = {
                index: curve_build_ops._rim_profile(
                    build, topology,
                    curve_build_ops._RimVertex(
                        index, directions[index], radii[index]
                    ),
                )
                for index in directions
            }
            STATE["carried_profiles"] = profiles
        faces = curve_build_ops._rounded_shell_faces(topology, profiles)
        rim_owner = {}
        for station, profile in profiles.items():
            for point in profile[1:-1]:
                rim_owner[point] = station

        pairs, triangles = _detect(build, faces)
        record = {
            "pass": attempt,
            "intersections": len(pairs),
            "classes": {},
            "stations": set(),
            "recurring_vertices": {},
        }
        for pair in pairs:
            name = " vs ".join(sorted((
                _classify(triangles[pair[0]], topology.vertex_count),
                _classify(triangles[pair[1]], topology.vertex_count),
            )))
            record["classes"][name] = record["classes"].get(name, 0) + 1
            for triangle_index in pair:
                for index in triangles[triangle_index]:
                    record["recurring_vertices"][index] = (
                        record["recurring_vertices"].get(index, 0) + 1
                    )
            record["stations"] |= _stations_of(
                pair, triangles, rim_owner, topology.vertex_count,
                boundary_vertices,
            )
        record["health"] = _mesh_health(build, faces, topology.vertex_count)
        record["min_wall_mm"] = _min_wall_thickness_mm(
            build, topology.vertex_count
        )
        record["delivered_max_mm"] = max(radii.values()) * 1000.0
        record["delivered_mean_mm"] = (
            sum(radii.values()) / max(1, len(radii)) * 1000.0
        )
        STATE["passes"].append(record)

        if not pairs:
            STATE["final"] = (build, faces, radii, profiles)
            return build, faces, radii, repair
        if previous_count is not None and len(pairs) >= previous_count:
            # no measurable progress - stop rather than loop
            record["stopped"] = "no progress"
            STATE["final"] = (build, faces, radii, profiles)
            return build, faces, radii, repair
        previous_count = len(pairs)

        # LOCAL REPAIR: lift fan points clear of the inner wall.
        #
        # Shrinking the radius was tried first and FALSIFIED: it moved 98 rim
        # vertices (max 0.312mm) and left the intersection set byte-identical,
        # because `_rim_profile` starts the cap TANGENT to the wall and
        # tangency is radius-independent. The measured cause is a single
        # station whose first fan point sits 0.071mm BELOW the inner wall
        # (1/2232 in the failing case, 0/2234 in the passing one), so the
        # repair variable is CLEARANCE, not radius. Only rim points move.
        lifted = 0
        max_lift = 0.0
        for station in record["stations"]:
            profile = profiles.get(station)
            if not profile:
                continue
            for point_index in profile[1:-1]:
                point = build[point_index]
                location, normal, _i, _d = inner_tree.find_nearest(point)
                if location is None:
                    continue
                clearance = (point - location).dot(normal)
                if clearance < CLEARANCE_MARGIN:
                    shift = (CLEARANCE_MARGIN - clearance)
                    build[point_index] = point + normal * shift
                    lifted += 1
                    max_lift = max(max_lift, shift)
        record["repaired_stations"] = len(record["stations"])
        record["lifted_points"] = lifted
        record["max_lift_mm"] = max_lift * 1000.0
        carried = build

    STATE["final"] = (build, faces, radii, profiles)
    return build, faces, radii, repair


def _profiles_of(coordinates, topology, directions, radii):
    """Rebuild the profiles on a scratch copy, so indices match `coordinates`."""
    build = list(coordinates[: 2 * topology.vertex_count])
    profiles = {}
    for index in directions:
        profiles[index] = curve_build_ops._rim_profile(
            build, topology,
            curve_build_ops._RimVertex(index, directions[index], radii[index]),
        )
    # the scratch build reproduces the same appended order as production, so
    # profile indices address `build`, not the caller's list
    for station, profile in profiles.items():
        profiles[station] = profile
    _profiles_of.build = build
    return profiles


def _run():
    TRIES["n"] += 1
    if not hasattr(bpy.types, "RIGO_PT_main") and TRIES["n"] < 40:
        return 0.1
    key = sys.argv[-2] if len(sys.argv) >= 2 else "a17"
    label = sys.argv[-1]
    arc = ARCS.get(key)
    base = corset = None
    try:
        prepare_reference_design()
        settings = bpy.context.scene.rigo_brace
        bpy.ops.rigo.auto_trimline()
        curve = bpy.data.objects["Rigo Trim Perimeter"]
        if arc is not None:
            for index, point in enumerate(curve.data.splines[0].bezier_points):
                point.select_control_point = arc[0] <= index <= arc[1]
            bpy.ops.rigo.smooth_trimline("INVOKE_DEFAULT", mode="SMOOTH_ARC")
        LINES.append(
            f"CASE {key} arc={arc} [{label}] fillet requested="
            f"{settings.trim_fillet_radius:.2f}mm segments="
            f"{settings.trim_fillet_segments} thickness="
            f"{settings.corset_thickness:.2f}mm"
        )
        LINES.append(f"  MAX_PASSES={MAX_PASSES} SHRINK={SHRINK} "
                     f"NEIGHBOUR_SPAN={NEIGHBOUR_SPAN}")

        # ---------- order A: production, for the before picture
        scan = settings.scan_object
        base = design_ops._prepare_candidate_base(bpy.context, scan, settings)
        corset = curve_build_ops._new_brace_candidate(bpy.context, base)
        projected = curve_build_ops._projected_perimeter(corset, curve)
        retained = curve_build_ops._retained_region(settings, curve, projected)
        curve_build_ops._cut_surface(
            bpy.context, corset, projected, retained, settings
        )
        topology = curve_build_ops._shell_topology(corset.data, settings)
        coordinates_a, faces_a, radii_a, _repair_a = _original_geometry(
            corset.data, settings, topology
        )
        pairs_a, triangles_a = _detect(coordinates_a, faces_a)
        health_a = _mesh_health(coordinates_a, faces_a, topology.vertex_count)
        LINES.append("")
        LINES.append("  ORDER A (production: wall repair -> rim -> validate)")
        LINES.append(f"     intersections={len(pairs_a)}")
        classes_a = {}
        for pair in pairs_a:
            name = " vs ".join(sorted((
                _classify(triangles_a[pair[0]], topology.vertex_count),
                _classify(triangles_a[pair[1]], topology.vertex_count),
            )))
            classes_a[name] = classes_a.get(name, 0) + 1
        LINES.append(f"     classes={classes_a}")
        LINES.append(f"     health={health_a}")
        LINES.append(
            f"     delivered fillet max={max(radii_a.values())*1000:.4f}mm "
            f"mean={sum(radii_a.values())/len(radii_a)*1000:.4f}mm"
        )
        LINES.append(
            f"     min wall thickness="
            f"{_min_wall_thickness_mm(coordinates_a, topology.vertex_count):.4f}mm"
        )

        # ---------- is the RIM the cause, or only the messenger?
        # Shrinking the offending stations' radii moved 98 rim vertices and
        # changed nothing about the intersection set, so test whether the
        # surfaces the fan is anchored to are already bad on their own.
        LINES.append("")
        LINES.append("  UPSTREAM CHECK (are the walls self-intersecting "
                     "before the rim exists?)")
        vertex_count = topology.vertex_count
        cut_pairs = mesh_intersections.triangle_intersection_pairs(
            [c.copy() for c in coordinates_a[:vertex_count]],
            list(topology.triangles),
        )
        LINES.append(f"     inner wall alone: {len(cut_pairs)} self-intersections")
        outer_coords = [c.copy() for c in coordinates_a[vertex_count:2 * vertex_count]]
        outer_pairs = mesh_intersections.triangle_intersection_pairs(
            outer_coords, list(topology.triangles)
        )
        LINES.append(f"     outer wall alone: {len(outer_pairs)} self-intersections")
        walls_only = [c.copy() for c in coordinates_a[:2 * vertex_count]]
        wall_faces = [
            (face[0], *reversed(face[1:])) for face in topology.surface_faces
        ] + [
            tuple(i + vertex_count for i in face)
            for face in topology.surface_faces
        ]
        both_pairs, both_tris = _detect(walls_only, wall_faces)
        LINES.append(
            f"     inner+outer together (no rim): {len(both_pairs)} "
            "intersections"
        )
        if both_pairs:
            classes_w = {}
            for pair in both_pairs:
                name = " vs ".join(sorted((
                    _classify(both_tris[pair[0]], vertex_count),
                    _classify(both_tris[pair[1]], vertex_count),
                )))
                classes_w[name] = classes_w.get(name, 0) + 1
            LINES.append(f"     wall-only classes={classes_w}")

        # ---------- FRAME ORIENTATION at the implicated stations
        # The walls are clean and shrinking the radius changes nothing, so the
        # fan must be leaving its station in the wrong direction: an inward
        # `outward` vector collides with the wall at ANY positive radius.
        LINES.append("")
        LINES.append("  FRAME DIRECTION CHECK")
        directions_a = curve_build_ops._stable_outward_directions(
            coordinates_a, topology.triangles, topology.boundary, vertex_count
        )
        ring = curve_build_ops._ordered_boundary_ring(topology.boundary)
        flips = []
        for position, station in enumerate(ring):
            nxt = ring[(position + 1) % len(ring)]
            if station in directions_a and nxt in directions_a:
                dot = directions_a[station].dot(directions_a[nxt])
                if dot < 0.0:
                    flips.append((station, nxt, dot))
        LINES.append(
            f"     ring length={len(ring)} neighbour-to-neighbour outward "
            f"sign flips={len(flips)}"
        )
        for station, nxt, dot in flips[:10]:
            LINES.append(f"        flip {station} -> {nxt}: dot={dot:+.4f}")
        implicated = sorted(STATE.get("implicated_preview", []))
        # measure the fan direction against the local wall normal
        suspicious = []
        for station in directions_a:
            normal = (
                coordinates_a[station + vertex_count] - coordinates_a[station]
            )
            if normal.length <= 1e-12:
                continue
            normal.normalize()
            align = abs(directions_a[station].dot(normal))
            if align > 0.30:
                suspicious.append((station, align))
        suspicious.sort(key=lambda kv: -kv[1])
        LINES.append(
            f"     stations whose outward is NOT perpendicular to the wall "
            f"(|dot| > 0.30): {len(suspicious)}"
        )
        for station, align in suspicious[:10]:
            LINES.append(f"        station {station}: |outward.normal|={align:.4f}")

        # ---------- TANGENT-START vs LOCAL CONCAVITY
        # `_rim_profile`'s docstring: each quarter arc leaves its wall along
        # +/- `outward`, so the cap is TANGENT at both ends - "concave overlap
        # is left for the exact validator to judge". A tangent start is
        # radius-independent, which is exactly why shrinking the radius moved
        # 98 vertices and changed nothing. Where the wall is locally CONCAVE
        # toward `outward`, the first fan point must dip below the wall.
        from mathutils.bvhtree import BVHTree

        LINES.append("")
        LINES.append("  TANGENT-START vs WALL CONCAVITY")
        inner_tree = BVHTree.FromPolygons(
            [c.copy() for c in coordinates_a[:vertex_count]],
            [tuple(t) for t in topology.triangles],
            all_triangles=True, epsilon=0.0,
        )
        implicated_stations = {24499, 24500, 24501, 24746, 25200, 26116}
        depths = {}
        for station, profile in _profiles_of(
            coordinates_a, topology, directions_a, radii_a
        ).items():
            if len(profile) < 3:
                continue
            first_point = _profiles_of.build[profile[1]]
            location, normal, _i, _d = inner_tree.find_nearest(first_point)
            if location is None:
                continue
            # positive = clear of the inner wall, negative = dipped below it
            depths[station] = (first_point - location).dot(normal) * 1000.0
        if depths:
            ordered = sorted(depths.values())
            below = sum(1 for v in depths.values() if v < 0.0)
            LINES.append(
                f"     first fan point vs inner wall: min={ordered[0]:+.5f}mm "
                f"p01={ordered[len(ordered)//100]:+.5f}mm "
                f"median={ordered[len(ordered)//2]:+.5f}mm "
                f"max={ordered[-1]:+.5f}mm; BELOW the wall={below}/{len(depths)}"
            )
            for station in sorted(implicated_stations):
                if station in depths:
                    LINES.append(
                        f"        implicated station {station}: "
                        f"{depths[station]:+.5f}mm"
                    )

        # ---------- PER-STATION frame vote
        # `_stable_outward_directions` sums `outward.dot(interior)` over the
        # WHOLE loop into one `votes` and flips every frame together. Its
        # docstring says that is deliberate: "A single ambiguous vertex can
        # then no longer invert its own frame." The consequence is that a
        # station whose LOCAL vote disagrees keeps a frame pointing INTO the
        # surface, and its first fan quad then folds over the adjacent wall
        # triangle - which is exactly the `inner vs inner+rim` signature.
        LINES.append("")
        LINES.append("  PER-STATION FRAME VOTE (positive = outward points INTO "
                     "the surface)")
        adjacency = design_ops._vertex_adjacency(
            vertex_count, topology.triangles
        )
        inner_coords = coordinates_a[:vertex_count]
        wrong = []
        for station, outward in directions_a.items():
            normal = (
                coordinates_a[station + vertex_count] - coordinates_a[station]
            )
            if normal.length <= 1e-12:
                continue
            normal = normal.normalized()
            interior = Vector()
            for neighbour in adjacency[station]:
                interior += inner_coords[neighbour] - inner_coords[station]
            interior -= normal * interior.dot(normal)
            if interior.length <= 1e-12:
                continue
            vote = outward.dot(interior.normalized())
            if vote > 0.0:
                wrong.append((station, vote))
        wrong.sort(key=lambda kv: -kv[1])
        LINES.append(
            f"     stations whose frame points INTO the surface: "
            f"{len(wrong)}/{len(directions_a)}"
        )
        for station, vote in wrong[:12]:
            marker = " <-- IMPLICATED" if station in {
                24499, 24500, 24501, 24746, 25200, 26116
            } else ""
            LINES.append(f"        station {station}: vote=+{vote:.4f}{marker}")

        # ---------- order B / C: prototype
        coordinates_b, faces_b, radii_b, _repair_b = _prototype_geometry(
            corset.data, settings, topology
        )
        LINES.append("")
        LINES.append("  ORDER B/C (per-station frame correction + post-rim "
                     "detect/repair)")
        LINES.append(
            f"     frame-corrected stations={STATE.get('frame_corrected')}"
        )
        for record in STATE["passes"]:
            LINES.append(
                f"     PASS {record['pass']}: intersections="
                f"{record['intersections']} classes={record['classes']}"
            )
            if record["intersections"]:
                recurring = sorted(
                    record["recurring_vertices"].items(),
                    key=lambda kv: -kv[1],
                )[:6]
                LINES.append(
                    f"        stations implicated={sorted(record['stations'])} "
                    f"recurring vertices={recurring}"
                )
                LINES.append(
                    f"        repaired stations={record.get('repaired_stations', 0)} "
                    f"lifted points={record.get('lifted_points', 0)} "
                    f"max lift={record.get('max_lift_mm', 0.0):.5f}mm"
                )
            LINES.append(
                f"        delivered fillet max="
                f"{record['delivered_max_mm']:.4f}mm mean="
                f"{record['delivered_mean_mm']:.4f}mm  min wall="
                f"{record['min_wall_mm']:.4f}mm"
            )
            LINES.append(f"        health={record['health']}")
            if record.get("stopped"):
                LINES.append(f"        STOPPED: {record['stopped']}")

        metrics = _geometry_metrics(
            coordinates_a, coordinates_b, topology.vertex_count
        )
        LINES.append("")
        LINES.append("  A -> B GEOMETRY DELTA")
        LINES.append(f"     {metrics}")
        LINES.append(
            f"     PATIENT-CONTACT INNER WALL MOVED: "
            f"{metrics['inner_max_mm'] > 0.0} "
            f"(max {metrics['inner_max_mm']:.9f}mm)"
        )
        LINES.append(
            f"     OUTER WALL MOVED: {metrics['outer_max_mm'] > 0.0} "
            f"(max {metrics['outer_max_mm']:.9f}mm)"
        )
        shrunk = sum(
            1 for k, v in radii_b.items()
            if v < STATE["baseline_radii"].get(k, v) - 1e-12
        )
        LINES.append(
            f"     stations whose delivered radius was reduced={shrunk}"
            f"/{len(radii_b)}"
        )
        final_pairs = STATE["passes"][-1]["intersections"]
        LINES.append("")
        LINES.append(
            f"  RESULT: order A intersections={len(pairs_a)} -> "
            f"order B/C intersections={final_pairs} "
            f"in {len(STATE['passes'])} pass(es)"
        )
    except Exception as error:  # noqa: BLE001
        LINES.append(f"ERROR={error!r}\n{traceback.format_exc()}")
    finally:
        for obj in (corset, base):
            if obj is not None and design_ops._object_is_registered(obj):
                design_ops._remove_object_and_orphan_mesh(obj)
    with open(f"{OUT}_{label}_{key}.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(LINES))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(_run, first_interval=0.5)
