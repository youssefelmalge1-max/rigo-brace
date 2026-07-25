# Mesh Processing Playbook

Recipes for the geometry operations the brace pipeline relies on, with the gotchas we
already hit (cross-ref learned_memory.md LM-xxxx).

## Import & units
Raw scans arrive in mm or cm → import gives a model hundreds of BU tall. Apply Units
scales `*0.001` (mm) etc., then **re-frame the viewport** (LM-0001) — a rescale doesn't
move the camera, so a correct-size model looks "gone." Guard double-apply (refuse if
already body-sized < 3 m). Always report the resulting size.

## Clean
- **Center**: origin to geometry/bounds, move to world origin.
- **Auto-Remesh**: voxel REMESH for even topology; expose voxel size (detail) — smaller =
  more triangles. Apply, then smooth lightly. Keep a pre-remesh history version.
- **Holes/islands**: `select_linked` to find islands; delete stray ones; `fill_holes`
  for gaps. Verify before closing (highlight suspect geometry).
- **Select-to-keep**: paint accumulates (LM-0002) — only wipe when whole mesh selected;
  circle-select must be ADD mode so strokes add, not replace.

## Shape (region edits)
- Push/pull a painted region along normals by mm, then **grow the region and smooth** for
  a feathered boundary (uFit technique). Circular variant: proportional edit from the
  region center, NORMAL orient, `proportional_size = radius` → smooth dome.
- Simple Deform: **BEND axis Y** (coronal; Z destroys it — LM-0003), TWIST axis Z,
  STRETCH axis Z + `lock_x/lock_y` (else it tapers girth — LM-0004).
- Deform range via draggable plane discs driving modifier `limits` through drivers
  (LM-0005); freeze driven values before `modifier_apply` to avoid "Invalid driver".

## Pads / outline displacement
- Read the **evaluated** curve for AUTO handle positions (raw handles are (0,0,0) until
  depsgraph eval — LM-0006). Bound drape raycasts (silhouette grazing) + closest-point
  fallback.
- Inside-test (even-odd) on the best-fit plane; KDTree distance-to-boundary → smoothstep
  feather; reject the opposite hollow-shell wall via `vertex_normal · plane_normal > 0`.

## Trim
- Editable Bezier outline → variable-height cut; or boolean with a crop box.
- **One-button smoothing**: CorrectiveSmooth on a "Smooth" vertex group (WASP pattern).
- Flare the cut edge (offset rim) for comfort.

## Shell
- Liner gap: DISPLACE (NORMAL) outward. Wall: SOLIDIFY (offset 1.0). Variable thickness:
  SOLIDIFY `thickness_vertex_group` = min/max ratio + MASK (WASP). Reinforce by extra
  thickness over a region.
- Ventilation: parametric hole grid → BOOLEAN difference cutters over a region.

## Apply / bake
Force OBJECT mode before modifier_apply / boolean / mode-sensitive ops (a user may sit in
Edit/Sculpt). Refuse pad-apply if the scan still has un-applied deform modifiers
(evaluated vs base mismatch). Snapshot a history version at each major stage.

## Export QA
Manifold + watertight check, min wall thickness, no sharp/degenerate edges, correct mm
units + orientation, deviation-vs-scan within intended correction. See qa_test_protocol.md.
