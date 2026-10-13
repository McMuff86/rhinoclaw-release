"""Save/capture the exact live Grasshopper document without scripting."""

import json
from typing import Literal

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


def _artifact_call(command, parameters):
    try:
        result = get_rhino_connection().send_command(command, parameters)
        if result.get("success") is False or (result.get("verification") or {}).get("pass") is not True:
            response = from_exception(RuntimeError(result.get("message", "Artifact verification failed")),
                                      code=result.get("error_code", ErrorCode.VERIFICATION_FAILED))
            response["data"] = result
            return json.dumps(response)
        return json.dumps(ok(result.get("message", "Verified Grasshopper artifact"), data=result))
    except Exception as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def save_grasshopper_definition(
    ctx: Context, definition_id: str, file_path: str, mode: Literal["copy", "save_as"] = "copy",
) -> str:
    """Save exact live edits to a NEW .gh/.ghx path with archive readback.

    copy preserves the shown graph's path and modified flag; save_as changes
    its path and marks it saved only after verification. Existing paths are
    rejected. Verifies top-level node/port/wire IDs and full Slider/Panel/Toggle
    values in a separately deserialized graph. Does not solve or bake; then
    load the saved copy, solve and use get_grasshopper_outputs to prove geometry.
    Reports external_file_written/written_file_path even on partial failure.
    Files and GH state are outside Rhino Undo. Never blindly repeat a failed save.
    """
    if not definition_id or not definition_id.strip() or not file_path or not file_path.strip() \
            or not file_path.lower().endswith((".gh", ".ghx")) or mode not in ("copy", "save_as"):
        return json.dumps(from_exception(ValueError("definition_id, a fresh .gh/.ghx path and mode copy/save_as are required"),
                                         code=ErrorCode.INVALID_PARAMS))
    return _artifact_call("save_grasshopper_definition", {"definition_id": definition_id, "file_path": file_path, "mode": mode})


@mcp.tool()
def capture_grasshopper_canvas(ctx: Context, definition_id: str, file_path: str) -> str:
    """Capture the currently shown exact definition to a NEW readable PNG.

    Show the definition first. A different active graph fails without switching.
    Uses native canvas drawing, preserves selection and verifies PNG dimensions.
    A canvas image proves presentation, not geometry or a successful solve.
    """
    if not definition_id or not definition_id.strip() or not file_path or not file_path.lower().endswith(".png"):
        return json.dumps(from_exception(ValueError("definition_id and a fresh .png file_path are required"),
                                         code=ErrorCode.INVALID_PARAMS))
    return _artifact_call("capture_grasshopper_canvas", {"definition_id": definition_id, "file_path": file_path})
