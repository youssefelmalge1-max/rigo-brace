# Rigo Brace Designer

**An open-source Blender add-on that turns a 3D torso scan into a manufacturable
Rigo-Chéneau scoliosis brace.**

Scoliosis bracing is a small, highly specialised corner of orthotics. The CAD tools that
serve it are proprietary, expensive, and locked to specific scanners and milling
hardware — which puts computer-aided brace design out of reach for independent
orthotists, clinics in low-resource settings, and the schools that train them. This
project is an attempt to build that pipeline in the open, on top of Blender.

> **Clinical boundary — read this first.** This software *guides* design; it does not
> prescribe treatment. Nothing it produces is a clinical recommendation. Every generated
> brace and correction must be reviewed and approved by a qualified orthotist before
> fabrication or fitting. See
> [clinical_safety_protocol.md](orthoblender-spine-skill/knowledge/clinical_safety_protocol.md).

## What it does

The add-on replaces Blender's general-purpose interface with a five-stage guided
workflow built around how an orthotist actually works:

| Stage | What happens |
| --- | --- |
| **File** | Import the patient torso scan (`.stl` / `.obj`). |
| **Scan** | Scale, align and clean the raw scan — remove noise, holes and scanner artefacts. |
| **Landmarks** | Place anatomical reference points (C7, scapulae, axillae, curve apices, iliac crest, ASIS/PSIS, trochanters, waistline). These drive everything downstream. |
| **Mesh Edit** | Derotate, correct and remold the torso — lattice deformation, region-based sculpting, and the pressure/expansion correction system. |
| **Design** | Generate the brace body: trimline generation and smoothing, pads and reliefs, ventilation, rivets, wall thickness, QA checks, and export. |

Supporting systems:

- **Painted correction regions** — an Edit-Mode-native paint-select system where the live
  face selection *is* the region, so corrections stay tied to real surface areas.
- **Pressure / expansion couples** — corrections are modelled as coupled 3D corrective
  systems (force and counterforce), not isolated dents, following Rigo-Chéneau principles.
- **Persistent pad library** — clinical pad and relief shapes, plus orthotist-recorded
  outlines with favourite depth/size/kind, stored per workstation.
- **Design history** — every shaping step is undoable, and designs are versioned per patient.
- **QA gate** — manifold/watertight checks, wall-thickness verification, and unit
  validation before export.

## Status

Working and in active development. The pipeline runs end to end, and it is used against
real scan data locally — but it has **not** been through clinical validation or
regulatory assessment, and should be treated as research/design software.

Roughly: 19,000 lines of Python across 36 modules, 119 registered operators, and 165
scripted GUI test and diagnostic harnesses under [tools/](tools/).

## Install

**Requirements:** Blender 5.x (manifest declares 4.2+ minimum).

1. Build the extension zip:
   ```
   python build.py          # → rigo_brace.zip
   ```
2. In Blender: **Edit → Preferences → Get Extensions → ▼ → Install from Disk…** and pick
   the zip.
3. Enable it, press **N** in the 3D Viewport, and open the **Rigo Brace** tab.

For the full orthotist-facing experience — a stripped, single-viewport UI with the
workflow as top-level tabs — install the application template as well. On Windows,
`./install.ps1` does all of it (extension + template + baked startup layout).

## Testing

Tests must run in a **GUI** Blender session — Blender's extension system (`bl_pkg`) does
not exist under `--background`:

```
& "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --app-template rigo_brace --python tools\selftest.py
```

Each harness registers a `bpy.app.timers` callback, runs its checks, writes
`<name>_result.txt` to the project root, and quits Blender itself. Read the result file
afterwards — nothing useful goes to stdout.

> **Gotcha:** tests exercise the *installed* copy of the add-on, not the repo copy. Re-run
> `./install.ps1` after editing anything under `rigo_brace/`.

## Architecture

```
rigo_brace/                  the Blender extension
  core/                      RigoBraceSettings (all tunables, mm-denominated),
                             anatomical landmarks, pad/region/trim libraries
  operators/                 one module per pipeline area — all use the `rigo.` prefix
  ui/panels.py               the five-stage wizard panel + tool-header step bar
  keymaps.py                 Alt+<key> shortcuts for the paint-select tools
rigo_brace_template/         application template — the stripped orthotist UI
tools/                       GUI test + diagnostic harnesses
orthoblender-spine-skill/    project knowledge base and operating discipline
.ai/expert-council/          advisory review system (see below)
```

Conventions: 1 Blender unit = 1 m; **all UI values are millimetres** and operators
convert at the boundary. Mutating operators carry `bl_options = {"REGISTER", "UNDO"}` —
every shaping step is undoable.

## Engineering process

Because this is clinical-adjacent geometry code where a silent numerical failure has
real consequences, the repository carries its own review infrastructure:

- **[Expert council](.ai/expert-council/)** — 15 domain lenses (mesh processing, geometry
  robustness, Blender internals, numerical analysis, scoliosis biomechanics, clinical
  brace design) plus an orchestrator that routes a problem to the smallest sufficient set
  and runs adversarial cross-review before a patch is written. The clinical lenses hold
  veto authority over changes that would destroy clinical meaning.
- **[orthoblender-spine-skill/](orthoblender-spine-skill/)** — a persistent knowledge base
  (decision log, error log, learned memory, code provenance) updated after each task.

Each expert lens is explicitly a **literature-derived lens, not a person** — it does not
simulate, speak for, or represent the researcher it is named after.

## Contributing

Issues and pull requests are welcome, particularly from orthotists and CPOs — clinical
feedback is more valuable here than code. Two hard rules:

1. **Never commit patient data.** Scans, `.blend` working files, and X-rays are
   patient-identifiable. `.gitignore` blocks `*.stl` and `*.blend`; keep it that way.
2. **Preserve clinical semantics.** A geometric offset is not physical pressure. Label it
   `depth_mm` unless a validated mechanical model says otherwise.

## License

[GPL-3.0-or-later](LICENSE). Blender add-ons that use the `bpy` API are derivative works
of Blender and must be GPL-compatible.

## References

Rigo M, Villagrasa M, Gallo D. *A specific scoliosis classification correlating with
brace treatment: description and reliability.* Scoliosis. 2010;5:1.
[doi:10.1186/1748-7161-5-1](https://doi.org/10.1186/1748-7161-5-1) — open access (CC BY).
</content>
