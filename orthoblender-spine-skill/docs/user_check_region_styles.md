# User Check — Save and Import a Committed Correction Style

Readiness: **PARTIAL / INFRASTRUCTURE ONLY**. Installed-copy save/reload/import geometry
passes; the orthotist's fresh-session UI check is still required.

## Restart and fixture

Close every Blender window, restart **Rigo Brace**, and first use `Brace Sample.stl` as
millimetres. Confirm it is oriented correctly before testing on a patient scan.

## Save a committed style

1. Open **4 Mesh Edit**.
2. Paint faces and create a live Pressure or Expansion region.
3. Edit and Update Preview until satisfied, then press **Commit**.
4. Press **Save Committed Style…**, enter a descriptive non-clinical name, and confirm.
5. The style appears under **Reusable Correction Styles**. It is stored globally on this
   PC, outside the patient `.blend` file.

Saving before Commit must be rejected.

## Import the style

1. Open another prepared scan.
2. Place the 3D cursor on the intended body surface with `Shift + Right-click`.
3. Select the style under **Reusable Correction Styles**.
4. Press **Import at Cursor**.
5. Review the live preview. Use **Edit Selection** and **Update Preview** as needed.
6. Commit only after checking location, sign, depth and transition from multiple views.

## Pass checks

- The imported region has the saved Pressure/Expansion kind and peak amount.
- It follows the new scan surface and is editable; it is not a floating curve.
- The clean target mesh is unchanged until Commit.
- Delete removes the library entry, not an already committed mesh correction.

## Automated evidence and limits

`regionstyletest.py` saved a committed 8.000 mm pressure, forced a JSON disk reload,
decimated the target scan to a different topology, imported an editable 8.000 mm preview,
then committed exactly 8.000 mm. All gates passed.

Templates preserve millimetre size and surface-up orientation. Interactive scaling and
rotation after import are not implemented. Orthotist review is mandatory.
