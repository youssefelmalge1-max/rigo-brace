# User Check — Three-Ring Bend, Twist and Stretch

Status: **TECHNICALLY COMPLETE — USER VALIDATED 2026-07-12**. Installed-copy numeric and
visual tests pass, and the orthotist confirmed Bend, Twist, and Stretch work. Icons,
names, and ring appearance may be polished later without changing the geometry contract.

## Restart and fixture

Close every Blender window, restart **Rigo Brace**, and import `Brace Sample.stl` as
millimetres. Use an upright, correctly oriented scan for clinical work.

## Exact check

1. Open **4 Mesh Edit**.
2. Press **Start Bend**, **Start Twist**, or **Start Stretch**.
3. Three filled rings appear: blue Lower, white Middle, blue Upper.
4. Select a ring in the viewport, press `G`, then `Z`, drag vertically, and click.
5. Choose **Lower ↔ Middle** or **Middle ↔ Upper** under **Three Segment Rings**.
6. Adjust Bend/Twist in degrees. Stretch uses **Stretch (mm)**; enter `40` for the
   measured 40 mm test. Ring movement and amount remain live.
7. Test the other interval. Use **Full: Lower ↔ Upper** only when the whole torso should
   be modified.
8. Press **Apply** to bake once or **Reset** to discard the live deformation.

## Pass checks

- Dragging any ring changes only the bounded interval.
- With Middle-Upper active, the lower body remains fixed.
- For localized Twist and Stretch, geometry below and above the two active rings remains
  fixed in position.
- Entering `40 mm` Stretch produces a measured 40 mm peak inside either active interval.
- Bend keeps its established rigid continuation outside the active zone because that
  behavior was manually approved.
- Switching interval does not add a second modifier or compound the amount.
- Reset restores the untouched base; Apply removes all three rings.

## Automated evidence and limits

`segmentdeformtest.py` passes Bend, Twist and Stretch for all three interval choices.
Localized Twist/Stretch outside movement is 0.0000 mm; requested/measured Stretch is
40.00/40.00 mm; Bend rigid-shape error is 0.0000 mm. The established
`planestest.py`, `bendtest.py` and `stretchtest.py` regressions also pass.

This matches the three-loop behavior described in the local LeoSpinal tutorial. Public
Rodin4D documentation does not reveal enough detail to claim an identical internal
algorithm.
