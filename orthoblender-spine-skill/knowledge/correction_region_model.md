# CorrectionRegion — the measurable pressure/expansion data model (Patch 4 backbone)

Principle (DEC-0014, user's standing rule): a correction is **measurable data**, never
"some vertices I happened to move." Every push/pull becomes an editable, undoable,
orthotist-reviewable, QA-checkable object. This makes Patch 4's Guided sculpt reproducible
and lets the same data drive the QA gate and (later) clinical templates.

Separated by concern (per skill discipline):

## Clinical concept
A **pressure zone** pushes the shell inward against the body at a curve apex (corrective
force); an **expansion / relief zone** lifts the shell outward to give room (breathing,
bony prominence, opposite side of a curve). They come in **coupled pairs** — push here,
relieve on the opposing side — which is the Rigo 3-point / 4-point principle. Magnitude and
extent are clinical values the orthotist sets in **mm**, and every zone `requires_
orthotist_review`. The software guides; it never decides the magnitude.

## Data model (Blender implementation)
A `RigoCorrectionRegion` PropertyGroup in a `CollectionProperty` on the brace object
(travels with the mesh, saved in the .blend, visible/editable in the panel):

| field | type | meaning |
|---|---|---|
| `name` | str | user label |
| `anatomical_label` | Enum | from LANDMARKS (thoracic apex, lumbar, pelvic, waist, axilla…) |
| `kind` | Enum | PRESSURE (inward) / EXPANSION (outward) |
| `center` | FloatVector (m) | region centroid, captured from the paint selection |
| `direction` | Enum + FloatVector | NORMAL (mean surface normal) or explicit axis |
| `magnitude_mm` | Float | signed push/pull depth in mm (UI mm → `*0.001`) |
| `radius_mm` | Float | influence radius for falloff |
| `falloff_type` | Enum | SMOOTH / SPHERE / LINEAR / SHARP (matches proportional-edit) |
| `surface_mask` | str | name of the vertex group storing the painted region (weights = falloff) |
| `opposing_region` | int | index of the coupled expansion region (−1 = none) |
| `enabled` | bool | toggle without deleting |
| `requires_review` | bool (True) | clinical-safety flag, always set |

Why a vertex group as the mask: it is deterministic, survives edits, re-applies exactly,
and the weights ARE the falloff — so Apply and Undo reproduce the same geometry.

## Operators (`operators/region_ops.py`, new — reuses existing code)
- `rigo.region_add` — from the current paint selection (reuse `select_ops` region): compute
  centroid + mean normal, bake a falloff vertex group (grow-then-smooth feather, reuse the
  `pad_ops` feather logic), create the data entry. Deterministic.
- `rigo.region_apply` — displace masked verts along `direction` by `magnitude_mm × weight`.
  Signed by `kind`. `{"REGISTER","UNDO"}`. Idempotent from stored data (re-apply from
  zero-state = same result).
- `rigo.region_mirror` — create/refresh the opposing expansion region across the sagittal
  plane.
- `rigo.region_toggle` / `rigo.region_remove`.
- (Free mode stays separate: enter Blender 5 Sculpt Mode with a curated brush set — for
  freehand only; freehand is NOT a CorrectionRegion and is flagged as un-measured.)

Reuse map: paint selection = `select_ops`; feather = `pad_ops`; normal-direction displace
= new but small; history snapshot on apply = `history_ops`. No duplicate operators.

## Panel (Shape stage)
Guided box: a UIList of regions (kind icon · label · magnitude_mm · enabled) + Add-from-
selection · mm/radius/falloff fields · Apply · Mirror · Remove. Free box: Enter/Exit
Sculpt + brush picker. Live circumference readout after Apply (Measure stage, later).

## Quantitative acceptance gates (regiontest.py — DEC-0014)
Apply a known region and assert **numbers**, not appearance:
- Displacement at the center vertex = `magnitude_mm` (±0.05 mm).
- Falloff monotonic: verts at `radius_mm` move ≈0; beyond radius move exactly 0
  (untouched region proven).
- Vertex COUNT unchanged (displace, not add/remove); no new non-manifold edges.
- Undo restores the pre-apply vertex positions **exactly** (max delta < 1e-6 m).
- Re-apply from the stored data reproduces the same positions (deterministic).
- Op completes < 2 s on the sample scan.
- Original imported scan object left unchanged (we edit the working brace copy).

## Open design choices to confirm before coding
1. Store regions on the **object** (travels with mesh, per-brace) vs the **scene** →
   recommend **object**.
2. `direction`: default **mean surface normal** of the selection (most clinical) with an
   optional explicit-axis override → recommend normal-default.
3. Auto-create the opposing expansion region on add, or only via `region_mirror` →
   recommend **manual mirror** (orthotist decides the couple).
