# Three-Ring Segment Deformation Research

Date: 2026-07-12

## Verified behavior

The project-provided `Leospinal tutorial.md` is explicit:

- Bend positions an axis and bending planes and can affect the bottom portion or the
  whole model.
- Twist positions a twisting zone with multiple bounding curves.
- Stretch supports two or three control loops. With three loops, deformation is limited
  to the zone between two blue curves; the loops can be repositioned and the bottom
  section can be selected.

Therefore the previous two-ring implementation was incomplete. The requested independent
segment control is consistent with the documented LeoSpinal workflow.

## Rodin4D comparison

Rodin4D's public Neo material confirms professional rectification tools, libraries of
pre-rectified forms, creation of custom libraries, change history, and import/export.
Public documents do not expose the exact algorithm or prove that Neo uses the identical
three-ring interaction. We can match the requested and LeoSpinal-documented behavior,
but must not claim exact Rodin4D implementation parity.

Sources:

- Local reference: [`Leospinal tutorial.md`](../../Leospinal%20tutorial.md)
- [Rodin4D global CAD/CAM solution brochure](https://www.rodin4d.com/app/uploads/2023/08/Rodin-DOC-EN.pdf)
- [Rodin4D Neo official product overview](https://www.rodin4d.com/es/logiciel-cfao/)
- [LeoSpinal release notes: JSON template saving](https://leopoly.com/leoshape/2026/05/20/leospinal-release-notes-20-05-26/)

## Independent implementation decision

Create three filled, draggable rings: Lower, Middle and Upper. Select one active interval:

- Lower to Middle
- Middle to Upper
- Lower to Upper (full model compatibility)

The active pair drives one Blender Simple Deform modifier. For Twist and Stretch, a live
height mask fades to zero at both rings, so geometry below and above the interval remains
fixed in world position. Bend retains Blender's rigid continuation outside the interval
because the orthotist confirmed that behavior is correct.

## Acceptance gates

- All three rings are visible, filled click targets and move only vertically.
- Dragging the middle ring changes the active modifier limit live.
- For Middle-Upper, lower-segment absolute movement is below 0.01 mm.
- For localized Twist/Stretch, absolute movement outside both rings is below 0.01 mm.
- Stretch is entered in millimetres; evaluated peak error is below 0.05 mm.
- For Bend, the outside continuation preserves pairwise distances below 0.01 mm error.
- Gates pass independently for Bend, Twist and Stretch.
- Switching intervals does not accumulate modifiers or drivers.
- Apply removes rings/drivers and bakes once; Reset removes them without mesh change.
