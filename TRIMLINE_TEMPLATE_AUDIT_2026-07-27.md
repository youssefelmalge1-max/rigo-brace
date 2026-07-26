# Template Trimline Generator & Editor — Audit and Decision Report

_Date: 2026-07-27. Scope: upstream trimline quality (generator + editor). The rim,
projection de-burring, QA guard and shell pipeline (8668f95, 1c6f36e, 76db5ce,
3066bc6, 185263e) were not touched and are not proposed for change._

Evidence: `tools/trimgenaudit.py` → `trimgenaudit_result.txt` (new, this audit) and
`tools/rimwavedbg.py` → `rimwavedbg_result.txt` (re-run at shipped settings).
Fixture: A-type scan + Rigo-Chéneau Reference template, 4 mm wall, 3 mm offset —
the brace in the user's screenshots. All numbers below are measured, not assumed.

---

## 1. Actual trimline object lifecycle

| Object | Type | Created by | Removed/replaced by | Visible when |
|---|---|---|---|---|
| `Rigo Trim Perimeter` | Bézier curve, 42 controls, cyclic, bevel tube r=1.2 mm, Shrinkwrap→scan (NEAREST_SURFACEPOINT, offset 1.5 mm) | `rigo.auto_trimline` / `rigo.custom_trim_from_paint` (name-keyed delete-then-recreate) | itself on regenerate; `rigo.clear_trimlines`; new-patient import | TRIM view — **the editable clinical authority** |
| `Rigo Trim Top` / `Rigo Trim Bottom` | Bézier curves, 24 controls | `rigo.auto_trimline` | same | never (hidden immediately; legacy compatibility) |
| `Rigo Build Trim Perimeter` | copy of the perimeter, bevel tube r=1.2 mm, Shrinkwrap→`Rigo Corset Base` (TARGET_PROJECT, offset 0.2 mm) | `curve_build_ops._preview_curve` on every Generate | replaced on next Generate (`_discard_after_commit`) | BRACE view, together with the shell |
| `Rigo Corset` / `Rigo Corset Base` | meshes | Generate (transactional candidates) | replaced atomically on next Generate | Corset in BRACE view; Base always hidden |

Regeneration is clean: `auto_trimline` twice and Generate twice produced identical
name sets, zero `.001`/Candidate/Backup leftovers, and `curvestagedbg` had already
proven bit-identical rebuild determinism.

## 2. Why the paths look doubled

**Measured root cause: the BRACE-view preview tube is fully embedded in the shell.**
`_set_design_view("BRACE")` deliberately shows the shell **plus**
`Rigo Build Trim Perimeter`. That curve renders as a 1.2 mm-radius tube whose
centerline sits 0.015–0.41 mm (p50 0.20 mm) from the shell surface — **1008 of
1008 sampled points are closer than the tube radius**, so the entire tube pierces
the shell and its emerging half reads as a second dark line/ridge running parallel
to the rim, with intermittent marks where it dips in and out. This is the doubled
path and the "burnt specks" along the edges in the screenshots.

Classification against the brief's list: (5) an offset preview/editing guide,
amplified by (6) bevel thickness. It is **not** stale geometry, not a duplicate,
and not two authorities — regeneration replaces everything correctly.

Secondary display finding: the orange TRIM-view line is the **evaluated
(shrink-wrapped) curve**, but Generate samples the **raw Bézier** and projects it
onto the offset mold. Displayed-vs-built gap: p50 0.48 mm, p95 2.39 mm,
**max 11.77 mm** (where the raw curve bridges a concavity and the display wraps
onto the body). The orthotist is editing a line that is not, at the worst spot,
the line that gets cut.

## 3. Stage that introduces each observed artifact

| Symptom | Stage | Measurement |
|---|---|---|
| Doubled/overlapping paths | display (BRACE preview tube) | 100 % tube-radius penetration |
| Repeated small waviness in smooth regions | Stage-2 projection onto the faceted mold (known: LM-0035) | clinical curve turn p95 2.32° → 3.90° after projection+de-burr; all later stages track ≤0.02 mm p95 |
| Waviness of the *displayed* line | display Shrinkwrap (per-sample nearest-point, **no de-burring on the display path**) | same facet-stamping mechanism the build path already corrects |
| Kinks at section transitions | generator handle model (G1-only, curvature jumps at controls) | junction Δκ p95 54.5 /m vs within-segment baseline p95 5.62 /m — **~10×**; worst at the opening corners and top-front transition (θ ±9°, ±29°, 70°) |
| "Connected segments" feel | generator handle reach + control spacing | reach 0.25–0.75 of the Catmull-Rom third-of-chord (p50 0.75); control spacing 24.5–132.3 mm (**5.4× spread**) |
| Abrupt/unpredictable manual edits | editor | drag tent is ±2 *controls* (not mm): an 8 mm drag moved geometry 2.0 mm at >150 mm arc distance; "Add Curve Detail" (refine) moved the curve p95 3.75 mm / **max 14.8 mm**; any point drag wipes user-rotated handles everywhere (20.0° user rotation → 0.0° after an unrelated drag) |

What the clinical Bézier is **not**: wavy. Against its own 3 mm-smoothed self the
raw curve deviates max 0.29 mm with 1.5 % sign flips; it contains zero >10° dense
turns; per-view turn p95 is 1.8–2.6°. The generated curve is fair — the damage is
at the junctions, in the display, and in the editor.

## 4. Draft or manufacturing-ready?

Confirmed split verdict:
- **Downstream (projection → cut → resample → rim): manufacturing-grade.** Trimline
  fidelity on the shell p95 0.029 mm / max 2.57 mm (hairpin), deterministic,
  0 intersections, QA green.
- **Upstream (curve + editor + display): anatomical draft guide.** Fair in itself,
  but G2-discontinuous at landmark stations, displayed ≠ built (max 11.8 mm),
  editing non-local and destructive of handle intent.

## 5. Current spline/interpolation architecture

One closed cyclic Bézier spline (42 controls template / ≤84 painted / ≤168
refined). Landmarks are **not** connected by independent segments: landmarks give
anchors (bottom/waist/top z, pelvis axis, ASIS front), the template's 72-bin
angular profile is sampled at 18 stations per edge + 3 per opening side, each
station radially ray-draped onto the scan +1.5 mm. Handles: explicit FREE pairs,
direction = neighbour chord (central difference), reach = 0.25 × min(adjacent
chords) both sides (`_set_clamped_tangent_handles`).

## 6. Continuity at landmark junctions

- **C0**: exact (single spline).
- **G1**: exact by construction (collinear handle pairs). The measured "tangent
  break" (p95 3.8°) is finite-difference bias proportional to local curvature ×
  sample step, not a real break.
- **C1**: no — derivative magnitude jumps where adjacent chords differ (up to 5.4×).
- **G2/C2**: no — curvature jumps at controls are ~10× the within-segment
  variation, concentrated exactly at the opening corners and the axillary/top
  transition. This is the measured "kinks where sections transition" mechanism.

## 7. Manual-editing failure mechanism

The user edits **Bézier control points and handles** of the perimeter (never
evaluated points or mesh vertices — good). Three defects:

1. **Topological, not metric, falloff**: `_move_dragged_point` weights
   (1.0/0.50/0.18 at 0/±1/±2 controls) span up to ±260 mm of arc where controls
   are 132 mm apart. Locality is unpredictable because spacing varies 5.4×.
2. **Handle-intent destruction**: every point drag re-derives *all* handles
   (`_set_clamped_tangent_handles(spline)`), resetting any user-rotated
   (LINKED_TANGENTS) handle anywhere on the curve. Measured: full 20° wipe at
   a quarter-perimeter distance.
3. **Refine jump**: "Add Curve Detail" subdivides exactly (shape-preserving) but
   then radially re-fits **every** control onto the body, snapping the raw curve
   toward the displayed one in one uncontrolled step (p95 3.7 mm, max 14.8 mm).

Positive findings: Fit-to-body on an untouched curve is a no-op (max 0.1 µm);
drags do **not** create kinks (turn p95 1.50→1.55° in the window — handle
re-derivation keeps the response smooth); Esc/Ctrl+Z snapshots restore exactly;
the smooth brush already implements mm-radius falloff, visibility filtering and
*local* handle refresh — the correct pattern already exists in the codebase.

## 8. Smallest safe architecture change

**No representation change.** Keep the cyclic Bézier: the measured defects are
tangent magnitudes, station spacing, display truthfulness and editor falloff —
none require B-spline/NURBS/Hermite, all of which would rebuild the editor UX for
no measured gain. Catmull-Rom-style tangents *derived onto* the existing Bézier
give the fairness benefit while remaining Blender-native and editable.

Four independent, individually revertible fixes, all inside `trimline_ops.py` +
one display constant, none touching `curve_build_ops`/rim/QA:

- **P1 Display truth (doubled line)**: BRACE preview tube — reduce bevel to
  ~0.3 mm and raise its shrinkwrap offset above the tube radius (or draw as a
  wire/in-front thin curve). Acceptance: zero centerline samples closer to the
  shell than the tube radius. TRIM tube likewise thinned to clear its 1.5 mm
  offset.
- **P2 Generator stations + tangents**: cap arc-station spacing (~≤40 mm, insert
  stations on long arcs) and replace the reach formula with per-side
  centripetal-weighted third-of-chord (asymmetric reach, collinear directions —
  stays G1, approaches C2). Acceptance: junction Δκ p95 ≤ 3× within-segment
  baseline (now 9.7×); displayed-vs-raw gap p95 ≤ 1 mm (now 2.39, max 11.77);
  spacing spread ≤ 2.5× (now 5.4×).
- **P3 Editor falloff + handle preservation**: drag falloff by arc-length mm
  (reuse the smooth brush's distance/falloff machinery) and re-derive handles
  only inside the affected arc (`_refresh_brush_handles` pattern). Acceptance:
  8 mm drag moves nothing beyond 60 mm arc by >0.5 mm; far user-rotated handle
  changes <0.5°.
- **P4 Refine locality**: fit only the newly inserted midpoints (nearest-surface,
  not radial), leave existing controls untouched. Acceptance: refine deviation
  max ≤1 mm (now 14.8).

Explicitly **not** proposed: mold smoothing, changes to Stage-2 σ, rim changes,
downstream compensation of any kind. Feature protection (opening corners) already
exists via `trim_brush_lock_opening` + corner anchors downstream; P2 must keep
the opening-corner stations pinned.

## 9. Files and functions expected to change

- `rigo_brace/operators/trimline_ops.py` — `_make_trim_curve` (bevel),
  `_set_linked_tangent_handle`/`_set_clamped_tangent_handles` (P2 tangents),
  `RIGO_OT_auto_trimline.execute` (station densification, P2),
  `RIGO_OT_slide_trimline_on_surface._move_dragged_point` (P3),
  `_fit_refined_controls` / `RIGO_OT_refine_trimline` (P4).
- `rigo_brace/operators/curve_build_ops.py` — `_preview_curve` only (bevel/offset
  constants, P1). No logic change.
- `tools/trimgentest.py` (new) — numeric gates listed above + lifecycle
  duplicate check; `tools/trimgenaudit.py` retained as the diagnostic.

## 10. Tests that must be added / stay green

New: `trimgentest.py` (gates in §8). Regression battery unchanged and must stay
green: `rimresampletest`, `curvebuildtest` (4/4 determinism), `customtrimseamtest`,
`curvefinishtest`, `trimqualitytest`, `referencetrimtest`, `thicknesstest`,
`qatest`, `slotbracetest`, `importtest`, `selftest`. Prototype fixtures: A
reference (this audit), hostile hairpin (existing), B scan, painted custom trim,
repeated regenerate + edit-then-regenerate (already covered by determinism +
this audit's lifecycle phase).

## 11. Rollback strategy

Each of P1–P4 is a self-contained hunk in one function group; revert
individually. P1 is display-only (zero geometry risk). P2 changes generated
curves — the stored `rigo_trim_handle_model` stamp distinguishes old/new curves,
and the previous reach formula is one line to restore. No stored file format
changes. The downstream pipeline consumes dense samples and is representation-
agnostic, so a rollback cannot strand a generated shell.

## 12. Recommendation

**Limited prototype (P1–P4), in that order, one patch each with its gate.**
Not full implementation (the fixes are small enough that a big-bang change would
only blur attribution), and not deferral (every defect is measured, localized,
and has an existing in-codebase pattern to reuse). P1 alone resolves the most
visible complaint (doubled line) with zero geometry risk and should go first.

Residual known limits, out of scope here (unchanged from LM-0030/0031/0035):
the offset-mold self-intersection that caps painted-trim control density at 84,
the spacing-limited delivered fillet radius (~0.35 mm), and the Stage-2 facet
floor (3.90° vs 2.32°) which only mold fairness could further improve.

_Adversarial cross-review (per project habit) is pending: the codex CLI quota
returns 2026-08-01._
