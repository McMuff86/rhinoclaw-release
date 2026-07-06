import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def build_gh_definition(
    ctx: Context,
    file_path: str,
    components: List[Dict[str, Any]],
    wires: Optional[List[Dict[str, Any]]] = None,
    description: Optional[str] = None,
) -> str:
    """Build a Grasshopper definition (.gh) file programmatically.

    Authors a .gh on disk from a component graph — Number Sliders, Boolean
    Toggles, Panels, Python 3 Script components, and SDK components — wired
    together. This is the agent's *write* capability for Grasshopper: pair it
    with `inspect_grasshopper_definition` (read the result back) and
    `run_grasshopper` / `solve_grasshopper` / `bake_grasshopper` (execute) to
    author, run, and verify a definition in a loop.

    Parameters:
    - file_path: Output path for the .gh file (must end in `.gh`).
    - components: Component definitions. Each is a dict keyed by `type`:
        slider:         {"type":"slider","name":"Width","default":200,"min":10,"max":1000,"decimals":1,"position":[50,80]}
        toggle:         {"type":"toggle","name":"Closed","default":true,"position":[50,160]}
        panel:          {"type":"panel","name":"Label","value":"hello","position":[50,240]}
        python3_script: {"type":"python3_script","name":"MyScript","code":"...","inputs":["Width","Height"],"extra_outputs":["b"],"position":[450,160]}
        sdk_component:  {"type":"sdk_component","guid":"28061aae-...","name":"CenterBox","position":[450,160]}
    - wires: Connections between components. Each:
        {"from":"Width","to":"MyScript","to_input":"Width"}
        {"from":"MyScript","from_output":"a","to":"Preview","to_input":0}
      Optional — omit (or pass []) for a single-component definition.
    - description: Optional definition description.

    Returns:
        {"success": true, "message": "...", "data": {
            "file_path": "...", "object_count": N, "errors": [...],
            "status": "success" | "success_with_errors"}}

    Note: a `data.status` of "success_with_errors" means the file was written
    but some components/wires reported problems — inspect `data.errors`.
    """
    if not file_path:
        return json.dumps(from_exception(
            ValueError("file_path is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if not file_path.lower().endswith('.gh'):
        return json.dumps(from_exception(
            ValueError("file_path must be a .gh file"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if not components:
        return json.dumps(from_exception(
            ValueError("components must be a non-empty list"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        params: Dict[str, Any] = {
            "file_path": file_path,
            "components": components,
            "wires": wires or [],
        }
        if description is not None:
            params["description"] = description

        result = rhino.send_command("build_gh_definition", params)

        status = result.get("status", "success")
        error_count = len(result.get("errors", []) or [])
        return json.dumps(ok(
            message=f"Built GH definition: {file_path} "
                    f"({result.get('object_count', 0)} components, "
                    f"status={status}, {error_count} error(s))",
            data=result,
        ))
    except Exception as e:
        logger.error(f"Error building Grasshopper definition: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
