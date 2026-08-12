import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.tools.find_gh_component import _catalog
from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError
from rhinoclaw.utils.gh_catalog import (
    authoring_catalog_contract,
    catalog_verification_failure_data,
    require_catalog_verification,
)
from rhinoclaw.utils.gh_lint import lint_definition
from rhinoclaw.utils.responses import error, from_exception, ok


@mcp.tool()
def build_and_bake_gh(
    ctx: Context,
    file_path: str,
    components: List[Dict[str, Any]],
    wires: Optional[List[Dict[str, Any]]] = None,
    layer: str = "GH_Bake",
    material: Optional[str] = None,
    description: Optional[str] = None,
    bake_output: str = "a",
) -> str:
    """Build a Grasshopper definition, solve it, and bake its geometry to a layer.

    One-shot author → solve → bake: writes the `.gh` (see
    `build_gh_definition` for the component/wire schema), solves it, and bakes
    the resulting geometry onto `layer`, returning the baked object GUIDs so a
    follow-up step can address them.

    ⚠️ LIMITATION (Rhino 8, verified 2026-06-04): Grasshopper **script
    components do NOT execute in headless solve** — confirmed for both the
    Python 3 (CPython) and legacy GhPython (IronPython) components. A definition
    whose geometry comes from a `python3_script` / `ghpython_script` therefore
    bakes nothing (`data.status == "no_geometry"`, `diagnostics.items_in_output
    == 0`). This is a Rhino platform limit, not a RhinoClaw bug.
    - For geometry from a SCRIPT, bake directly via
      `execute_rhinoscript_python_code` (IronPython + RhinoCommon) instead.
    - `build_gh_definition` (authoring only) is unaffected — the script runs
      when the .gh is opened in the Grasshopper canvas.
    - Headless bake here is reliable only for SDK-native component graphs.

    Parameters:
    - file_path: Output path for the .gh file (must end in `.gh`).
    - components / wires: Same schema as `build_gh_definition`.
    - layer: Target layer for baked geometry (created if missing; default "GH_Bake").
    - material: Optional material name to assign to the target layer.
    - description: Optional definition description.
    - bake_output: Nickname of the component output to bake (default "a").
      Set this for SDK-native components whose geometry output is not "a"
      (e.g. Center Box → "B", Sphere → "S"). Native-component recipes set this
      automatically per component.

    Returns:
        {"success": true, "message": "...", "data": {
            "file_path": "...", "layer": "...", "baked_count": N,
            "baked_ids": ["guid", ...],
            "status": "success" | "no_geometry" | "build_errors" | "error"}}

    Note: the call succeeds at the transport level even when the inner
    `data.status` reports a build/bake problem — "no_geometry" means it solved
    but baked nothing, "build_errors" means the .gh had build errors. Always
    check `data.status` and `data.baked_count`.
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

    catalog = _catalog()
    lint = lint_definition(components, wires, catalog=catalog)
    if not lint["valid"]:
        return json.dumps(error(
            "Grasshopper build-and-bake failed static authoring preflight",
            code=ErrorCode.INVALID_PARAMS,
            data={"lint": lint},
        ))

    try:
        rhino = get_rhino_connection()

        params: Dict[str, Any] = {
            "file_path": file_path,
            "components": components,
            "wires": wires or [],
            "layer": layer,
            "bake_output": bake_output,
            "catalog_contract": authoring_catalog_contract(
                catalog, components
            ),
        }
        if material is not None:
            params["material"] = material
        if description is not None:
            params["description"] = description

        result = rhino.send_command("build_and_bake_gh", params)
        require_catalog_verification(result)
        result["lint"] = lint

        status = result.get("status", "success")
        baked_count = result.get("baked_count", 0)
        return json.dumps(ok(
            message=f"Built + baked: {file_path} → layer "
                    f"'{result.get('layer', layer)}', "
                    f"{baked_count} object(s) (status={status})",
            data=result,
        ))
    except RhinoCommandError as e:
        logger.error(f"Error building + baking Grasshopper definition: {str(e)}")
        if e.error_code == ErrorCode.VERIFICATION_FAILED:
            return json.dumps(error(
                str(e),
                code=ErrorCode.VERIFICATION_FAILED,
                data=catalog_verification_failure_data(
                    e, mutation_attempted=True),
            ))
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
    except Exception as e:
        logger.error(f"Error building + baking Grasshopper definition: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
