# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Rigo Brace Designer — a Blender 5.x add-on plus application template for orthotists to design Rigo-Chéneau spinal braces, modeled on the LeoSpinal workflow (see "Leospinal tutorial.md"). Pure Python against the `bpy` API; there is no build system beyond zipping, and no git repo.

Blender path (hardcoded in install.ps1): `C:\Program Files\Blender Foundation\Blender 5.0\blender.exe`

## Commands

- Build distributable zip: `python build.py` → `rigo_brace.zip`
- Install/update the local dev install: `./install.ps1` (PowerShell, project root). Copies `rigo_brace/` into `%APPDATA%\Blender Foundation\Blender\5.0\extensions\user_default\rigo_brace`, installs the app template, bakes `startup.blend` via `tools/build_startup_gui.py`, and creates a desktop shortcut.
- Run a test (GUI Blender required — the extension system `bl_pkg` does not exist under `--background`):

  ```powershell
  & "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --app-template rigo_brace --python tools\selftest.py
  ```

  Each test script registers a `bpy.app.timers` callback that retries until the UI is registered, runs its checks, writes `<name>_result.txt` to the project root (errors are captured there with a traceback), and quits Blender itself. Read the result file afterwards; nothing useful is printed to stdout.

  - `tools/selftest.py` → `selftest_result.txt` — registration smoke test (`ALL_PASS=True/False`)
  - `tools/selecttest.py` → `selecttest_result.txt` — functional paint-select pipeline test against `Brace Sample.stl` (`PASS=True/False`)
  - Same pattern: `keymaptest.py`, `scancleantest.py`, `padtest.py`, `designtest.py`, `outlinetest.py`

**Critical gotcha:** tests run the *installed* copy of the add-on (loaded via `--app-template rigo_brace`), not the repo copy. After editing anything under `rigo_brace/` or the template, re-run `./install.ps1` first, otherwise the test exercises stale code.

## Architecture

Two installable pieces:

- `rigo_brace/` — the extension (`blender_manifest.toml`). Its `__init__.py` fans out `register()` strictly in order `core → operators → ui → keymaps` (keymaps reference operator bl_idnames, so they must come last).
- `rigo_brace_template/` — Blender application template that gives the orthotist a stripped, single-viewport UI. Its `register()` runs before Blender's extension system is ready, so *all* setup (enabling the add-on, deleting extra workspaces, theming) is deferred onto retrying `bpy.app.timers` callbacks — never do workspace/area surgery synchronously (it corrupts the screen; see comments in the file). The screen layout and the METRIC/MILLIMETERS unit settings live in the pre-baked `startup.blend`, built once in a real GUI session by `tools/build_startup_gui.py` (headless baking cannot configure the screen).

Inside the add-on:

- `core/__init__.py` — single source of truth: the `RigoBraceSettings` PropertyGroup mounted at `Scene.rigo_brace` (every tunable shown in the UI, all mm-denominated), plus constants: anatomical `LANDMARKS`, `WORKFLOW_TABS` (the five wizard stages), and well-known object/collection names (`CORSET_NAME`, `OUTLINE_CURVE_NAME`, …) used to find objects across operators.
- `core/pad_library.py` — the persistent pressure/relief shape library: builtin clinical entries + orthotist-recorded outlines with favourite depth/size/kind, stored as one json in the user's Blender config dir (`…/config/rigo_brace/pad_library.json`, global per PC). Dynamic enum items for `pad_type` come from a module-cached list (string-lifetime gotcha); no file IO happens at `register()`.
- `operators/` — one module per pipeline area (io, scan, mesh, landmark, remold, deform, pad, correction, design, select, ui). All operators use the `rigo.` idname prefix; `selftest.py` asserts each one's presence by name.
- `ui/panels.py` — one main panel `RIGO_PT_main` (N-panel, "Rigo Brace" category) drawing a five-stage wizard: a step bar plus per-stage draw functions dispatched through `_STAGE_DRAW`. The same step bar is appended to the viewport tool header (`VIEW3D_HT_tool_header` — renamed in Blender 5.0, see `_tool_header_type()` for the compat lookup). `_draw_select_box` is shared by the Scan, Mesh and Design stages.
- `keymaps.py` — Alt+<key> shortcuts for the paint-select tools.

Conventions:

- Units: 1 Blender unit = 1 m. All UI values are millimetres; operators convert with `* 0.001`.
- The painted-region system (`operators/select_ops.py`) is Edit-Mode native: the live face selection IS the region — no sculpt mask or vertex group. "Paint Area" switches to Edit Mode + face select, turns X-ray **off** (so the circle-select brush only hits visible front faces, not the hollow back of the scan), and activates `builtin.select_circle`. Region operators have both an `invoke()` path (interactive modal transform for the GUI) and an `execute()` path with a BMesh fallback (used by tests, which can't mouse-drag).
- Mutating operators must carry `bl_options = {"REGISTER", "UNDO"}`; the add-on's promise to users is that every shaping step is undoable.
