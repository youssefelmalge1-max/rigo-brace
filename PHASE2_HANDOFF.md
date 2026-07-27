# Phase-2 Handoff — B-type downstream non-manifold failure

_Written 2026-07-28 at the end of the #37 investigation. Read this before touching
anything in the trimline / brace-generation path._

---

## 1. Repository state

| item | value |
|---|---|
| HEAD when this was written | **`76a0dc9`** — "#37 Candidate A: triangle-quality baseline and fairing-order evidence" |
| diagnostics committed through | `76a0dc9` |
| production patches shipped, **unchanged** | `3f1c561` P1 · `2c3fe7d` P2 · `55dabb6` P3 · `fd1a95f` P4 · `50e88ae` display fix |
| production code committed for #37 | **none** — Candidate A is deliberately uncommitted |

Standing prohibition still in force (`issues.md` #42, DEC-0039): **do not remove
`SURFACE_OFFSET` as a standalone fix.**

---

## 2. Uncommitted prototype state

Two files are modified in the working tree and must NOT be committed as the production
fix until Phase 2 is understood.

| file | modification | purpose |
|---|---|---|
| `rigo_brace/operators/design_ops.py` | `+147` — adds `InnerSurfaceFoldError`, `_repair_faired_offset`, and a call to it at the end of `_prepare_candidate_base` | #37 Candidate A, Order B: detect residual folds on the **final faired** inner surface and repair locally |
| `rigo_brace/operators/curve_build_ops.py` | `+1` — adds `design_ops.InnerSurfaceFoldError` to the caught tuple in `_build` | routes an unrepairable fold through the existing transactional cancel/restore path |

**Patch artifact:** `PHASE2_CANDIDATE_A.patch` (committed alongside this file)

| property | value |
|---|---|
| sha256 | `a82010a94a093356d6ce51c665ee2f6477d15b8b4cc10bf5853293a2f4da8b8e` |
| bytes | 7487 |
| base commit | `76a0dc9efeba0c0c57b696aa9e19c8e1041925a5` |
| verification | `git apply --check --reverse` succeeds against the working tree, proving the patch is exactly the current diff from HEAD |

To reproduce the prototype from a clean checkout of `76a0dc9`:

```
git apply PHASE2_CANDIDATE_A.patch
./install.ps1          # tests exercise the INSTALLED copy, not the repo copy
```

### Two correctness properties that MUST survive any rework

1. **Write-back locality.** Only vertices whose offset *direction* genuinely changed are
   written. An earlier version reconstructed every vertex as `source + direction × length`,
   which sent untouched geometry through a float round-trip — measured as **737 of 44,859**
   vertices "moving" when **7** were repaired.
2. **The detector must evaluate the coordinates that will actually be stored.** The same
   earlier version tested a fully reconstructed array, so it validated geometry differing
   by epsilon from what would be written. `_positions()` now reconstructs *only* touched
   entries and leaves the rest as the faired coordinates themselves.

Both are load-bearing. Losing either silently breaks the locality contract.

---

## 3. Candidate A baseline (B-type, real production path)

Real `DISPLACE` + real `LaplacianSmooth` (shipped `use_volume_preserve`, `lambda_factor`
0.12, `lambda_border` 0.04, iterations from `corset_smooth`), evaluated through the
modifier stack — **not** the stand-in Laplacian used to choose the order.

| clearance | raw displaced | **real faired** | detection | after repair | touched | written | outside written set | no-op |
|---|---|---|---|---|---|---|---|---|
| 0.1 mm | 0 | 0 | clean | 0 | 0 | 0 | 0.00e+00 | **YES** `c55621c44ba5` |
| 0.5 mm | 0 | 0 | clean | 0 | 0 | 0 | 0.00e+00 | **YES** `949c89e1aabb` |
| 1.0 mm | 0 | 0 | clean | 0 | 0 | 0 | 0.00e+00 | **YES** `4d40ef9f0492` |
| 2.0 mm | 3 | **4** | FOLD | **0** | 7 | **7** | 0.00e+00 | NO |
| 3.0 mm | 8 | **7** | FOLD | **0** | 14 | **14** | 0.00e+00 | NO |
| 5.0 mm | 176 | 165 | FOLD | **53 residual** | 179 | — | — | **cancels transactionally** |

Zero degenerate triangles at every clearance; `min_area` unchanged. A-type is a no-op at
all six clearances (verified separately, `moldrepairdbg_atype.txt`).

**Reproduce:**
```
RIGO_MATRIX_FIXTURE=btype  blender --app-template rigo_brace --python tools/moldmatrixdbg.py
RIGO_MATRIX_FIXTURE=atype  blender --app-template rigo_brace --python tools/moldmatrixdbg.py
```
Fixtures: `B type model.stl` via `bracefixture.prepare_design(..., "B")`;
`A type model.stl` via `prepare_reference_design()`. Blender:
`C:\Program Files\Blender Foundation\Blender 5.0\blender.exe`.

Other diagnostics: `moldoffsetdbg.py` (clearance sweep + concavity/connectivity),
`moldorderdbg.py` (quality baseline by population + fairing order), `moldrepairdbg.py`
(standalone repair probe), `evidencedbg.py` (painted / sigma / btype evidence cases),
`cutfolddbg.py` (per-stage self-intersections).

---

## 4. Phase-2 objective

**Diagnose the independent B-type downstream non-manifold failure.** It is NOT #37.

The premise that fixing the inner-offset fold would make B-type buildable is **rejected by
measurement**: B-type generation fails at *every* clearance, including ones where the offset
mold is provably clean and Candidate A is a verified no-op.

```
0.1 mm  mold selfX=0, repair no-op       -> CANCELLED: 0 open, 4 non-manifold edges
1.0 mm  mold selfX=0, repair no-op       -> CANCELLED: 0 open, 1 non-manifold edge
3.0 mm  mold selfX 7 -> 0 (repaired)     -> CANCELLED: 0 open, 4 non-manifold edges
```

**Do not propose or implement a downstream fix until the first clean-to-invalid stage is
measured independently at 0.1, 1.0 and 3.0 mm.** Identical final messages do **not** imply
one cause — that assumption has already had to be retracted twice in this investigation.

---

## 5. Primary diagnostic fixtures

| fixture | offset state | Candidate A | final failure |
|---|---|---|---|
| B-type 0.1 mm | clean (selfX 0) | verified no-op | 4 non-manifold edges |
| B-type 1.0 mm | clean (selfX 0) | verified no-op | 1 non-manifold edge |
| B-type 3.0 mm | repaired 7 → 0 | 14 verts written | 4 non-manifold edges |
| A-type, same clearances | clean | no-op | control — must build |

B-type **0.1 mm is the primary fixture**: source scan clean (0 of 89,718 triangles), offset
mold clean, repair inert, so any later failure is isolated from the fold mechanism.

---

## 6. Required ten-stage instrumentation

1. source / corrected body
2. raw displaced offset
3. real faired offset
4. post-repair offset
5. cutter construction
6. keep-interior result
7. boundary resample
8. rim generation
9. outer-wall generation / join / weld
10. final validation

---

## 7. Record at every stage

boundary edges · non-manifold edges · self-intersections · duplicate/coincident vertices ·
zero-area and inverted triangles · connected components · **exact coordinates of invalid
edges** · provenance of incident faces · deterministic recurrence across repeated runs.

---

## 8. Mechanisms Phase 2 must distinguish

- cutter grazing / tangential intersection
- keep-interior classification ambiguity
- open or duplicated boundary loops
- boundary-resample fold
- rim-strip orientation reversal
- inner/outer rim loop correspondence failure
- incomplete weld, or coincident-but-unmerged vertices
- T-junctions from differing loop densities

---

## 9. Issue separation — keep these distinct

| issue | mechanism | status |
|---|---|---|
| **#37** | residual self-intersection of the **final faired inner offset**, scan-dependent | Candidate A prototype corrected, uncommitted; 2.0/3.0 mm reach zero |
| **#43** | painted-path **low-density boundary-resample** fold (cap 48 fails, 84/168 clean) | open, separate |
| **#44** | **station-refinement rim overlap** (6 local overlaps; mold and cut clean) | open, separate |
| **NEW** | B-type **downstream non-manifold** failure | open, undiagnosed — Phase 2 |
| **#42** | trimline as a curve on a persistent inner brace surface | blocked on **both** a reliable inner surface **and** a valid downstream build path |

**#42 wording correction:** resolving #37 alone does **not** unblock #42 on all fixtures.
B-type support additionally depends on the new downstream non-manifold issue.

---

## 10. Non-negotiables

- Preserve transactional cancellation. Never commit a partially repaired inner surface, and
  never a downstream non-manifold brace.
- Do not broaden the repair globally or reduce a requested clearance to force the 5.0 mm
  stress case to pass; it is reported, not accommodated.
- Do not weaken the 2.0/3.0 mm acceptance gate.
- Tests exercise the **installed** copy — run `./install.ps1` after editing `rigo_brace/`.
