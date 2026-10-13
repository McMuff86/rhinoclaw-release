"""Read a retained operation receipt without executing the operation again."""
import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, mcp
from rhinoclaw.utils.responses import error, from_exception, ok
from rhinoclaw.utils.errors import ErrorCode


@mcp.tool()
def get_operation_result(ctx: Context, operation_id: str, session_id: str) -> str:
    """Look up a timed-out operation in its original plugin session without re-executing it.

    Use the operation_id and session_id returned with a TIMEOUT/OUTCOME_UNKNOWN
    error. States are pending, completed (includes the original response), or
    unknown (receipt evicted/lost, not proof that nothing happened). Completed
    receipts describe the original execution, not the current document state.
    Requires plugin 0.8.1+. Inspect UI and document state before further mutations.
    """
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128 or not isinstance(session_id, str) or not session_id:
        return json.dumps(error("Provide the original operation_id and session_id.", code=ErrorCode.INVALID_PARAMS))
    try:
        result = get_rhino_connection().send_command("get_operation_result", {
            "operation_id": operation_id, "session_id": session_id,
        })
        if result.get("state") == "unknown":
            return json.dumps(error("Receipt unavailable; inspect the document. Do not automatically repeat the operation.",
                                    code=ErrorCode.OUTCOME_UNKNOWN, data=result))
        if result.get("state") not in {"pending", "completed"}:
            return json.dumps(error("Plugin returned an invalid operation receipt.",
                                    code=ErrorCode.VERIFICATION_FAILED, data=result))
        return json.dumps(ok(message="Operation receipt: " + result.get("state", "unknown"), data=result))
    except Exception as exc:
        return json.dumps(from_exception(exc))
