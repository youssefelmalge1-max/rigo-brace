# Blender Capabilities (how Blender replaces external orthotic CAD tasks)

How each orthotic CAD task maps to Blender, with the API/operator we use.

## Mesh tools (Edit Mode / bmesh)
- Region select: face/vert select, circle/box/lasso; `bmesh.from_edit_mesh`.
- Shape: `transform.shrink_fatten` (push/pull along normals, mm), proportional edit
  (smooth dome), `mesh.vertices_smooth`, `mesh.subdivide`.
- Cleanup: `mesh.fill_holes`, `mesh.remove_doubles`/`bmesh.ops.remove_doubles`,
  `mesh.normals_make_consistent`, `mesh.separate`/`select_linked` (islands),
  `mesh.delete` (cut), `mesh.dissolve_*`.

## Modifiers (non-destructive shaping)
- `REMESH` (voxel) — controllable retopo of a raw scan (Clean stage Auto-Remesh).
- `SOLIDIFY` — wall thickness; `thickness_vertex_group` ratio = variable thickness.
- `MASK` — restrict another modifier to a vertex group.
- `LATTICE` — cage deformation (correction / derotation).
- `SIMPLE_DEFORM` — Bend (axis Y) / Twist / Stretch (Z + lock_x/y).
- `CORRECTIVE_SMOOTH` on a vertex group — one-button curve/trimline smoothing.
- `BOOLEAN` — slots, ventilation holes, crop/trim, emboss.
- `DISPLACE` (NORMAL) — liner-gap offset.
- `SHRINKWRAP` — project a shape/curve onto the scan surface.

## Sculpt (Blender 5)
Sculpt Mode brushes (Draw/Grab/Smooth/Flatten) for free shaping; vertex-color or
mask to scope region edits; we combine this Free mode with uFit's measurable Guided
push/pull.

## Curves
Bezier outline (trim line / pad shape) with editable control points + handles;
`mathutils.geometry.interpolate_bezier` to sample; `bevel_depth` for a visible tube.

## Drivers / live UI
SCRIPTED drivers tie helper-object transforms to modifier values (the active pair among
three deform rings). PropertyGroup `update=` callbacks live-drive modifiers from sliders.

## Geometry / math (mathutils, numpy)
`matrix_world` transforms; vertex normals; `kdtree` (nearest/feather distance);
`Vector`/`Matrix`; Newell normal for best-fit planes; raycast (`scene.ray_cast`,
`object.ray_cast`, `closest_point_on_mesh`) for placing things on the surface.

## View / UX
Quad view (`screen.region_quadview`), fullscreen (`screen.screen_full_area`), fixed
angles (`view3d.view_axis`), X-ray shading (`space.shading.show_xray`), object color
shading, image-empty overlays (X-ray radiograph), `previews` for icons/assist images.

## IO
STL/OBJ import/export via `wm.stl_import` / `wm.obj_import` / export ops; units via
`scene.unit_settings` (METRIC / MILLIMETERS).

## Persistence
`bpy.utils.user_resource("CONFIG", ...)` for per-PC libraries (pad library json);
custom properties on objects for per-object state (history stage, pad params).
