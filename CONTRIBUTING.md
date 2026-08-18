# Contributing

Contributions are welcome — particularly from orthotists and CPOs. Clinical feedback on
whether a generated brace is *right* is worth more to this project than code.

## Before anything else: never commit patient data

Torso scans, `.blend` working files, and X-rays are patient-identifiable. `.gitignore`
blocks `*.stl` and `*.blend`; do not override it, and do not attach a real patient scan
to an issue. If you need to demonstrate a bug, describe the mesh (vertex count, units,
scanner) or reproduce it on a synthetic body.

Third-party reference geometry from commercial brace CAD systems is likewise never
committed, even for comparison.

## Reporting a bug

Open an issue using the **Bug report** template. Geometry bugs are hard to diagnose from
prose, so the useful details are:

- which of the five stages (File / Scan / Landmarks / Mesh Edit / Design) it happened in
- the operator name if you know it (they all start with `rigo.`)
- your Blender version and OS
- a screenshot of the viewport — for geometry defects this is usually the single most
  informative thing you can attach

Clinicians: if the software produced something that is geometrically fine but clinically
wrong, use the **Clinical feedback** template instead. That is a different and more
valuable class of report.

## Working on the code

Read [CLAUDE.md](CLAUDE.md) first — it documents the architecture and the conventions
that are easy to get wrong.

Three that bite people:

1. **Units.** 1 Blender unit = 1 m. Every UI value is millimetres and operators convert
   at the boundary with `* 0.001`. Mixing these produces braces that are wrong by 1000×.
2. **Tests run the *installed* add-on**, not your working copy. Run `./install.ps1`
   after editing anything under `rigo_brace/`, or you will test stale code.
3. **Mutating operators need `bl_options = {"REGISTER", "UNDO"}`.** Every shaping step
   must be undoable; that is a promise the add-on makes to its users.

### Testing

Tests need a **GUI** Blender session — the extension system (`bl_pkg`) does not exist
under `--background`:

```
& "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --app-template rigo_brace --python tools\selftest.py
```

Each harness writes `<name>_result.txt` to the project root and quits Blender itself.
Read the result file; stdout is not useful. Add or extend a harness in [tools/](tools/)
for any behaviour change.

## Clinical changes

If a pull request changes what a correction *means* clinically — pressure/expansion
pairing, laterality, sagittal constraints, trimline coverage — say so explicitly in the
description. Geometry that looks smooth in the viewport is not fabrication approval, and
a geometric offset is not physical pressure. Label it `depth_mm` unless a validated
mechanical model says otherwise.

## License

By contributing you agree your work is licensed under [GPL-3.0-or-later](LICENSE).
