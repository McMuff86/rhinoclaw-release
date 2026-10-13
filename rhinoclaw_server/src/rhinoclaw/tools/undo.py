import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def undo(ctx: Context, force: bool = False) -> str:
    """Roll back the previous RhinoClaw tool call in the active Rhino document.

    Each mutating tool call (create_object, modify_object, boolean_operation,
    execute_*_code, ...) is wrapped in one Rhino undo record by the plugin, so
    one `undo()` rolls the whole previous tool call back as one atomic step.
    `undo` and `redo` themselves are not recorded (like Rhino's own Ctrl+Z).

    Ownership rule: the plugin only undoes when its own last record is on top
    of the undo stack. If the user did something in Rhino after the last tool
    call (gumball move, selection edit, a native command), `undo()` refuses
    with `outcome: foreign_record_on_top` instead of silently reverting the
    user's work; `no_owned_record` means RhinoClaw has not recorded anything in
    this document yet. Pass `force=True` to undo the top entry regardless.

    The plugin runs Rhino's native `_Undo` command. `data.undo_after` shows the
    document's undo state afterwards; `outcome: undo_state_dirty` means Rhino
    left a record or undo flag open and the next mutation would fail.

    Returns:
        {
          "success": true | false,
          "data": {
            "did_undo": true | false,
            "outcome": "undone" | "no_change" | "foreign_record_on_top" |
                       "no_owned_record" | "undo_state_dirty" | "<unavailable reason>",
            "undo_before": {...}, "undo_after": {...},
            "message": "..."
          }
        }
    """
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("undo", {"force": bool(force)})
        if result.get("success") is False:
            response = from_exception(RuntimeError(result.get("message", "Undo unavailable")),
                                      code=ErrorCode.RHINO_ERROR)
            response["data"] = result
            return json.dumps(response)
        did_undo = bool(result.get("did_undo", False))
        return json.dumps(ok(
            message=result.get(
                "message",
                "Rolled back the previous tool call." if did_undo else "Nothing to undo.",
            ),
            data=result,
        ))
    except Exception as e:
        logger.error(f"Undo failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
