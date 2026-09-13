"""MCP tools for external toolbox kits (``rhinoclaw-kit.json``)."""

import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.kits import (
    KitError,
    build_invoke_source,
    discover_kits,
    find_kit,
    parse_invoke_output,
    resolve_entry,
)
from rhinoclaw.utils.responses import error, from_exception, ok


@mcp.tool()
def kit_list(ctx: Context) -> str:
    """List external toolbox kits found on disk (no live Rhino needed).

    A kit is a folder with ``rhinoclaw-kit.json`` (schema rhinoclaw-kit/1).
    Search order:
    1. ``RHINOCLAW_KITS`` — path-separated kit roots or scan directories
    2. otherwise ``cwd``, ``cwd/..``, ``~/repos``, ``~/source/repos``
    3. plus ``RHINOCLAW_KITS_ROOT`` when set (one level deep)

    Call this once to see ids and which actions are ``callable`` versus
    ``interactive_only``. Then ``kit_describe`` for schemas, ``kit_invoke``
    to run a callable action through Rhino's Python 3 engine.

    Cheap call: filesystem only.
    """
    try:
        kits, errors = discover_kits()
        message = (
            f"{len(kits)} kit(s) found"
            if kits
            else "No kits found. Set RHINOCLAW_KITS to the toolbox folder."
        )
        return json.dumps(ok(
            message=message,
            data={
                "kits": [kit.to_summary() for kit in kits],
                "errors": errors,
            },
        ))
    except Exception as exc:
        logger.error("kit_list failed: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.INTERNAL_ERROR))


@mcp.tool()
def kit_describe(ctx: Context, kit: str) -> str:
    """Return one kit's actions, input schemas, and side effects.

    Parameters:
    - kit: kit id from ``kit_list`` (e.g. ``rhinolayouttools``)

    Use this before ``kit_invoke`` so arguments match ``input_schema``.
    Actions with ``status=interactive_only`` have no ``run()`` yet — tell
    the user to run the Rhino alias instead of inventing prompts.
    """
    if not kit:
        return json.dumps(error("kit is required", code=ErrorCode.MISSING_PARAMS))
    try:
        found = find_kit(kit)
        return json.dumps(ok(
            message=f"Kit '{found.id}': {len(found.actions)} action(s).",
            data=found.to_detail(),
        ))
    except KitError as exc:
        return json.dumps(error(str(exc), code=ErrorCode.INVALID_PARAMS))
    except Exception as exc:
        logger.error("kit_describe failed: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.INTERNAL_ERROR))


@mcp.tool()
def kit_invoke(
    ctx: Context,
    kit: str,
    action: str,
    args: str = "{}",
    timeout: Optional[float] = None,
) -> str:
    """Run a callable kit action in the connected Rhino (Python 3, no prompts).

    Parameters:
    - kit: kit id from ``kit_list``
    - action: action name from ``kit_describe`` (must be ``status=callable``)
    - args: JSON object matching the action's input_schema, default ``{}``
    - timeout: seconds for the Rhino Python-3 run (default server timeout)

    Interactive aliases stay untouched. This loads the declared ``entry``
    script and calls ``run(**args)`` inside Rhino via ``execute_python3_code``.
    The action result is a dict with ``ok`` plus domain fields; ``ok: false``
    is a rejected run, not a transport failure.
    """
    if not kit or not action:
        return json.dumps(error(
            "kit and action are required", code=ErrorCode.MISSING_PARAMS))
    try:
        parsed_args = json.loads(args) if args else {}
    except json.JSONDecodeError as exc:
        return json.dumps(error(
            f"args is not valid JSON: {exc}", code=ErrorCode.INVALID_PARAMS))
    if not isinstance(parsed_args, dict):
        return json.dumps(error(
            "args must be a JSON object", code=ErrorCode.INVALID_PARAMS))

    try:
        found = find_kit(kit)
        spec = found.action(action)
        if spec.status != "callable":
            alias = spec.alias or spec.name
            return json.dumps(error(
                f"Action '{action}' is interactive_only. "
                f"Ask the user to run the Rhino alias '{alias}' — "
                "there is no prompt-free run() yet.",
                code=ErrorCode.UNSUPPORTED_OPERATION,
                data={"kit": found.id, "action": spec.to_dict()},
            ))
        entry = resolve_entry(found, spec)
        source = build_invoke_source(entry, spec.invoke or "run", parsed_args)
    except KitError as exc:
        return json.dumps(error(str(exc), code=ErrorCode.INVALID_PARAMS))

    try:
        rhino = get_rhino_connection()
        result = rhino.send_command(
            "execute_python3_code",
            {"code": source},
            timeout=timeout,
        )
        if isinstance(result, dict) and result.get("success") is False:
            return json.dumps(error(
                result.get("message", "Python 3 execution failed"),
                code=ErrorCode.SCRIPT_ERROR,
                data=result,
            ))
        output = ""
        if isinstance(result, dict):
            output = str(result.get("result") or "")
        payload = parse_invoke_output(output)
        ok_flag = payload.get("ok", True)
        message = (
            f"Kit '{found.id}.{action}' completed"
            if ok_flag
            else f"Kit '{found.id}.{action}' refused: {payload.get('error', 'ok=false')}"
        )
        data = {
            "kit": found.id,
            "action": action,
            "result": payload,
            "engine": result if isinstance(result, dict) else {"result": result},
        }
        if not ok_flag:
            return json.dumps(error(message, code=payload.get("code") or ErrorCode.RHINO_ERROR, data=data))
        return json.dumps(ok(message=message, data=data))
    except KitError as exc:
        return json.dumps(error(str(exc), code=ErrorCode.SCRIPT_ERROR))
    except Exception as exc:
        logger.error("kit_invoke failed: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
