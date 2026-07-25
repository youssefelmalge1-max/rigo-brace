# Manufacturing Constraints (3D-printed spinal brace)

Targets that bound the design. **Verify against the actual printer/material/clinical
spec** — these are sensible defaults, not fixed rules.

## Wall thickness
- Default shell: ~4 mm (range 3–5 mm typical for printed TLSO depending on material).
- Reinforced zones (pelvic anchor, major thoracic pressure): thicker (e.g. 5–6 mm).
- Expansion/relief and ventilated zones: thinner allowed (e.g. 3 mm) but never below the
  printer's reliable minimum.
- Absolute minimum: set per material; flag anything below it in QA.

## Edges & trimlines
- All trim edges flared/rounded (no knife edges against skin).
- Flare the cut by a small % of local radius for comfort + edge strength.

## Ventilation
- Parametric hole grid: hole Ø + spacing in mm; keep **minimum bridge width** between
  holes (≥ wall thickness, ~2–4 mm) so the shell stays strong and printable.
- Avoid placing ventilation in high-stress zones (pelvic anchor, primary pressure pads).

## Mesh for print
- Manifold, watertight, consistent outward normals.
- No self-intersections after deform/boolean.
- Reasonable triangle density (post-remesh); decimate if oversized, but preserve form.
- Units mm; export STL or 3MF; correct scale (1 BU = 1 m internally → export in mm).

## Boolean robustness
Slots, ventilation and emboss use BOOLEAN — apply in OBJECT mode, check manifold after,
prefer clean cutters (closed, non-coplanar with the wall). Re-run QA after each boolean.

## Connectors / components (future)
Strap/buckle/ring/closure mounts must be solidly fused to the shell (no floating/0-volume
joins) and oriented to the surface normal.
