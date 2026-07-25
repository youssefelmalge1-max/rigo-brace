# Pressure / Expansion Feature Specification

Status: revised after manual Blender feedback on 2026-07-11. Selection-based live
pressure/expansion is **PARTIAL / INFRASTRUCTURE ONLY**: installed-copy geometry passes,
but the orthotist's fresh-session visual check is pending. Committed-region Save/Import
is implemented; self-intersection rejection is not implemented yet.

## Clinical and CAD conclusion

A Rigo-Cheneau contact area is not a universal circular pad. Its level, shape,
orientation, counterforce relationship and paired expansion room depend on the curve
pattern and intended 3D correction. The add-on may store and reproduce geometry authored
by an orthotist, but it must not label a generic oval as a clinically correct iliac-crest
pressure.

Research basis:

- [3D Rigo Cheneau-type brace principles](https://pmc.ncbi.nlm.nih.gov/articles/PMC5356257/)
- [Rigo classification and pressure/contact areas](https://pmc.ncbi.nlm.nih.gov/articles/PMC2825498/)
- [CAD/CAM and FEM orthotist iteration](https://pmc.ncbi.nlm.nih.gov/articles/PMC5525241/)
- [Digital mould rectification and iliac-crest geometry](https://www.mdpi.com/2076-3417/11/10/4665)
- [Measured Cheneau brace interface pressures](https://pubmed.ncbi.nlm.nih.gov/18609033/)

Clinical location, amount and coupling remain orthotist decisions.

## Decision from manual testing

Point-click curve authoring was difficult, and editing a curve could feel detached from
the body. A painted mesh selection is now the source of truth. The old curve operators
remain registered so legacy files can load, but their controls are removed from the main
panel.

## Current workflow

1. Paint mesh faces; Grow, Shrink and Ctrl-remove refine the area.
2. Choose Pressure or Expansion, amount in millimetres, feather and falloff.
3. **Create Live Region** builds a weighted vertex group and a non-destructive Displace
   preview. Each vertex moves along its local surface normal.
4. Change the active region's Kind or Amount and press **Update Preview**. The same
   modifier is updated, so values do not accumulate.
5. **Edit Selection** restores the weighted mask as editable mesh faces. Modify the
   selection, then press **Update Preview** to rebuild its weights.
6. **Commit** applies the preview once. A committed region rejects a second commit.
7. **Ready Circular Region** creates a quick surface-geodesic circle at the 3D cursor.
8. **Save Committed Style** stores the authored mask, kind, amount and falloff globally.
9. **Import at Cursor** reprojects the style onto another scan as an editable live region.

## Current data model

Each `RigoCorrectionRegion` stores its kind, centre, mean direction, magnitude, measured
radius, falloff, vertex-group mask, opposing-region link, enabled state and orthotist
review flag. The preview modifier is named from that mask and uses Blender `NORMAL`
displacement with millimetres converted to metres.

`region_library.json` stores reusable surface-local point/weight samples, sampling and
curvature tolerances, kind, amount, falloff and the mandatory review flag. Patient
placements remain on the patient mesh; library templates remain global per PC.

## Verified acceptance gates

Installed Blender 5.0.1 `tools/regiontest.py` proves:

- pressure preview peak is 10.000 mm with local-normal error 0.0000 mm;
- the base mesh is unchanged before commit;
- Update Preview replaces 10 mm with 7.000 mm rather than producing 17 mm;
- Edit Selection restores selected faces and rebuilds the preview;
- Commit bakes 7.000 mm once and removes the preview modifier;
- vertices outside the mask do not move;
- vertex count and non-manifold edge count do not change;
- mirrored expansion and the geodesic circular region remain functional.

`tools/boundarytest.py` also executes the legacy boundary-creation path after the
Enter-key crash fix. Interactive Enter timing still requires the user check.

Installed `tools/regionstyletest.py` proves a committed 8.000 mm style is saved, rejected
before Commit, reloaded from JSON, imported onto a target with different topology as an
editable non-destructive 8.000 mm preview, committed exactly once, and deletable.

## Reusable selected shapes — implemented

The implementation saves an orthotist-authored mask in a surface-local millimetre frame,
reprojects samples to the target surface, adapts to target mesh spacing, rebuilds the
weighted mask and preserves kind, depth, falloff and `requires_orthotist_review=true`.
Imported styles remain editable before Commit.

## Remaining safety gates

- Detect or reject self-intersection at extreme depth or concave anatomy.
- Define and test overlapping-region behaviour.
- Test exact undo after Commit and interactive style scale/rotation.
- Confirm the generated corset follows the committed rectified mould.
- Complete a live iliac-region design review with the orthotist before clinical use.
