import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def list_capabilities(ctx: Context) -> str:
    """Return a categorised inventory of everything this plugin can do.

    Call this once at session start so the agent knows the menu without
    guessing from documentation. The response carries:

    - `plugin_version`, `rhino_version`
    - `categories` — typed MCP commands grouped by domain
      (geometry / transforms / booleans_and_solids / curves /
      dimensions_and_text / layers_and_materials / files_and_io /
      viewport_and_render / groups_and_blocks / scene_analysis /
      batch / undo_redo / grasshopper / scripting / streaming /
      debug_and_diagnostics / meta).
    - `native_command_allowlist` — Rhino native commands that
      `run_native_command` will accept. Useful when no typed tool fits
      and `rhinoscriptsyntax` doesn't expose a clean wrapper.
    - `scripting_paths` — pointers and helpers for falling back to
      `rhinoscriptsyntax` (Option A) and RhinoCommon (Option B), with
      links to the dev-repo `docs/rhinocommon-cookbook.md`.
    - `preferences` — the preference order to follow when picking a
      tool. Read this BEFORE reaching for `execute_python3_code`.

    Cheap call: pure metadata, no document mutation.
    """
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("list_capabilities", {})
        category_count = len(result.get("categories", {}))
        return json.dumps(ok(
            message=f"Plugin {result.get('plugin_version', 'unknown')}: "
                    f"{category_count} command categories available.",
            data=result,
        ))
    except Exception as e:
        logger.error(f"list_capabilities failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
