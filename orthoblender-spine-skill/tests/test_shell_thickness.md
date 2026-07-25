# Test: Shell / Thickness

Automated: `tools/designtest.py` (generate corset + emboss). Add `tools/thicknesstest.py`
for unified + variable thickness (Patch 7 / WASP weight port).

Test name: Generate shell + thickness
Feature: design_ops (generate_corset, thickness) + planned scale/unified/variable thickness
Input: a corrected torso
Steps:
1. Keep-part selection → keep the brace shell.
2. Scale (mm or %).
3. Apply unified thickness → check wall is even and ≥ minimum (manufacturing_constraints).
4. (Later) variable thickness: reinforce a region, thin an expansion room.
Expected result: solid wall of the set thickness; reinforced/thin zones honored; manifold.
Failure signs: thin spots below minimum, non-manifold wall, self-intersections.
Clinical risk if failed: brace too weak (breaks) or too bulky.
Files involved: design_ops.py, deform_ops.scale_girth
