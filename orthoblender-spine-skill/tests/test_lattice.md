# Test: Lattice / Derotation

Automated: none yet — add `tools/latticetest.py` with the WASP lattice port (Patch 5).

Test name: Lattice deform + multi-section derotation
Feature: planned port of WASP add_lattice / edit_lattice / rotate_sections
Input: an aligned torso scan
Steps:
1. Add Lattice (cage) around the torso (resolution e.g. 3×3×5).
2. Edit Lattice → move control points → torso deforms smoothly.
3. Rotate Sections → per-height-layer rotation → progressive derotation up the spine.
4. Apply → mesh baked; cage removed; snapshot a history version.
Expected result: smooth deformation, no self-intersection; derotation visibly twists the
torso progressively; circumferences update.
Failure signs: spiky/torn mesh, no effect, whole-body rigid rotation instead of graded.
Clinical risk if failed: incorrect/over-correction; unsafe geometry.
Files involved: correction_ops.py (+ Patch 5 lattice module)
