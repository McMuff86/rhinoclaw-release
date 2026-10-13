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
    """Execute Python 3 (CPython) code in Rhino via the RhinoCode engine.

    Runs REAL Python 3 — not IronPython — in-process through the official
    RhinoCode API (Rhino.Runtime.Code): CPython 3.9+ in Rhino 8, CPython
    3.13 in Rhino 9. Use this when the code needs modern syntax or
    packages: f-strings, `pathlib`, `os.makedirs(exist_ok=True)`, type
    hints, `numpy`, or any pip package via RhinoCode requirement comments:

        # r: xlsxwriter
        import xlsxwriter
        ...

    `rhinoscriptsyntax`, `scriptcontext`, and `Rhino.*` are available and
    operate on the active document, exactly like the IronPython executor.
    Failed scripts return the real CPython traceback and roll back their
    own undo record (previous work is never popped).

    Style contract: write RhinoCommon-first. Use `Rhino.*` with
    `scriptcontext.doc` (`doc.Layers` + `ParentLayerId` for nested layers,
    `ObjectAttributes`, `TextEntity`, `Box.ToBrep()`, ...) instead of
    `rs.*` — `rhinoscriptsyntax` is an IronPython habit and hides object
    identity behind name lookups. Reach for `rs.*` only when RhinoCommon
    genuinely lacks the API. For nested layers, prefer the dedicated
    `ensure_layer_path` tool over any script.

    Engine choice:
    - `execute_rhinoscript_python_code` — IronPython 2.7: fast startup,
      battle-tested for plain `rs.*` document automation. No f-strings,
      no pip packages, no `exist_ok=`.
    - `execute_python3_code` (this tool) — CPython 3: modern syntax + pip
      packages. The plugin warms the engine when its server starts, so
      calls are normally fast; the first call only pays multi-second
      engine spin-up if that warm-up was skipped or is still running.

    Parameters:
    - code: Python 3 source. `# r:` / `# requirements:` comment lines are
      honored. On the RhinoCode path the code reaches the engine verbatim;
      the ScriptEditor fallback wraps it (indented into a try block, `# r:`
      lines hoisted to the top).
    - timeout: Seconds to wait (default: server setting; capped at
      `RHINOCLAW_MAX_TIMEOUT`, default 300). Reaches the plugin's
      UI-thread wait too (hard cap 300 s there) — raise it when a `# r:`
      requirement needs a first-time pip install.

    Returns:
        {"success": true, "data": {"method": "RhinoCode" | "ScriptEditor",
            "result": "...print output..."}}
        `method` reports the executing path: "RhinoCode" is the official
        API; "ScriptEditor" is the temp-file fallback used when the
        RhinoCode language cannot be resolved.
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
            "python3_engine": "RhinoCode" | "ScriptEditor" | null,
            "python3_warm": true, "rhino_version": "8.31..."}}

    `python3: true` means `execute_python3_code` is available (Rhino 8+).
    `python3_engine` reports which path would execute it right now —
    "RhinoCode" (official Rhino.Runtime.Code API) or "ScriptEditor"
    (temp-file fallback) — and `python3_warm` whether the CPython engine
    is already resolved (the plugin warms it at server start).
    `ironpython2` covers `execute_rhinoscript_python_code`.
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
