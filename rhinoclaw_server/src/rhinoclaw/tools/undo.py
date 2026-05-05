import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def undo(ctx: Context) -> str:
    """Roll back the most recent undoable action in the active Rhino document.

    Each MCP tool call (create_object, modify_object, boolean_operation, …)
    is wrapped in a single Rhino undo record by the plugin, so one
    `undo()` rolls the entire previous tool call back as one atomic step.
    Calls to `undo` and `redo` themselves are *not* recorded (mirroring
    Rhino's native Ctrl+Z behaviour), so a follow-up `undo()` rolls back
    the next-older tool call rather than re-doing the undo.

    Returns:
        {
          "success": true,
          "data": {
            "did_undo": true | false,   # false if the stack was already empty
            "message": "..."
          }
        }
    """
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("undo", {})
        did_undo = bool(result.get("did_undo", False))
        return json.dumps(ok(
            message=result.get(
                "message",
                "Rolled back the previous action." if did_undo else "Nothing to undo.",
            ),
            data=result,
        ))
    except Exception as e:
        logger.error(f"Undo failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
