import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def run_native_command(
    ctx: Context,
    command: str,
    args: Optional[List[str]] = None,
    echo: bool = False,
) -> str:
    """Run an allowlisted Rhino native command non-interactively.

    Last-resort hatch for commands that have no clean RhinoCommon SDK
    path (e.g. `_Sweep1` with several rails, `_NetworkSrf`,
    `_BooleanSplit`). The plugin restricts which commands can be fired
    — call `list_capabilities` to see the current allowlist.

    Parameters:
    - command: underscore-prefixed command name. "_Loft" and "Loft" are
      both accepted; the plugin canonicalises to the underscore form.
    - args: optional list of strings. Each entry becomes one space-
      separated token after the command. Use `_Pause` to yield to the
      user, `_Enter` to finalise multi-step commands. Coordinates as
      strings (e.g. `"0,0,0"`, `"r0,0,5"`).
    - echo: if true the command-line output stays visible to the user.
      Off by default to keep batches quiet.

    Returns:
        {"success": true, "data": {
          "command": "_Loft",
          "script": "_Loft _Pause _Pause _Enter",
          "success": true,
          "message": "..."
        }}

    Example:
        run_native_command(
            command="_Sweep1",
            args=["_Pause", "_Pause", "_Enter"],
        )
    """
    try:
        if not command or not command.strip():
            return json.dumps(from_exception(
                ValueError("'command' is required"),
                code=ErrorCode.INVALID_PARAMS,
            ))

        params: Dict[str, Any] = {"command": command, "echo": echo}
        if args:
            params["args"] = args

        rhino = get_rhino_connection()
        result = rhino.send_command("run_native_command", params)
        return json.dumps(ok(
            message=result.get("message", "Command executed."),
            data=result,
        ))
    except Exception as e:
        logger.error(f"run_native_command failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
