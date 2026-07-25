# Rigo Brace Designer — Blender Add-on

A clean, focused Blender add-on for orthotists to design **Rigo-Chéneau spinal
braces** fast — without the clutter of full Blender. Built on Blender 5.x.

This is **Phase 0 (skeleton)**: the full pipeline is laid out as a simple
top-to-bottom panel, with the import, remesh, smooth, anatomical-landmark,
thickness, and export stages already working.

## Pipeline (panel order)

1. **Import Scan** — load a patient body scan (`.stl` or `.obj`).
2. **Remesh** — rebuild clean, even topology from the raw scan.
3. **Smooth** — relax scan noise and bumps.
4. **Anatomical Landmarks** — place clinical points (C7, scapula, axilla,
   curve apices, iliac crest, ASIS/PSIS, trochanters, waistline). These will
   drive automatic pad and relief placement in later phases.
5. **Thickness** — give the brace a solid printable wall.
6. **Export Brace** — save a print-ready STL.

> Coming next: remold/sculpt tools, free-form **correction** of the curve
> (Lattice deform), the **Rigo pad & relief library**, and trimline cutting.

## Install in Blender 5.x

1. Zip the `rigo_brace` folder (the folder that contains `blender_manifest.toml`).
   - On Windows: right-click `rigo_brace` → **Send to → Compressed (zipped) folder**.
   - Or run the helper: `python build.py` (creates `rigo_brace.zip`).
2. In Blender: **Edit → Preferences → Get Extensions → ▼ (top-right) →
   Install from Disk…** and pick the zip.
3. Enable it if not auto-enabled. Press **N** in the 3D Viewport and open the
   **Rigo Brace** tab.

## Notes

- The panel labels values in **mm**; operators convert assuming 1 Blender unit
  = 1 m. Set your scene unit scale to taste — unit handling is finalized in a
  later phase.
- Each shaping step applies a modifier and is fully undoable (`Ctrl+Z`).

## Project layout

```
rigo_brace/
  blender_manifest.toml     extension metadata (Blender 4.2+/5.x)
  __init__.py               registers everything
  core/__init__.py          settings + anatomical landmark definitions
  operators/
    io_ops.py               import scan / export brace
    mesh_ops.py             remesh / smooth / thickness
    landmark_ops.py         place / clear landmarks
  ui/panels.py              the Rigo Brace side panel
```
