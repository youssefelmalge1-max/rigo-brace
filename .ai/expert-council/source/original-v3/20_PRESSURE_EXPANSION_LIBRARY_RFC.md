# RFC — Portable Pressure & Expansion Correction Library

status: proposed
scope: Blender orthotic / scoliosis-brace add-on
goal: reusable, movable, patient-specific pressure and expansion regions inspired by professional O&P CAD workflows without copying proprietary implementation details.

## 1. Product goal

The orthotist chooses a correction type from a library, places it on a patient model, sees an immediate preview, and can move/rotate/scale/change magnitude while the region remains attached coherently to the surface.

The same template can be instantiated on different patients without assuming identical topology.

This is conceptually consistent with public O&P CAD workflows that provide libraries, rectification tools, reusable protocols and the ability to move/merge anatomical areas. It does **not** assume knowledge of Rodin4D's proprietary internals.

## 2. Non-goals

Version 1 should not:
- automatically choose a Rigo classification
- predict Cobb correction
- claim real pressure in kPa
- infer tissue mechanics
- auto-place all pads from scan alone
- copy proprietary Rodin4D assets/algorithms
- require identical vertex topology between patients

## 3. Domain model

### CorrectionTemplate

```yaml
id: uuid
name: string
semantic_type: pressure|expansion|relief|transition
device_concept: generic|rigo_cheneau|other
clinical_tags: []
shape:
  family: ellipse|freeform|library_patch|procedural
  aspect_ratio: float
influence:
  model: geodesic_radial|local_uv|harmonic|biharmonic|custom
  falloff_curve: smoothstep
direction:
  policy: surface_normal|transported_tangent_plus_normal|clinical_vector
constraints:
  max_default_depth_mm: null
schema_version: 1
```

### CorrectionInstance

```yaml
id: uuid
template_id: uuid
target_model_id: uuid
attachment:
  anchor:
    triangle_id: transient
    barycentric: [u,v,w]
    world_fallback: [x,y,z]
  local_frame:
    normal: [...]
    tangent_u: [...]
    tangent_v: [...]
  landmark_frame_id: optional
boundary:
  representation: local_2d_curve
  control_points: [...]
transform:
  translate_uv: [...]
  rotation_deg: 0
  scale_uv: [1,1]
magnitude:
  depth_mm: 8
  profile: smooth
stack:
  enabled: true
  order: 20
version:
  attachment: 1
  evaluator: 1
```

## 4. Why raw vertex groups are insufficient

Vertex groups are useful as derived masks but fragile as canonical correction objects:
- topology changes invalidate indices
- remesh changes density and influence
- moving a region requires repainting/recomputation
- transferring to another patient is impossible directly
- clinical semantics are not encoded

Use vertex groups/attributes as **cache/output**, not source of truth.

## 5. Surface-local coordinate system

For each region:
1. choose anchor surface point,
2. derive surface normal,
3. derive tangent basis,
4. orient basis using user direction, landmark direction, principal curvature, or transported reference,
5. store region boundary/control points in local coordinates.

When moved, rebuild frame at the new anchor and reproject/evaluate.

### Orientation options

**Simple**
Project a user-selected anatomical direction into tangent plane.

**Advanced**
Parallel-transport orientation along surface as the region moves.

**Clinical**
Use landmark-based anatomical axes, then refine locally.

## 6. Influence field

The evaluator converts template + instance into a scalar influence `w(x)`.

### Candidate A — geodesic radial
Fast conceptual model:
- geodesic distance from anchor
- anisotropic scaling in tangent directions
- falloff curve

Pros: surface-aware.  
Cons: one-center model may not fit complex boundaries.

### Candidate B — local parameter-domain field
Define arbitrary 2D region boundary and map to nearby surface.

Pros: artist-friendly/freeform.  
Cons: distortion must be monitored.

### Candidate C — constrained harmonic/biharmonic field
Boundary/control constraints define a smooth field.

Pros: very smooth transitions.  
Cons: solver complexity/caching.

Recommended prototype: **local 2D boundary + geodesic/tangent-space influence**, then benchmark against constrained biharmonic deformation.

## 7. Deformation direction

Do not hard-code "pressure = inward normal, expansion = outward normal" as a clinical truth.

Support policies:
- normal displacement for simple geometric rectification
- blended normal + clinical vector
- user-defined vector projected/transported
- future biomechanical solver

Label UI parameters as **geometric depth/relief** unless real pressure is computed.

## 8. Move / rotate / scale UX

### Move
Raycast cursor to surface → new anchor → update local frame → reevaluate mask/deformation.

### Rotate
Rotate local template around surface normal.

### Scale
Change dimensions in local tangent coordinates.

### Magnitude
Change geometric depth without changing footprint unless explicitly linked.

### Boundary edit
Expose control handles in local surface coordinates.

### Accept/cancel
Use preview buffer. `Esc` restores exact prior state; confirm commits domain object + evaluated result.

## 9. Correction stack

Corrections should be ordered domain objects:
`C1 -> C2 -> C3 ...`

Each declares:
- topology_preserving: bool
- invalidates_attachments: bool
- locality bounding box
- cache key
- semantic dependencies

For pressure/expansion, strongly prefer topology-preserving deformation until a deliberate topology-changing stage.

## 10. Clinical coupling

For scoliosis templates, support relationships:
- paired/required expansion
- counterforce relationship
- classification applicability
- sagittal warnings
- left/right mirroring rules that can be overridden

A template may be geometrically reusable but clinically inapplicable to a given case. Software must not hide this distinction.

## 11. Library format

Store templates as JSON/YAML + optional preview thumbnail + optional neutral geometry resource.

Directory:

```text
correction_library/
  schema.json
  templates/
    thoracic_pressure_a.json
    thoracic_expansion_a.json
  previews/
  migrations/
```

Every file has:
- UUID
- schema version
- created_by
- reviewed_by
- evidence/source note
- checksum for external binary asset
- compatible evaluator versions

## 12. Versioning

Never reinterpret old patient corrections silently.

When evaluator changes:
- old instances keep `evaluator_version`
- migration may be offered
- before/after geometric deviation is measured
- user can preserve legacy result

## 13. Geometry metrics

On every preview/commit measure as appropriate:
- max displacement
- 95th percentile displacement
- triangle flips
- self intersections
- min edge length
- max aspect ratio
- normal inversion
- boundary drift
- protected landmark movement
- execution time

## 14. Performance architecture

Avoid:
- rebuilding entire mesh for every mouse pixel
- repeated `bpy.ops`
- rebuilding BVH/KDTree unnecessarily
- Python loops over all vertices for local edits

Prefer:
- cache spatial structures
- identify local affected region
- use vectorized/compiled/native operations where possible
- coarse preview while dragging, full solve on release
- dirty-region recomputation

## 15. Test suite

### Unit
- serialization roundtrip
- local frame construction
- boundary transform
- falloff evaluation
- evaluator deterministic under fixed inputs

### Geometry
- plane
- cylinder
- sphere
- saddle
- noisy torso patch
- nonuniform triangulation
- high curvature

### Interaction
- place
- move
- rotate
- scale
- cancel
- undo
- redo
- save/reopen
- duplicate patient model
- remesh invalidation warning

### Clinical semantic
- pressure template requiring paired expansion
- sagittal warning
- left/right mirror metadata
- unknown classification prevents auto-placement

## 16. Acceptance criteria for v1

- Place a template in ≤3 interactions.
- Move it without visible detachment.
- Cancel restores geometry exactly.
- Save/reopen preserves instance parameters.
- Works across two scans with different topology.
- No triangle flips in supported depth range on benchmark set.
- Preview latency is subjectively interactive on representative scan sizes.
- All severe geometry failures generate explicit errors, not silent commits.

## 17. Research/engineering routes

- Interactive geometry + representation: Ryan Schmidt
- Surface frame/geodesic: Keenan Crane
- Smooth deformation/robustness: Alec Jacobson
- Declarative correction stack: Jacques Lucke
- Blender lifecycle: Campbell Barton
- Clinical Rigo semantics: Manuel Rigo
- Mechanical/simulation semantics: Carl-Éric Aubin
- Future optimization: Mark Pauly

## Public product references

Rodin4D publicly describes:
- Neo as a CAD/CAM rectification core for orthoses/prostheses
- libraries of pre-rectified forms
- custom rectification protocols
- tool history
- 25+ rectification tools
- historical workflow examples for copying/moving anatomical areas, merging and smoothing

Sources:
- https://www.rodin4d.com/
- https://www.rodin4d.com/es/logiciel-cfao/
- https://www.rodin4d.com/newsletters/april-2013-en.html

Use these only as **product/workflow references**, not as claims about proprietary implementation.
