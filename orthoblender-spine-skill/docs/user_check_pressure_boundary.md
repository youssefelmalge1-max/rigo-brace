# User Check — Pressure / Expansion Boundary Authoring

Readiness: **READY FOR USER CHECK — author/save/regenerate slice only.**

The complete Pressure/Expansion feature is not ready: deterministic deformation Preview,
Cancel and Commit are still pending. Do not clinically validate the deformation yet.

## Before checking

1. Save any open Blender work.
2. Close Blender completely; the add-on was reinstalled and needs a fresh process.
3. Launch the **Rigo Brace** desktop shortcut.
4. Import a torso scan and apply the correct units/orientation.

## Check the boundary workflow

1. Open **Mesh Edit** → scroll to **Pressure / Expansion**.
2. Select **Pressure (in)** or **Expansion (out)**.
3. Click **Draw New Boundary**.
4. In the viewport, left-click 5–10 points around the intended area.
5. Press **Enter** to close it. Backspace removes the last point; Esc cancels.
6. Expect a closed red line for Pressure or blue line for Expansion.
7. Click **Edit Boundary**. Drag a blue control point with `G`; drag green handles to
   change the curvature. Press `Tab` to leave Edit Mode.
8. Click **Save Boundary…**, give it a unique name, and confirm.
9. Clear placed boundaries with the trash button.
10. Select the saved entry (marked with `★`) and click **Generate Saved**.
11. Click a new position on the scan; right-click or Esc ends placement.
12. Click **Edit Boundary** again and verify that the saved curve and handles return.

## Pass checks

- Draw New Boundary accepts viewport clicks and Enter creates one closed outline.
- Pressure is red; Expansion is blue.
- Edit Boundary exposes movable points and Bézier handles.
- The saved entry survives a Blender restart.
- Generate Saved reproduces the authored non-circular boundary, not a generic circle.
- The regenerated boundary remains editable.

## Known limits — not a pass/fail surprise

- **Apply Shapes is still the legacy destructive operation. Do not use it repeatedly.**
- Size does not yet resize an already placed boundary.
- Rotation/orientation controls and deterministic Preview/Cancel/Commit are pending.
- This test proves geometry authoring fidelity, not clinical correctness of placement.

If a step fails, report its number and attach one screenshot with the Pressure / Expansion
panel visible.
