# User Workflow — Spinal Brace (orthotist guide)

The guided brace workflow. Press **N** in the viewport → **Rigo Brace** tab. The
**Brace Workflow** panel (top) shows your progress, a picture+text hint per step
(Assistance), and the design history (Back / Next / Rollback). Each stage you finish is
saved as a version you can roll back to.

## Stages
1. **Import** — load the patient scan (STL/OBJ).
2. **Clean** — center, Auto-Remesh for clean even topology, fill holes, remove noise;
   select the part to keep; verify before closing the mesh.
3. **Align** — Quad View + Rotate to stand the scan upright, facing front, on the floor.
4. **Landmarks** — place the anatomical points (C7, axilla, apices, iliac crest,
   ASIS/PSIS, trochanter, waist). They drive measurement + pad placement.
5. **Measure** — circumference at the clinical levels (armpit, below-chest, waist, GT);
   values update live as you shape.
6. **Shape** — correct the torso: highlight a region and push/pull by mm; Bend/Twist/
   Stretch; lattice derotation; pressure (red, in) / expansion (blue, out) pads from the
   library; X-ray radiograph overlay for reference. **Always pair a pressure with an
   expansion** (see clinical rules).
7. **Trim Lines** — draw + edit the trim line (RightClick, G, move, RightClick to stop);
   X-ray to see through; one-button smooth; flare the edge for comfort.
8. **Shell** — keep the brace part, scale, give it wall thickness, add ventilation,
   emboss a label.
9. **Export** — compare the design against the original scan (X-ray transparency), run
   the checks, export a print-ready file.

## Tips
- Units are millimetres everywhere.
- View panel: Full Screen / Quad / Ortho + fixed angles (Top/Front/…).
- Nothing here is a prescription — you, the orthotist, review and approve every design
  (see knowledge/clinical_safety_protocol.md).
