"""Start the BlenderMCP bridge inside a live GUI Blender session.

Run (GUI required — the app-template extension system needs it):

    & "C:\\Program Files\\Blender Foundation\\Blender 5.0\\blender.exe" \
        --app-template rigo_brace --python tools\\mcp_bridge.py

This enables the `blender_mcp_addon` (installed in Blender's scripts/addons) and starts
its socket server on port 9876, which the registered `uvx blender-mcp` MCP server connects
to — giving Claude the live see->measure->fix loop over our rigo_brace session. Leave this
Blender window open while working. Dev tool only; not part of the shipped product.
"""

import bpy

_PORT = 9876


def _start():
    try:
        if "blender_mcp_addon" not in bpy.context.preferences.addons:
            bpy.ops.preferences.addon_enable(module="blender_mcp_addon")
        scene = bpy.context.scene
        scene.blendermcp_port = _PORT
        srv = getattr(bpy.types, "blendermcp_server", None)
        if not srv or not getattr(srv, "running", False):
            bpy.ops.blendermcp.start_server()
        print(f"BLENDERMCP_BRIDGE_STARTED port={_PORT}")
    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"BLENDERMCP_BRIDGE_ERR {exc!r}")
        traceback.print_exc()
    return None  # one-shot


bpy.app.timers.register(_start, first_interval=1.0)
