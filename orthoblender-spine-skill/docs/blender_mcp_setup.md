# Blender MCP — live see→measure→fix loop (setup)

Goal: let the agent drive a **running** Blender session — run Python, read the scene,
take viewport screenshots, measure mesh quality — so geometry is verified by *seeing and
measuring*, not by reading a text result file. This is the fix for "blind" 3D work
(DEC-0014). Project: `ahujasid/blender-mcp` (MIT).

## STATUS — installed & verified by the agent 2026-07-03
The whole chain is in place and was proven end-to-end (get_scene_info + execute_code both
returned `success` against a live rigo_brace session on Blender 5.0.1):
- ✅ `uv`/`uvx` present (0.11.25).
- ✅ MCP server registered with Claude Code: `blender: uvx blender-mcp` (local scope,
  shows **Connected** in `claude mcp list`).
- ✅ Add-on installed at
  `%APPDATA%\Blender Foundation\Blender\5.0\scripts\addons\blender_mcp_addon.py`,
  **enabled + saved to userpref** (auto-start on, port 9876). `requests` 2.32.3 is bundled
  in Blender 5.0's Python, so it imports cleanly.
- ✅ Launcher `tools/mcp_bridge.py` boots Blender with the rigo_brace template AND starts
  the bridge socket on 9876.

### The ONE remaining action (you)
**Restart Claude Code** once. MCP tools load at session start, so the `blender.*` tools
(get_scene_info, execute_code, get_viewport_screenshot, …) only enter the agent's toolset
in a *new* session. After restarting, just say "check the Blender MCP connection."

### To run the live loop (each work session)
1. Start the bridged Blender (leave the window open):
   ```powershell
   & "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" `
       --app-template rigo_brace --python "tools\mcp_bridge.py"
   ```
   (Because the add-on auto-starts, a plain `--app-template rigo_brace` launch also works;
   `mcp_bridge.py` just makes it deterministic and forces port 9876.)
2. In Claude Code (new session), ask me to check the connection. I'll pull the scene and
   screenshot the viewport.

### Manual fallback (if you ever need it)
In Blender: press **N** → **BlenderMCP** sidebar tab → **Connect to MCP server**. Re-register
the server if it's ever missing: `claude mcp add blender -- uvx blender-mcp`.

## If it errors on Blender 5.0
The add-on targets older Blender in places. If enabling it or connecting throws, paste me
the error — I'll patch a local copy of `addon.py` (5.0 API: context overrides, `hide_get`,
socket handler) and we keep our own copy with a provenance entry.

## How the agent will use it (discipline — DEC-0014, memory: 3d-rigor)
Per geometry change, the loop becomes:
1. **Run** the operator/script in the live session.
2. **See** — viewport screenshot from the relevant view (front/side/top).
3. **Measure** — vertex/face count, bounding box (mm), non-manifold/boundary/loose,
   self-intersections, op timing.
4. **Judge against numeric gates** (not "looks right") — see the quantitative test gates.
5. **Fix and re-run** until gates pass; only then report done.

MCP is for the **live dev loop**; the committed `tools/*test.py` result-file tests remain
the reproducible record. The two are complementary, not a replacement.

### Capture reliability (learned 2026-07-03, issue #12)
- **Always sanity-check a capture's brightness** before trusting it (load the PNG into
  `bpy.data.images`, sample mean RGB; < 0.02 ≈ black frame). A black frame means the
  *visual* channel failed — object data via `execute_code` is still trustworthy.
- If a capture comes back black: run `bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP",
  iterations=1)` and retry once; if still black, restart the bridged Blender session.
- The one observed black-capture episode followed an operator **crashing mid-execute**
  (the pre-fix Remold AttributeError). An exception inside an operator can leave the UI
  in a bad state — fix crashes first, don't chase the capture.

## Security / clinical note
BlenderMCP executes arbitrary Python in your Blender session — it is a dev tool, run it
only for this project. Patient scans/X-rays stay local; nothing is uploaded.
