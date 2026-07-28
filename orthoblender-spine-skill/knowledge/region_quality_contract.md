# Reusable Pressure/Expansion correction — geometry acceptance contract (#48)

Written BEFORE the fix, from measured controls (2026-07-29, `tools/regionqualdbg.py`).
A committed correction (direct paint, direct circle, or imported style) passes only if
every gate below holds. Gates are evaluated on the raw mesh after commit, scoped to the
correction footprint (mask members + one ring).

## Measured clean controls (baseline)

Direct circle, 15 mm PRESSURE, 30 mm radius, patient scan (44.5k verts, 3.85 mm edges):
`osc_max=1.23 mm, osc_mean=0.32 mm, dihedral max=46.4°, edges>60°=0, inverted=0,
selfx=0, holes=0, core_med=14.43–14.55 mm (96–97 %), outside=0.0000 mm, monotone_rev=0`.

Broken pre-fix references: imported styles `osc_max` 1.9–4.0 mm, spikes>60° up to 111
(flat!), IoU vs direct 0.648, decim-0.30 `core_med=0.00`; repeat-import `osc_max=6.6`,
162 spikes, 40 inverted, 136 self-intersections; painted path 115 self-intersections.

## Gates

1. **Validity** — new self-intersections = 0; inverted faces = 0; degenerate faces = 0;
   non-manifold edge delta = 0; weight-field holes (w<0.1 vert with ≥3 one-ring
   neighbours w>0.5) = 0; vertex/face count unchanged by displacement.
2. **Smoothness** — one-ring displacement oscillation bounded by twice the analytic
   smoothstep curvature of the requested profile:
   `osc_max ≤ max(1.0, 2 × amount_mm × 6/feather_mm² × h²)` where `h` = mean edge (mm)
   and feather = the effective falloff width (circle: its radius). A steeper
   amount/feather combination legitimately produces steeper walls — steepness alone is
   not a defect, discontinuity is. **Import parity**: importing a style must not be
   rougher than applying it directly — `osc_max(import) ≤ 1.5 × osc_max(direct) + 0.3 mm`
   and new dihedral >60° edges `import ≤ direct + 2` on the same fixture/parameters.
3. **Amount fidelity** — median |displacement| over the w>0.9 core within
   **90–110 %** of the requested amount. The saved style's stored amount and the
   region's `magnitude_mm` are one value; the panel's global "Amount (mm)" only seeds
   NEW regions and is never multiplied in.
4. **Feather fidelity** — |displacement| outside the mask ≤ 0.001 mm; zero
   weight-vs-|d| monotonicity reversals (>0.2 mm) across edges; radial-bin profile
   monotone within one bin tolerance.
5. **Library fidelity** — importing a saved style at its authoring location on the
   authoring mesh vs the direct region: footprint IoU ≥ 0.80; |d| field RMS diff
   ≤ 0.5 mm; max diff ≤ 2.5 mm.
6. **Resolution robustness** — the same style on 2 mm / 3 mm / 6 mm flat fixtures and
   on decimate-0.65/0.30 scan targets passes gates 1–4 and keeps `core_med ≥ 90 %`.
7. **Evaluated-surface correctness** — the import frame and the vertex field must be
   computed from the SAME geometry state (the evaluated surface the user sees). If the
   modifier stack changes the vertex count, the import must refuse with an actionable
   error, never corrupt geometry.
8. **Determinism / state safety** — same inputs ⇒ same weights (bit-equal);
   `regiontest.py` + `regionstyletest.py` undo/preview/idempotence gates keep passing;
   a failed import mutates nothing.
9. **Performance** — import + commit ≤ 2 s on the patient scan.

Verified by `tools/regionqualtest.py` (gated PASS/FAIL) and `tools/regionqualdbg.py`
(diagnostic numbers, no gates).
