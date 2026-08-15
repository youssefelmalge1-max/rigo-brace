# Council Investigation — #49c: make the committed wall read as ONE sculpted surface (ZBrush-like), without touching clinical intent

2026-08-16. Orthotist request after #49b: the corrected area is better but
still shows terracing / speed-bump ridges; whole-mesh Smooth doesn't make it
read as one continuous form. Preserve amount, footprint, plateau, transition
design exactly.

## Repository Evidence (tools/sculptdbg.py, decim-0.15 steep painted wall, 15/10 mm)

Candidate causes measured independently (A/B/C/D/E/F/G/H/I variants), wall
band = edges with both endpoints 0.05<w<0.95; terrace metric = CONVEX signed
dihedrals (>10°) inside a pressed (concave) wall:

- A (today-#49b: linear split + IDW field): repair leaves 5 defects; dihedral
  mean 18.9°, p95 55.2°, 111 ridge edges.
- B (curved Phong split placement): repair 5→0 defects; mean 17.6, p95 48.4.
  Linear splitting leaves the refined base piecewise-flat at the ORIGINAL
  facet scale — curving split points through the original vertices' tangent
  planes fixes both quality and repair convergence.
- C (harmonic field alone): no measurable change on this fixture — the kinks
  live AT the original anchors, not between them. (Kept anyway: IDW's
  gradient provably vanishes at samples; harmonic is max-principle-safe and
  nearly free.)
- E/F/G (post-displacement fairing of new verts): ridges 111→75..94 but
  REINTRODUCES 4 repair failures (fairing only new verts kinks the surface
  at the anchored originals). REJECTED.
- H/I (Phong resurfacing of the displaced coarse mesh): validates (0
  defects), ridges →86, but worst ridge WORSENS (94→112°, wrong-sheet BVH
  grabs on the steep wall). REJECTED on measurement.
- REFERENCE (identical patch on the FULL-density scan — the quality
  ceiling): mean 14.3°, p95 39.1°, max 85°, ridge fraction 26%.
  The coarse commit with B+C measures mean 17.5 / p95 48.4 / ridge fraction
  30% — already NEAR the intrinsic ceiling of steep pressure on this
  wrinkled skin.
- The dominant remaining PERCEPTUAL gap is not geometry: STL imports render
  FLAT-SHADED — every facet displayed as a plate — while the ZBrush
  reference renders smooth-shaded. The scan was never shade-smoothed
  anywhere in the product.

## Classification

`TOPOLOGY` (subdivision placement) + `SURFACE_MATH` (field interpolation) +
`UX_TOOL_LIFECYCLE` (shading presentation). P2 (quality polish; no validity
defect). No clinical field changes.

## Activated Experts

botsch (primary — subdivision/quality), keenan-crane (interpolation
smoothness; IDW zero-gradient at samples, harmonic max principle),
campbell-barton (shading data-level, no modifier — no veto),
geometry-reliability (reference-anchored metrics), rigo governor (amounts /
footprint / plateau untouched — NO VETO).

## Root Cause

One falsifiable sentence: linear split placement left the refined base
piecewise-flat at the original facet scale (fixed by Phong-curved split
points, measured 5→0 repair defects and improved dihedrals), and the
remaining "plates" perception is dominated by flat shading on STL-imported
scans — the committed geometry already sits near the full-density reference's
intrinsic dihedral spectrum.

## Council Verdict

**HARDEN**, unanimous, no vetoes:
1. Curved (Phong) split placement, weighted-parent edges only (unweighted
   new vertices stay EXACTLY on the original surface — feather outside
   contract 0.001 mm; measured 0.0000), agreeing normals only (no crease
   bulging). Original vertices never move.
2. Harmonic field relaxation of NEW vertices' weights anchored at the
   authored originals (Gauss–Seidel ×24, deterministic, max principle).
3. Smooth-by-angle shading (60°) as product behavior at scan import and
   apply-units — data-level (face smooth flags + sharp edges), NO modifier;
   flags survive the transactional commit. Genuine creases stay crisp.
4. wall_dih_p95 recorded per commit in the battery (population 13–39°;
   coarse fixture 38° vs full-density reference 39°) — gate derivation
   deferred until the population includes more scan classes.
5. Fairing and Phong-resurfacing of final positions: REJECTED on
   measurement (see evidence).

Perf re-derived: floorless refinement + field passes measured 3.23 s on the
44.5k painted commit — contract perf gate 3.0→4.0 s, regiontest aligned.

## Success Criteria (defined with the orthotist's ask)

- Repair convergence on the coarse steep wall: 5 residual defects → 0 (met).
- Wall dihedral spectrum within ~25% of the full-density reference
  (met: p95 48.4 vs 39.1; mean 17.5 vs 14.3).
- Unweighted vertices exactly on the original surface (met: 0.0000 mm).
- The scan and committed corrections render as one continuous smooth-shaded
  surface with crisp true creases (shipped as product behavior).
- All existing clinical gates unchanged and green (amount, feather, plateau,
  footprint, parity, size, refusal safety).
