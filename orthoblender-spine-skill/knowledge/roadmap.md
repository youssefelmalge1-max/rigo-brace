# Spinal Orthotics MVP Roadmap (vs current state)

The MVP ladder from the master skill, marked against what `rigo_brace` already does.

## MVP 0 — Audit & knowledge system  ✅ (this session)
Repo audit, license register, feature matrix, backlog, roadmap, memory + decision
logs created under `knowledge/`. SKILL.md operating contract saved.

## MVP 1 — Spine scan workflow  ✅ (mostly)
Import STL/OBJ, set mm, orient, recenter/drop-to-floor, crop (box-erase), cleanup
(fill holes, remesh, smooth), landmark placement — all present and tested.
Remaining ⛔: patient **project workspace + versioning** (module 1).

## MVP 2 — Rigo/TLSO correction prototype  ✅ → extending now
Pressure/expansion via selection-first live regions plus reusable committed styles;
derotation/elongation via Bend/Twist/Stretch with Lower/Middle/Upper draggable rings and
selectable adjacent segments; before/after via live modifiers.
**Bend/Twist/Stretch technical status: complete and user-validated 2026-07-12.** Future
changes are UI polish only unless a regression test or user case proves a geometry bug.
**Active extension (P0):** Rodin-style **area-select → editable contour lines → carve/
add** — a more direct "sculpt-by-selection" path than the sculpt brush.
Remaining ⛔: clinically classified/prescribed templates; neutral orthotist-authored
styles are reusable now. Self-intersection and overlap safety gates remain.

## MVP 3 — Shell & trimlines  ✅
One editable surface-fitted perimeter, paired inner/outer walls, explicit rounded rim,
strap slots and emboss. A/reference technical gates pass. B generation now cancels
safely when bounded outer-wall repair cannot remove exact intersections; its clinical
trim/surface strategy remains unresolved.

## MVP 4 — Reinforcement & lattice  ⛔
Variable thickness, reinforcement zones (pelvic anchor, thoracic pressure), safe
lattice/ventilation zones with min-bridge thickness, printability validation.

## MVP 5 — Export & clinical report  ⚠
STL export QA now checks units, components, topology, intersections and chosen minimum
wall before exporting the canonical brace. 3MF, clinical report/design notes, and
versioned patient save remain.

## Build progress (uFit-style rebuild, DEC-0009)
- ✅ Patch 1 (DEC-0010, Req 2+6): View panel — Full Screen / Quad View / Ortho +
  View-Modes (Top/Front/Left/Right/Back/Bottom) + Align-in-Quad-View. Operators in
  ui_ops.py (`view_axis`, `toggle_quadview`, `toggle_fullscreen`, `align_quad`),
  panel `RIGO_PT_view`. Verified: tools/viewtest.py (PASS), selftest (ALL_PASS).
- ✅ Patch 2 (Req 4 shell): Brace Workflow panel — Progress bar, Assistance (image hook +
  text per stage), Design History (WASP-ported `stage_next`/`stage_back`/`rollback`,
  one snapshot per major stage as `NN_<patient>_<stage>` in a per-patient collection).
  Operators in operators/history_ops.py; core BRACE_STAGES + brace_stage/brace_patient;
  panel `RIGO_PT_workflow`. Verified: tools/historytest.py (PASS), selftest (ALL_PASS).
  Provenance PROV-0006.
- ✅ Patch 3 (Clean stage): Center Model + Verify Clean-up (new clean_ops.py) + Auto-Remesh
  (existing voxel remesh presented with a Detail slider). Verify highlights non-manifold/
  holes/loose and stashes counts (rigo_boundary/nonmanifold/loose/verify_ok) shown in the
  panel. Verified: tools/cleantest.py (PASS — detect hole→fill→remesh watertight),
  selftest (ALL_PASS). Cleanup pass also done: Scan de-noised, Design shaping de-duped,
  dead props/imports/files removed (DEC-0012).
- ⏭ Next: Patch 4 combined Guided(mm)+Free sculpt, Patch 5 lattice, Patch 6 trim
  X-ray/smooth/flare, Patch 7 shell/ventilation, Patch 8 export/compare.
  Full architecture: C:\Users\youss\.claude\plans\okay-nour-that-is-quirky-plum.md

## Patch 5 — Lattice derotation (DEC-0019, PROV-0008, 2026-07-06) — done
- ✅ lattice_ops.py: auto-fit section cage + per-section twist dials (gradient seed),
  edit points, apply/discard. Fixed vs WASP: Z-axis-in-code (not view axis),
  scale-compensated rotation (no shear), LINEAR interpolation, bbox auto-fit.
  Gates: dials 0/15/30° → 0.8/14.1/29.2° measured, radial drift 0.13 mm, discard
  restores exactly (latticetest PASS; selftest ALL_PASS). ERR-0011: lattice rest span
  = points-1 units, probe before sizing.
- ✅ Patch 6 — Trim-edge finishing (DEC-0020, PROV-0009, 2026-07-06): see-through
  (show_xray), Smooth Trim Edge (CorrectiveSmooth on the RIGO_TRIM_BAND group baked at
  Generate — the cut is only an open boundary pre-Solidify), Flare Edge (radial safe
  edge, 6.000 mm exact at the rim). trimtest PASS; selftest ALL_PASS.
- ✅ Patch 7 — Parametric ventilation + #13 guard (DEC-0021, 2026-07-07): vent_paint +
  vent_grid (tangent-grid + BVH raycast + merged-cylinder MANIFOLD boolean; bridge ≥3 mm
  enforced; trim-rim protected; genus-verified — 11 holes = (χ0−χ1)/2 exactly, 0 new
  defects). generate_corset refuses mid-deform (#13 fixed). venttest PASS; selftest
  ALL_PASS. Discovered #14: corset pinch edge at trim → Patch 8 repair.
- ✅ Auto Trim Lines by Rigo type (DEC-0023, PROV-0010, 2026-07-08): templates
  extracted from the user's A/B reference brace pairs (coverage boundary, 72 θ-bins,
  landmark-normalized); auto_trimline drapes editable top/bottom curves from placed
  landmarks; Generate keeps only the surface between them (fixes the real-torso
  generation bug — head/arms fall outside the profiles). trimlinetest PASS; selftest
  ALL_PASS. Pending: subtype calibration from the user's Rigo classification graphics.
- ⏭ Next: Patch 8 — Verify/Export: scan-compare overlay + QA gates (watertight/
  manifold/min-thickness + #14 manifold repair) + STL/3MF export.

## Patch 4a — Guided Sculpt / CorrectionRegion (DEC-0017, 2026-07-03) — done
- ✅ RigoCorrectionRegion data model on the object + region_ops (add/apply/mirror/remove)
  + Guided Sculpt box (UIList) in the Mesh stage. Gates: 0.0000 mm error, 10.000 mm exact,
  outside untouched, no topology change, 0.05 s (regiontest PASS; selftest ALL_PASS).
- ✅ Patch 4b (DEC-0018, 2026-07-06): geodesic circular quick-region at the 3D cursor;
  falloff choice at Add; X-ray overlay Move/Rotate/Scale + Lock-to-model (no-jump parent
  toggle); Remold presented as "Free Sculpt (brushes)". Gates: circle seed weight 1.000
  exact + geodesic containment (regiontest PASS); X-ray lock jump 0, follows model
  exactly (xraytest PASS); selftest ALL_PASS. ERR-0010: never hold RNA vert refs across
  bpy.ops in tests.
- ⏭ Patch 4 leftovers folded forward: per-region falloff REBAKE (edit falloff after
  add), retire remold_ops module name. Next major: Patch 5 — lattice + multi-section
  derotation.

## Quad remesh (DEC-0016, 2026-07-03) — done
- ✅ `rigo.quad_remesh` (QuadriFlow) + Quad Faces setting in the Clean stage; watertight
  guard enforces Fill-Holes-first. Proven: 107,726 tris → 7,697 faces 100% quads,
  watertight, manifold (quadtest PASS). Exoside = learn-of-only, not bundled (license).

## Issue-fix wave (DEC-0015, 2026-07-03) — done
- ✅ Full 70-operator live MCP audit → issues.md; re-verify reduced 12 findings to 3 real.
- ✅ Remold fixed for Blender 5.0 (remoldtest PASS); history keyed to brace_patient
  (historytest PASS incl. fallback); black captures resolved-by-remold-fix (bright ~0.73
  through the whole pipeline), hardening rules in docs/blender_mcp_setup.md.
- 🟡 Open low-priority: #13 generate_corset mid-deform copies the live modifier (fold
  into Patch 7); #B1 modal-only ops get execute fallbacks as stages are rebuilt.

## Tooling upgrades (DEC-0014, 2026-06-18) — user-approved
- ✅ **Blender MCP live loop** — INSTALLED + verified by the agent 2026-07-03 (server
  `blender: uvx blender-mcp` Connected; addon enabled in Blender 5.0 userpref port 9876;
  get_scene_info + execute_code both `success` on a live rigo_brace session). Launcher
  `tools/mcp_bridge.py`. Remaining: a Claude Code restart to load `blender.*` into the
  agent toolset. See docs/blender_mcp_setup.md. Fixes the root cause of past 3D errors.
- ⏭ **Patch 4 built on the CorrectionRegion data model** — measurable pressure/expansion
  as data (knowledge/correction_region_model.md), not untracked vertex moves.
- ⏭ **Quantitative test gates + fixtures/** — PASS=True → hard numeric gates (displacement
  ±0.05 mm, exact undo, zero new non-manifold, <2 s, scan unchanged). First: regiontest.py.
- ❌ Rejected: 18-sub-skill explosion; vendoring OpenAEC/computational-design/Blender-Dev-
  Tools packs (wrong domain + CC-BY-NC-ND). trimesh deferred (bmesh suffices for now).

## Immediate sequence (legacy P0 note)
1. **P0 area-select → contour-line carve/add** (now Req 8; reuses select_ops).
2. P1 export/manufacturing QA module (safety-critical before any real printing).
3. P1 variable thickness / reinforcement.
4. P2 patient project workspace + clinical template save.

## 2026-07-13 trimline/generator correction

- Added a first/default **Rigo-Cheneau Reference** profile with a measured millimetre
  opening; it is a neutral starting silhouette, not an automatic prescription.
- Replaced generic 3D control movement with **Edit on Body** raycast dragging plus
  **Fit** and live Shrinkwrap. The installed regression deliberately displaces a point
  60 mm and proves both controls and evaluated curve return to 1.500 mm from the body.
- Replaced post-cut Solidify with paired inner/outer walls offset along normals retained
  from the complete corrected torso, one bridged rim, and rim-aware QA.
- A/reference geometry passes closed/manifold, one-component and exact-intersection
  gates at the accepted tested settings. The earlier B diagnostic shell with two
  components, 16 intersections and a 0.358 mm local wall is no longer produced: current
  generation cancels before replacement when bounded outer-wall repair cannot remove
  overlap. This contained cancellation is recorded separately from B readiness; the
  readiness gate remains false. The next generator
  ticket is orthotist-reviewed B trim/surface intent plus signed correction-deviation
  preservation, followed by four-view visual approval.
