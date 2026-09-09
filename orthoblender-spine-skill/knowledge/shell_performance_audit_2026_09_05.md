# Shell generation performance investigation — 2026-09-05

## Problem

The user reports that Generate Brace takes too many seconds and asks whether the
cause is their computer or the implementation. Scope: diagnosis; no production
code, geometry, settings, or running Blender session changed.

## Repository Evidence

- UI: `rigo_brace/ui/panels.py:724` calls `rigo.generate_curve_corset`.
- Execution: `operators/curve_build_ops.py:1906` → `_build:1935` → private base
  preparation → `_build_curve_corset:1799` → cut → shell → validation → commit.
- Inputs: evaluated scan/base, trim perimeter and Scene settings. Candidates are
  disposable object/mesh copies. Cutting, welding, resampling and shell creation
  change topology. Geometry uses candidate-local metres; UI thickness uses mm.
- Existing `gentimedbg_result.txt`, written today at 13:23 +04:00: 89,144 input
  faces, 117,726 output faces, 4 mm wall, FINISHED, DONE=True, 11.36 s **profiled**.
- Existing `finishtimedbg_result.txt`, written today at 13:19 +04:00: same output
  face count, generation FINISHED, 7.73 s **unprofiled**. These are separate saved
  runs, not fresh measurements or a controlled measurement of profiler overhead.
- SHA256 comparison found no differences between repository and installed add-on
  Python/TOML files. This does not verify modules loaded by a running process.

| Stage in saved cProfile run | Cumulative seconds | Share of total |
| --- | ---: | ---: |
| Cut and prepare boundary | 7.303 | 64.3% |
| Boundary resampling, included in the row above | 3.752 | 33.0% |
| Construct paired shell and rim | 1.943 | 17.1% |
| All remaining work | 2.113 | 18.6% |

Do not add nested cumulative times. These percentages describe the instrumented
run only, not the user's current case.

## Current machine observations

Read-only Windows CIM probes during this audit found a Ryzen 7 5800H (8 cores,
16 logical processors), 16,625,724 KiB visible RAM (~15.86 GiB), 359–444 MiB
available RAM, and 96–97% committed memory. PagesInput/sec snapshots ranged
43–2,274. This establishes substantial memory pressure and page-in activity;
it does not measure how much of a brace build's delay comes from paging.

One Blender process was already running. It started at 12:55 +04:00; installed
`design_ops.py` has a 13:15 modification timestamp. A stale loaded module is
possible, not proven: the process may have reloaded its add-on. The installed
generator file predates that process, so this is not evidence that the old
57-second point-in-polygon implementation is still loaded.

## Classification

P2 workflow latency: PERFORMANCE, BLENDER_STATE, TESTING. No new geometry defect
or defective hardware established.

## Activated Experts

Ryan Schmidt geometry-systems lens: whole-mesh versus boundary-local work.
Campbell Barton Blender-platform lens: execution, copies, UI and module lifecycle.
Geometry reliability lens (primary investigator): timing provenance and resource
confounders. Independent agents read their own skills and exchanged findings for
cross-review. These are engineering lenses, not reviews by the named people.
Clinical, biomechanics and Boolean-solver councils were unnecessary for this
diagnosis: no clinical choice, mathematical predicate or solver is being changed.

## Independent Findings

### Geometry systems

`_dissolve_shortcut_chords:1207` sorts all BMesh edges before rejecting interior
edges. Filtering first and stable-sorting candidates with the same key is a
bounded optimization candidate. `_split_boundary_ear_quads:1154` scans every
face; early rejection or ordered boundary-face worklists may reduce allocations.
Two `_source_surface` builds cost 0.507 s combined; sharing an immutable per-build
snapshot is another candidate, subject to confirming identical geometry state.
None of these candidates has been implemented or timed.

### Blender platform

The operator executes synchronously with no progress/yield mechanism. Every click
rebuilds the candidate. Base preparation costs only 0.474 s in the saved profile,
so caching the base alone offers limited benefit. Apply & Verify also builds and
discards a full candidate (`trimverify_ops.py:296`), so subsequently generating
performs another build. This is deliberate verification, not a handler loop.
The inspected generation path uses Python, NumPy, BMesh and BVH operations and
has no GPU compute/render-device selection; rendering settings are not an
evidenced remedy for this path.

## Cross-Review

Both lenses agree that boundary work is the main measured stage. Geometry review
requires preserving BMesh ordering, especially stable-sort ties. Blender review
requires preserving owned candidates, failure cleanup, undo and explicit commit;
moving live bpy operations into arbitrary threads is not a safe shortcut.
Reliability rejects a fresh second Blender launch under the observed memory
pressure: it could disrupt the user's session and confound the timings. Saved
results are explicitly historical. Installed-file parity does not prove loaded
module parity or performance on the user's own mesh.

## Disagreements

No unresolved disagreement. End-to-end speedup estimates and attribution of the
user's delay between memory pressure, loaded code and mesh complexity remain open.

## Root Cause

In the saved reference run, trim preparation dominates generation; boundary
repair scans/sorts untouched interior topology, adding whole-mesh work to a local
operation. Current memory pressure is a separate plausible contributor to the
user's observed delay, not a quantified cause of that saved runtime.

## Council Verdict

**HARDEN**: pursue narrowly scoped boundary-work optimization after collecting a
controlled baseline. **KEEP**: current geometry checks and transactional commit.
**DEFER**: caching/reuse architecture and responsive progress UI; neither has a
demonstrated end-to-end speedup here.

## Minimal Safe Change

This task records the diagnosis only. First save work, close unused applications,
reopen Blender and time the same case. For a future patch, filter chords before
sorting, preserving exact ordered candidates; pass implementation-gate before
editing production. Avoid using coarser patient geometry as an automatic shortcut.

## Long-Term Architecture

DEFER explicit boundary worklists and immutable per-build spatial data until the
local candidate and its invalidation rules are proven.

## Regression Tests

For a future patch compare old/new ordered chord identities on each pass, then
coordinates, face topology, metadata and validation results. Include the reference
4 mm shell, the known 2 mm/6-segment rim case and a denser scan. No new defect was
fixed here; no fresh Blender regression suite was run or claimed.

## Performance Tests

After memory pressure is relieved, collect repeated unprofiled same-case timings
in fresh Blender, with revision, scan density, settings and available memory.
Use at least three runs for a preliminary median/range; use a larger repeated
sample before presenting a credible p95. Profile separately for stage attribution.
Compare Generate and Apply & Verify separately. The user's exact seconds, scan
and settings were requested but not available during the audit.

## Blender Integration Risks

Synchronous execution explains an unresponsive interface during calculation.
Progress feedback alone would not reduce total computation. Do not terminate the
user's process or launch concurrent geometry workloads at near-full commit.

## Clinical Risks

No geometry or clinical settings changed. Future performance work must retain
trim coverage, paired wall thickness, deterministic rim topology and validation.

## Implementation Instructions

Diagnosis complete; implementation deferred. No reinstall required for this
documentation-only audit. Restarting the existing Blender process after saving is
useful to eliminate the possible stale-module confounder. The sample timings do
not establish a performance guarantee for a different scan or corrected surface.

## Follow-up — 2026-09-06: fresh timings completed

The user closed Blender and authorized rerunning the measurement. No Blender was
running at preflight; installed/source Python and TOML hashes still match. Memory
commit dropped to 85%, with about 9.2 GiB virtual headroom, permitting one fresh
Blender process at a time. Physical RAM remained scarce: 248–747 MiB available in
snapshots across the session, with page-in activity. This is not an idle-machine
or paging-free performance baseline.

Added tools/genbench.py: a diagnostic-only harness following the existing GUI
fixture/timer pattern. It records actual settings, installed module path, Blender
version, preparation and unprofiled generation elapsed time, completion status,
wall metadata and output counts. Each invocation creates one sample design in its
own fresh process, exits without saving, and writes a separate result file. No
production add-on/template code or installed files changed; reinstall unnecessary.
The prior council's baseline experiment authorizes this harness; it implements no
geometry fix, changes no operation order, and makes no new clinical decision.

| Fresh process / artifact | Generation seconds | Result |
| --- | ---: | --- |
| genbench_20260906_1_result.txt | 8.82494 | FINISHED, done=true |
| genbench_20260906_2_result.txt | 8.68290 | FINISHED, done=true |
| genbench_20260906_3_result.txt | 9.12768 | FINISHED, done=true |

Median 8.82494 s; range 8.68290–9.12768 s. Three samples support a preliminary
median/range, not a credible p95. Generation timing excludes launch and fixture
preparation. Preparation took 0.286–0.388 s. Blender 5.0.1; reference RIGO_CHENEAU
A scan (89,144 faces), 25 mm opening, 4 mm thickness, 3 mm liner offset, fairing 5,
1 mm fillet / 8 segments. All runs produced 67,836 vertices / 117,726 faces and
recorded 4 mm requested thickness. Matching counts do not establish bit-exact
geometry equivalence. The production generation validations completed; no broad
regression, UI visual inspection, undo or save/load test is claimed.

A fourth, separate fresh process ran existing tools/gentimedbg.py and finished:
gentimedbg_20260906_result.txt records WALL=11.87s and DONE=True. The historical
profile is preserved as gentimedbg_20260905_result.txt. In the fresh profile:

- _cut_surface: 7.386 s cumulative (~62% of total).
- _resample_cut_boundary: 3.681 s, INCLUDED in _cut_surface.
- _build_strict_shell: 2.376 s (~20%).
- _validate_finished_rim: 0.545 s; metadata bake: 0.726 s.

These confirm the earlier stage attribution. Ordinary generation remains about
nine seconds despite a fresh process with current installed files. The earlier
single saved 7.73 s unprofiled measurement is not a matched pre-restart control;
no causal restart speedup, memory-related time fraction or code regression can be
inferred from comparing it to today's median. The candidate boundary optimizations
remain unimplemented and unbenchmarked. Verdict remains HARDEN, targeting redundant
whole-mesh work while retaining geometry checks and deterministic operation order.

Readiness: diagnostic evidence only; no new feature for UI acceptance. To manually
compare, use the supplied A reference fixture and recorded settings, then Design
> Select Design > Generate Brace. Expected result: a generated shell after roughly
nine seconds under these conditions; this is an observation, not a guarantee for
other scans. No restart is required for this diagnostic-only repository change.
