# Test: Remesh

Automated: covered partly by `tools/scancleantest.py`. Add `tools/remeshtest.py` with the
Clean stage (Patch 3 — Auto-Remesh).

Test name: Auto-Remesh keeps anatomical form
Feature: mesh_ops.remesh (voxel REMESH) / planned Auto-Remesh
Input: a body-sized torso scan
Steps:
1. Note the overall shape + key landmark positions.
2. Set voxel/detail; Remesh.
3. Compare: even topology, no large form change, landmarks still valid.
Expected result: cleaner even mesh; silhouette/dimensions preserved within tolerance.
Failure signs: over-smoothed/lost detail, huge triangle count, shifted form, holes.
Clinical risk if failed: distorted base → wrong correction geometry.
Files involved: mesh_ops.py (+ Patch 3 clean module)
