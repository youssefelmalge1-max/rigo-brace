# Test: Export Validation (manufacturing QA)

Automated: none yet — add `tools/exportqatest.py` (Patch 8). Use
`scripts/mesh_quality_metrics.py` for a quick manual check meanwhile.

Test name: Print-readiness validation
Feature: planned Verify/Export stage (compare-vs-scan + QA + export)
Input: a finished brace shell
Steps:
1. Show original scan + design as X-ray transparency → deviation looks like the intended
   correction (not random).
2. Run QA: units mm, manifold, watertight, min wall thickness, no sharp/degenerate edges,
   no self-intersection.
3. Export STL/3MF → re-import → identical + manifold.
Expected result: all QA gates pass; exported file matches; clinical checklist signed.
Failure signs: non-manifold, sub-minimum thickness, wrong units/scale, deviation wrong.
Clinical risk if failed: unprintable or unsafe brace reaches fabrication.
Files involved: io_ops.py (+ Patch 8 QA module); see knowledge/qa_test_protocol.md
