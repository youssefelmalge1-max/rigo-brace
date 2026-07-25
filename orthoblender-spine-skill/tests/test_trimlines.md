# Test: Trim Lines

Automated: `tools/outlinetest.py`. Extend when X-ray + one-button smooth + flare land
(Patch 6) → add asserts to a `tools/trimsmoothtest.py`.

Test name: Edit + apply a trim line
Feature: design_ops (edit_outline, apply_outline, reset_outline) + planned X-ray/smooth/flare
Input: a generated corset / shell
Steps:
1. Edit Trim Line → drag control points (RightClick, G, move, RightClick to stop).
2. Toggle X-ray to see through the shell while editing.
3. One-button Smooth the curve; set flare width.
4. Apply Trim Line → shell re-cut to the variable-height outline.
Expected result: shell trimmed to the edited curve; edge smoothed + flared; reset returns
to a flat cut.
Failure signs: cut ignores edits; jagged/sharp edge; non-manifold after cut.
Clinical risk if failed: impingement at axilla/neckline; sharp edges on skin.
Files involved: design_ops.py
