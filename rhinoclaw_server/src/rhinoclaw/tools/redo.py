import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def redo(ctx: Context) -> str:
    """Re-apply the most recently undone action in the active Rhino document.

    Mirror of `undo()`. Will only succeed if `undo()` was called previously
    and no new mutating tool call has happened since (any new edit clears
    the redo stack — same semantics as Rhino's native Ctrl+Y).

    Returns:
        {
          "success": true,
          "data": {
            "did_redo": true | false,
            "message": "..."
          }
        }
    """
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("redo", {})
        did_redo = bool(result.get("did_redo", False))
        return json.dumps(ok(
            message=result.get(
                "message",
                "Re-applied the previously undone action." if did_redo else "Nothing to redo.",
            ),
            data=result,
        ))
    except Exception as e:
        logger.error(f"Redo failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
