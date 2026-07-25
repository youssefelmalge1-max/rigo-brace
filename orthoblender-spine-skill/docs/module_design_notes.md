# Module Design Notes

Per-module intent + status. Status: ✅ done · 🔶 partial/legacy · ⛔ planned.

- **ui_ops** ✅ — workflow nav (set/step_tab) + view (view_axis, quadview, fullscreen,
  align_quad) + viewport options. Patch 1.
- **history_ops** ✅ — design history (stage_next/back/rollback), WASP port. Patch 2.
- **io_ops** ✅ — import_scan / export_brace. Export QA to extend (Patch 8).
- **scan_ops** ✅ — apply_units (re-frame + double-apply guard), realign/move/recenter,
  fill_holes, erase_toggle. Feeds the Clean stage (Patch 3 adds center + auto-remesh +
  verify gate).
- **mesh_ops** ✅ — remesh / smooth / thickness. Remesh → Clean stage; thickness → Shell.
- **landmark_ops** ✅ — pick/place/clear landmarks (18 points). Drive measure + pads.
- **deform_ops** ✅ — Bend(Y)/Twist/Stretch(Z+lock) with three draggable segment rings
  (drivers); scale_girth; X-ray radiograph overlay (import/grab) — enhance with full
  transform + apply (Patch 4). Stage 6.
- **pad_ops + core/pad_library** ✅ — pressure/relief outline shape library
  (place/edit/record/favourite/mirror/apply, per-PC json). Stage 6.
- **region_ops + core/region_library** ✅ — selection-first live correction regions plus
  committed style save/import across differing mesh topology.
- **select_ops** ✅ — Edit-mode region paint + push/pull/thicken/smooth/delete (mm). The
  seed for the combined Guided sculpt (Patch 4). Cleanup: drop unused SELECTION_VGROUP.
- **correction_ops** 🔶 — free-form lattice cage; to be folded into the Patch 5 lattice
  module (+ WASP multi-section derotation).
- **remold_ops** 🔶 — sculpt-brush remold; to be folded into the Patch 4 Free sculpt mode.
- **design_ops** ✅ — generate_corset, editable trim outline, slots, emboss. Stage 7/8;
  add X-ray + one-button smooth + flare (Patch 6), part-selection + ventilation (Patch 7).

## Planned modules
- **Patch 3 clean_ops** — center, auto-remesh (controllable), verify-clean gate.
- **Patch 4 sculpt_ops** — combined Guided(mm)+Free; X-ray overlay transform.
- **Patch 5 lattice_ops** — WASP add/edit lattice + rotate_sections derotation.
- **Patch 6** — trim X-ray + CorrectiveSmooth + flare on design_ops.
- **Patch 7** — keep-part + scale + unified thickness + parametric ventilation (hole grid).
- **Patch 8 export_ops** — scan-compare (X-ray) + QA gates + export.
- **Later** — variable thickness (WASP weight), components library, clinical templates.

## Cleanup ledger (remove only after replacement passes tests)
- ✅ 2026-06-17 — Scan stage de-noised (UI-only): dropped the shaping suite
  (Push/Pull/Thicken/Smooth-region) and the Transform box from `_draw_scan`. Shaping now
  lives ONLY in the Mesh/Shape stage (the shared `_draw_select_box`); Scan uses a new
  `_draw_clean_select` (paint → grow/shrink/clear/invert → Delete). Alignment
  (Rotate/Move/Recenter) relocated into the View panel's new "Align" box. Operators
  untouched. Verified: selftest ALL_PASS, scanshot draws clean. (DEC-0012)
- ✅ 2026-06-17 — Design stage de-duped: removed the repeated `_draw_select_box` shaping
  block from `_draw_design` (shaping is the Mesh stage's job; corset openings use the
  trim-line + slots). `_draw_select_box` now lives in the Mesh stage ONLY.
- ✅ 2026-06-17 — dead code removed: `SELECTION_VGROUP` (const + unused import in
  select_ops), dead props `select_symmetry` + `select_brush_size` (core); stale root
  files wstest/hdr/probe_result.txt deleted. Verified selftest/selecttest/designtest PASS.
- core: dead `select_symmetry` property.
- root: stale `wstest_result.txt`, `hdr_result.txt`, `probe_result.txt`; obsolete
  one-off `tools/*shot.py`/probe scripts once their feature is verified.
- correction_ops / remold_ops: superseded bits after Patch 4/5.
