# Reusable Pressure/Expansion correction — geometry acceptance contract (#48)

Written BEFORE the fix from measured controls (2026-07-29, `tools/regionqualdbg.py`);
reconciled 2026-08-14 after the expert-council review (hardening Wave 0 — see
`hardening_plan_48.md`). A committed correction (direct paint, direct circle, or imported
style) passes only if every gate below holds. Gates are evaluated on the raw mesh after
commit, scoped to the correction footprint (mask members + one ring) unless a gate says
whole-mesh.

## Machine-readable thresholds (single source of truth)

`tools/quality_contract.py` parses this block; `tools/regionqualtest.py` takes every
numeric gate value from it and nowhere else; `python tools/contractcheck.py` fails the
build when this block is missing, unparsable, or incomplete. Editing a threshold here IS
editing the test.

```json
{
  "validity": {
    "selfx": 0, "inverted": 0, "degenerate": 0, "holes": 0,
    "nonmanifold_delta": 0, "count_change": 0
  },
  "smooth": {"osc_floor_mm": 1.0, "osc_profile_coeff": 6.0, "osc_cap": "amount"},
  "amount": {"core_lo": 0.90, "core_hi": 1.10},
  "feather": {"outside_max_mm": 0.001, "rev_tol_mm": 0.2,
              "decile_rev_tol_mm": 0.2},
  "parity": {"osc_factor": 1.5, "osc_slack_mm": 0.3, "spike_slack": 2,
             "iou_min": 0.80, "rms_max_mm": 0.5,
             "core_maxdd_mm": 1.0, "rim_shift_edges": 1.5},
  "resolution": {"core_med_min_frac": 0.90},
  "perf": {"import_commit_max_s": 2.0},
  "wall": {"clearance_mm": 3.0, "cross_sheet_new": 0},
  "fold": {"dot": -0.95, "pre_dot": -0.5, "new_folds": 0,
           "oracle_post_deg": 160.0, "oracle_pre_deg": 120.0},
  "size": {"surface_tolerance_frac": 0.12}
}
```

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
   neighbours w>0.5) = 0; vertex AND face counts unchanged by displacement.
   **Whole-body validity (Wave 1, P0):**
   - *Opposite-wall clearance* — before mutating anything, the commit casts rays from
     every core (w>0.5) vertex along its displacement direction against the body's
     static (non-footprint) faces; any hit within `displacement + clearance_mm`
     REFUSES untouched. `clearance_mm` is a geometric collision floor (never press
     through or within 3 mm of another sheet), NOT a clinical thickness rule; a
     clinical minimum may later raise it, never lower it.
   - *Cross-sheet net* — after commit+repair, new footprint-vs-static face
     intersections (shared-vertex pairs excluded, pre-existing contacts baselined)
     must equal cross_sheet_new, else refuse-and-restore.
   - *Fold collapse* — adjacent footprint faces whose shared edge folds closed
     (normal dot < fold.dot) without being pre-creased (pre dot > fold.pre_dot) are
     defects the repair must clear, else refuse-and-restore. This closes the flip
     test's <90°-rotation blind window on creased scans.
   The TEST oracle for these is independent of the production predicates: footprint
   faces vs a whole-mesh BVH (different pairing/bookkeeping), and a dihedral-degree
   measurement (`> oracle_post_deg` new, was `< oracle_pre_deg`) instead of a
   normal-dot; a unit fixture cross-checks predicate against oracle; the
   `contract_constants` gate pins the production constants to this block.
2. **Smoothness** — one-ring displacement oscillation bounded by twice the analytic
   smoothstep curvature of the requested profile, clamped so it can never go vacuous:
   `osc_max ≤ max(osc_floor_mm, min(2 × amount_mm × 6/feather_mm² × h², amount_mm))`
   where `h` = mean footprint edge (mm) and feather = the effective falloff width
   (circle: its radius). The unclamped bound reached 40.5 mm at feather 10 — steeper
   walls are legitimate, but oscillation beyond the amount itself never is.
   **Import parity**: importing a style must not be rougher than applying it directly —
   `osc_max(import) ≤ osc_factor × osc_max(direct) + osc_slack_mm` and new dihedral >60°
   edges `import ≤ direct + spike_slack` on the same fixture/parameters.
3. **Amount fidelity** — median |displacement| over the w>0.9 core within
   **[core_lo, core_hi]** of the requested amount. The saved style's stored amount and
   the region's `magnitude_mm` are one value; the panel's global "Amount (mm)" only
   seeds NEW regions and is never multiplied in.
4. **Feather fidelity** — |displacement| outside the mask ≤ outside_max_mm; zero
   weight-vs-|d| monotonicity reversals (> rev_tol_mm) across edges; the weight-decile
   profile of mean |d| is monotone non-decreasing with weight within decile_rev_tol_mm
   (shape-agnostic replacement for the old radial-bin wording — radial bins are
   undefined for painted, non-convex footprints).
5. **Library fidelity** — importing a saved style at its authoring location on the
   authoring mesh vs the direct region: footprint IoU (w>0.05) ≥ iou_min; |d| field
   RMS diff ≤ rms_max_mm; **two-part max deviation** replacing the old single 2.5 mm
   number (which was authored without derivation and measured violated at 2.70 mm while
   the shipped test allowed 3.75 mm — see decision DEC-0042):
   - core (both weights > 0.9, the controlled plateau — same zone as gate 3):
     max |d| diff ≤ core_maxdd_mm;
   - rim (everything else): max |d| diff ≤ rim_shift_edges × h × slope_max where
     slope_max = 1.5 × amount/feather (the analytic peak slope of the smoothstep
     profile). Derivation: resampling a continuous field onto a different triangulation
     can shift the transition rim laterally by ~1.5 edges; on a slope s that reads as a
     depth difference of shift × s without any real shape change. Patient 15/30 mm,
     h≈3.15: bound 3.54 mm (measured 2.70); scan 15/30, h≈3.85: bound 4.33 (measured
     1.25). The global maxdd is still RECORDED in every run as a diagnostic.
6. **Resolution robustness** — the same style on 2 mm / 3 mm / 6 mm flat fixtures and
   on decimate-0.65/0.30 scan targets passes gates 1–4 and keeps
   `core_med ≥ core_med_min_frac`.
7. **Evaluated-surface correctness** — the import frame and the vertex field must be
   computed from the SAME geometry state (the evaluated surface the user sees). If the
   modifier stack changes the vertex count, the import must refuse with an actionable
   error and mutate NOTHING (no region, no vertex group, no vertex moved) — gated by a
   live-subdivision fixture.
8. **Determinism / state safety** — same inputs ⇒ same weights (bit-equal); a refused
   commit restores positions bit-exactly and keeps the live preview; a failed import
   mutates nothing; `regiontest.py` + `regionstyletest.py` preview/idempotence gates
   keep passing. *Pending evidence (hardening Wave 5): scripted undo/redo and .blend
   save/reopen round-trip are REQUIRED for release but not yet covered by a gate; do
   not cite them as verified until those tests exist.*
9. **Performance** — import + commit operators ≤ import_commit_max_s on the patient
   scan.
10. **Size semantics (Wave 2 decision)** — a style's authoritative size is measured
   ALONG THE SURFACE (geodesic mm) over its effective footprint (w > 0.05); the
   tangent chart's chord extent is diagnostic only and never defines the size. Amount
   stays normal-displacement mm; Feather stays surface mm. The import trim limit is
   the stored intrinsic size × 1.15 (legacy chord fallback for old entries), so
   distant lobes of non-convex pads survive. On a curved target the realized surface
   size must stay within surface_tolerance_frac of the authored size, else the import
   WARNS (never silently resizes). Measured chord-vs-geodesic divergence for a
   ~52 mm effective footprint: +3.5 % on an R=60 mm cylinder, +2 % on R=95 mm; the
   council's ±8–11 % figure applies to footprints approaching the chart's ~90°-of-arc
   envelope, where the fold guard (Wave 4) refuses before the divergence can lie.
11. **Non-convex fidelity (Wave 2)** — the snapshot anchor is snapped ONTO the pad
   (strong-member vertex nearest the weighted centroid; a horseshoe's raw centroid
   sits in its gap and shifted the imported pattern 40 mm / IoU 0.123 before this),
   and save→import of a C-shaped pad at its anchor keeps footprint IoU ≥ the parity
   iou_min.
12. **Pairing & mirror provenance (Wave 2 decisions 1–2)** — a style stores ONE
   region plus never-silently-discarded clinical facts: anatomical label, paired
   flag, counterpart kind/label/landmark/amount, counterpart center offset (mm),
   mirror provenance (`mirrored_from`), and whether a sided landmark was auto-mapped
   (only unambiguous L↔R pairs are mapped; midline labels never change). The UI must
   say when a selected style belonged to a pair. Mirror derives the opposite region
   from the UNdisplaced snapshot through the importer's continuous-field path — never
   from displaced geometry, never by nearest-vertex weight collapse.

Every result file opens with a provenance stamp (git commit, date, Blender version).

Verified by `tools/regionqualtest.py` (gated PASS/FAIL) and `tools/regionqualdbg.py`
(diagnostic numbers, no gates); `tools/contractcheck.py` guards doc/test consistency;
adversarial reproductions live in `tools/hardendbg.py`.
