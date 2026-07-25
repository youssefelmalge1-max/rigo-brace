# User Check — Selection Pressure / Expansion

Readiness: **PARTIAL / INFRASTRUCTURE ONLY**. Installed-copy geometry and operator paths
pass; the orthotist's fresh-session visual check below is still required. The reusable
shaped-selection library is not implemented yet.

## Restart

Close every Blender window, then start **Rigo Brace** from the Desktop shortcut. The
installed add-on was replaced and an already-open Blender process will still have the
old Python classes loaded.

## Test fixture

Use `Brace Sample.stl` first. Import it in **1 File**, choose **Millimeters**, apply the
units, and confirm the torso is upright and approximately 252 mm tall. Clinical review
on a patient scan comes only after this mechanical check passes.

## Exact check

1. Open **4 Mesh Edit**.
2. In **Select Area**, press **Paint Area (Alt+P)** and paint a closed patch on one side
   of the torso. Ctrl removes faces; **Grow/Shrink** adjusts the border.
3. In **Pressure / Expansion (Selection)** choose **Pressure**, set Amount to `10 mm`,
   Feather to `10 mm`, and Falloff to **Smooth**.
4. Press **Create Live Region**. The surface must move inward immediately with a soft
   transition. This is a preview; the base mesh has not yet been permanently changed.
5. In the active region controls below the region list, change Amount to `5 mm`, then
   press **Update Preview**. The peak must become 5 mm, not 15 mm.
6. In those same active-region controls switch to **Expansion**, press **Update
   Preview**, and confirm the same area moves outward from the original surface.
7. Press **Edit Selection**. Add/remove orange faces using the selection tools, then
   press **Update Preview**. The changed region must stay attached to the torso and
   follow its curved surface.
8. Press **Commit** only after the preview is correct. Pressing Commit again must report
   that the region is already committed instead of applying the depth twice.

## Pass checks

- Pressure moves inward; Expansion moves outward.
- The edge fades smoothly to zero; there is no floating curve or detached pad object.
- Amount changes replace the preview and do not accumulate.
- Edit Selection restores editable mesh faces and Update Preview uses the new border.
- Undo after Commit restores the pre-commit mesh.

## Known limits

- Automated Blender tests proved 10.000 mm preview, 7.000 mm update/commit, zero movement
  outside the mask, unchanged topology and no new non-manifold edges.
- Extreme depth on thin or sharply concave anatomy can still self-intersect; this slice
  does not yet include collision/thickness rejection. Inspect from several views.
- **Ready Circular Region** is only a quick geodesic circle. Saving and regenerating an
  arbitrary painted selection as a reusable library template is the next implementation
  slice.
- Clinical location, amount and pressure/expansion coupling require orthotist approval.

Optional regression check for the reported crash: press `F3`, run **Draw New Boundary**,
click at least three scan points and press Enter. A legacy curve should be created without
a traceback. This operator is intentionally no longer shown in the main panel.
