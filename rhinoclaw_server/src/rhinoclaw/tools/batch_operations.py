import json
from typing import Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

ErrorPolicy = Literal["rollback", "abort", "continue", "best_effort"]


@mcp.tool()
def batch_operations(
    ctx: Context,
    steps: List[Dict[str, Any]],
    on_error: ErrorPolicy = "rollback",
    name: Optional[str] = None,
) -> str:
    """Run a multi-step pipeline of MCP tool calls in a single TCP round-trip.

    Each step has shape `{"tool": "<tool_name>", "args": {...}}`. The plugin
    executes them sequentially inside one Rhino undo record (so the whole
    batch is one Ctrl+Z step for the user) and applies the chosen
    `on_error` policy.

    Parameters:
    - steps: ordered list of `{"tool": str, "args": dict}` entries.
    - on_error: failure policy (default "rollback").
        * "rollback"     — on first failure, undo every successful step
                           and surface the failure. Atomic-feeling.
        * "abort"        — on first failure, stop. Completed steps stay
                           applied (they're still inside the outer undo
                           record, so the user can Ctrl+Z everything).
        * "continue"     — log the failure, skip the failed step, keep
                           going. Useful for "best-effort apply N
                           materials".
        * "best_effort"  — same as continue, plus the response success
                           flag stays true even with step failures.
    - name: human-readable label for the batch, surfaced as the undo-
            record name. Defaults to "batch (N steps)".

    Returns:
        JSON dict with keys:
        - success: bool (false if any step failed and policy != best_effort)
        - policy: the normalised on_error string
        - counts: {total, completed, failed, skipped}
        - rolled_back: bool — whether the rollback actually fired
        - results: list of per-step entries
            {step: int, tool: str, success: bool, result: {...}, error: "..."}
        - failed_step / failed_tool / error: present only on failure
        - message: one-line human summary
        - batch_label: the resolved `name`

    Example:
        batch_operations(steps=[
            {"tool": "create_layer", "args": {"name": "MyLayer", "color": [255,0,0]}},
            {"tool": "create_object", "args": {"type": "BOX",
                "params": {"width": 5, "length": 5, "height": 5}, "layer": "MyLayer"}},
            {"tool": "create_material", "args": {"name": "RedMatte"}},
        ])
    """
    try:
        if not isinstance(steps, list) or len(steps) == 0:
            return json.dumps(from_exception(
                ValueError("'steps' must be a non-empty list of {tool, args} objects"),
                code=ErrorCode.INVALID_PARAMS,
            ))

        for i, step in enumerate(steps):
            if not isinstance(step, dict) or "tool" not in step:
                return json.dumps(from_exception(
                    ValueError(f"Step {i} is missing 'tool' field"),
                    code=ErrorCode.INVALID_PARAMS,
                ))

        params: Dict[str, Any] = {"steps": steps, "on_error": on_error}
        if name:
            params["name"] = name

        rhino = get_rhino_connection()
        result = rhino.send_command("batch_operations", params)

        # Plugin reports its own success flag on `result.success`. We surface
        # it to the agent as the outer ok() success — when policy is rollback
        # and a step failed, the whole batch_operations response has
        # success=false and the agent sees a structured error.
        if result.get("success", False):
            return json.dumps(ok(
                message=result.get("message", "Batch completed."),
                data=result,
            ))
        else:
            # Use the plugin's message + a structured payload so callers can
            # introspect failed_step / failed_tool / per-step results.
            response = {
                "success": False,
                "code": "BATCH_FAILED",
                "message": result.get("message", "Batch failed."),
                "data": result,
            }
            return json.dumps(response)

    except Exception as e:
        logger.error(f"batch_operations failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
