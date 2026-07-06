import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok


@mcp.tool()
def execute_python3_code(
    ctx: Context,
    code: str,
    timeout: Optional[float] = None,
) -> str:
    """Execute Python 3 (CPython) code in Rhino 8's ScriptEditor runtime.

    Runs REAL Python 3 (CPython 3.9+, the Script Editor engine) — not
    IronPython. Use this when the code needs modern syntax or packages:
    f-strings, `pathlib`, `os.makedirs(exist_ok=True)`, type hints,
    `numpy`, or any pip package via RhinoCode requirement comments:

        # r: xlsxwriter
        import xlsxwriter
        ...

    `rhinoscriptsyntax`, `scriptcontext`, and `Rhino.*` are available and
    operate on the active document, exactly like the IronPython executor.

    Engine choice:
    - `execute_rhinoscript_python_code` — IronPython 2.7: fast startup,
      battle-tested for plain `rs.*` document automation. No f-strings,
      no pip packages, no `exist_ok=`.
    - `execute_python3_code` (this tool) — CPython 3.9+: modern syntax +
      pip packages; first call can take a few seconds (runtime spin-up,
      package install on new `# r:` requirements).

    Parameters:
    - code: Python 3 source. `# r:` / `# requirements:` comment lines are
      honored anywhere in the code (the plugin hoists them to the top).
    - timeout: Seconds to wait (default: server setting; raise it when a
      `# r:` requirement needs a first-time pip install).

    Returns:
        {"success": true, "data": {"method": "ScriptEditor" | "CodePlatform",
            "result": "...print output..."}}
        On script errors: {"success": false, "message": "<traceback>"}.

    Requires Rhino 8+ with the Script Editor (check `get_script_capabilities`).
    """
    if not code:
        return json.dumps(from_exception(
            ValueError("code is required"), code=ErrorCode.INVALID_PARAMS))

    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("execute_python3_code", {"code": code},
                                    timeout=timeout)

        if isinstance(result, dict) and result.get("success") is False:
            # Script-level failure: surface the traceback as the message.
            return json.dumps(error(
                result.get("message", "Python 3 execution failed"),
                code=ErrorCode.RHINO_ERROR,
                data=result,
            ))

        return json.dumps(ok(
            message="Python 3 code executed",
            data=result if isinstance(result, dict) else {"result": result},
        ))
    except Exception as e:
        logger.error(f"Error executing Python 3 code: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def get_script_capabilities(ctx: Context) -> str:
    """Report which script engines the connected Rhino supports.

    Returns:
        {"success": true, "data": {"ironpython2": true, "python3": true,
            "rhino_version": "8.31..."}}

    `python3: true` means `execute_python3_code` (CPython via the Script
    Editor) is available; `ironpython2` covers
    `execute_rhinoscript_python_code`. Python 3 requires Rhino 8+.
    """
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("get_script_capabilities", {})
        return json.dumps(ok(
            message=f"Engines: ironpython2={result.get('ironpython2')}, "
                    f"python3={result.get('python3')}",
            data=result,
        ))
    except Exception as e:
        logger.error(f"Error getting script capabilities: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
