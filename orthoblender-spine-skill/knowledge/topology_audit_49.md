# #49 Topology-Dependency Audit — can the system survive a topology-changing commit?

2026-08-15. Four parallel audit passes covered: the region system; every other operator
module + core libraries; the downstream design chain (trimline → brace → QA → export);
UI/persistence/template/undo. Every finding carries file:line evidence in the audit
transcripts; this document keeps the load-bearing conclusions.

## Headline verdict

**No persisted subsystem is incompatible with footprint-local refinement.** Every
durable artifact is position-anchored (landmark empties, world-space curves, unbound
Lattice/Shrinkwrap modifiers), name-keyed (vertex groups, masks, committed flags,
modifier bindings), chart-based (region snapshots, style library — verified index-free),
or hash-guarded (geometry signatures that *intentionally* invalidate on any topology
change: QA, export blocking, trimline VERIFIED stamp all self-invalidate correctly).
Raw vertex/face index lists are persisted **nowhere** — not in IDProps, not in JSON,
not in the config dir.

The topology-dependence concentrates in exactly two places:

1. **Inside `RIGO_OT_region_apply` itself** — all transient index-keyed state
   (weights dict, member/affected sets, pre-normals, adjacency, faired directions,
   fold pairs, baseline face indices) and the per-index positions rollback. The
   rollback is INCOMPATIBLE with refinement and is REPLACED, not adapted, by the
   dry-run transaction (refusal = never write). The transient state must be built
   AFTER refinement, inside the transaction — which the approved ordering already
   requires.
2. **The test layer** — regiontest's `nverts0` equality, `before[v.index]` maps,
   post-commit vertex lookups; being rewritten as evidence-layer work (step 1).

## The one hard implementation constraint (all four audits converged)

**The commit must mutate `scan.data` IN PLACE via BMesh with custom-data
interpolation (`bmesh.ops.subdivide_edges` + `bm.to_mesh`), never rebuild the mesh
from arrays, never swap the scan object.** This single constraint makes the three
element-attached stores survive automatically:

- all regions' vertex-group masks (deform layer interpolates — including OTHER
  uncommitted regions overlapping the refined footprint);
- the painted custom-trim mask (`RIGO_CUSTOM_TRIM_MASK` POINT color attribute);
- painted Edit-Mode selection flags.

Object identity preservation additionally keeps: trim perimeter Shrinkwrap bindings,
`settings.scan_object`, landmark/deform IDProps.

## Blocking items to handle in the implementation (none justify stopping)

| # | Item | Handling |
|---|---|---|
| B1 | Per-index rollback (`pre_positions`) cannot un-subdivide | Deleted; dry-run bmesh transaction refuses by never writing |
| B2 | All commit transients captured pre-refinement | Pipeline reorder: refine first, then read weights / normals / baseline / fold pairs / BVHs from refined topology (also required so new verts get displaced at all) |
| B3 | Overlapping uncommitted region masks depend on deform-layer interpolation | Hard requirement + regression gate: region B's mask integral preserved across region A's refining commit |
| B4 | **"Rigo Corset Base" stale-base rebuild** (design_ops `_rebuild_existing_base`): Apply/Reset Trim Line rebuilds the brace from a frozen PRE-commit body, then stamps the CURRENT scan signature — provenance laundering. Pre-existing bug; #49 makes divergence guaranteed | Commit path must invalidate the cached base (delete `CORSET_BASE_NAME` or stamp it with its own source signature checked at rebuild) |
| B5 | `RIGO_CUSTOM_TRIM_MASK` guard detects loss, not scrambling | BMesh constraint covers it; add regression: CUSTOM_PAINT brace still generates after a refining commit |
| B6 | Live "Rigo Active Deform Segment" during commit → stale gain on new verts | Refuse commit while the deform modifier is live (mirror pad_ops' guard) |
| B7 | Scan verify counters (`rigo_verify_ok` etc.) show pre-commit stats forever | Delete those keys in the commit path (cosmetic) |
| B8 | Panel dirty-flag lag | Already handled: `region_apply` calls `mark_brace_dirty` in the same transaction |
| B9 | Other regions' `_evaluated_positions` count-guard after commit | Previews are name-keyed DISPLACE modifiers (count-agnostic); each operator re-reads fresh — verified no cross-commit cached arrays exist |
| B10 | Test layer: regiontest T1/T2, regionuitest's vertex-20000-after-commit lookup | Rewritten alongside step 4 (position-based, footprint-scoped count invariant) |

Documented non-blocking behavior: every commit (refining or not) flips the trimline
VERIFIED badge to STALE and marks the brace dirty until Update Brace — that is the
signature system working as designed. `region_edit` on a refined overlap shows a
resampled (finer) border — approximation, not corruption. Slot/rivet markers can
drift positionally off a rebuilt shell — pre-existing, positional, caught by cut
gates.

Also recorded (independent of #49): operators genuinely missing UNDO —
`rigo.place_slot`, `rigo.pick_landmark`, `rigo.place_pad`, `rigo.paint_select`,
`rigo.erase_toggle`, `rigo.custom_trim_paint` — backlog, not in this task's scope.
