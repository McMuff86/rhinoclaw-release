"""
Load a Grasshopper definition file and return information about its parameters.

This tool uses the Grasshopper SDK directly to load .gh/.ghx files,
providing programmatic access to parameters without opening the Grasshopper UI.
"""

import json
from uuid import UUID

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok
from rhinoclaw.tools.grasshopper_canvas import show_grasshopper_definition


def _verify_parameter_identity(result):
    issues = []
    parameters = result.get("parameters")
    if result.get("parameter_identity") != "parameter_instance_id":
        issues.append("parameter_identity must be parameter_instance_id")
    if not isinstance(parameters, list):
        issues.append("parameters must be a list")
        parameters = []
    seen = set()
    settable_count = 0
    for index, parameter in enumerate(parameters):
        if not isinstance(parameter, dict):
            issues.append(f"parameters[{index}] must be an object")
            continue
        raw_id = parameter.get("parameter_instance_id")
        try:
            parameter_id = UUID(raw_id) if isinstance(raw_id, str) else None
        except ValueError:
            parameter_id = None
        if parameter_id is None or parameter_id.int == 0:
            issues.append(
                f"parameters[{index}].parameter_instance_id is invalid"
            )
        elif str(parameter_id) in seen:
            issues.append(
                f"parameters[{index}].parameter_instance_id is duplicated"
            )
        else:
            seen.add(str(parameter_id))
        if parameter.get("settable_by_instance_id") is True:
            settable_count += 1
    if result.get("settable_parameter_count") != settable_count:
        issues.append("settable_parameter_count does not match parameters")
    return {"pass": not issues, "issues": issues}


@mcp.tool()
def load_grasshopper_definition(
    ctx: Context,
    file_path: str,
    show_in_grasshopper: bool = False,
) -> str:
    """
    Load a Grasshopper definition file and return information about its parameters.
    
    The definition is stored in memory for subsequent operations like
    set_grasshopper_parameter, solve_grasshopper, bake_grasshopper, etc.
    
    Parameters:
        file_path: Full path to the .gh or .ghx Grasshopper definition file
        show_in_grasshopper: Show the loaded instance on the visible canvas.
            Subsequent parameter updates/solves address this same instance.
            Default False preserves the headless workflow. Does not open chat;
            use show_grasshopper_definition(open_chat=True) for that.
    
    Returns:
        JSON object containing:
        - definition_id: Unique identifier for subsequent operations
        - file_path: Path to the loaded file
        - file_name: Just the filename
        - parameters: List of input parameters with:
            - name: Parameter display name
            - nickname: Parameter nickname (use this for set_grasshopper_parameter)
            - parameter_instance_id: Stable identity for atomic exact setting
            - settable_by_instance_id: Whether the exact batch setter supports it
            - type: Parameter type (NumberSlider, Panel, BooleanToggle, etc.)
            - value: Current value
            - min/max: For sliders, the valid range
            - component_guid: Internal GUID
        - outputs: List of output components with:
            - name: Output name
            - nickname: Output nickname
            - type: Output type
            - component_name: Parent component name
            - component_guid: Internal GUID
        - object_count: Total number of objects in the definition
    
    Example:
        >>> load_grasshopper_definition(file_path="C:/path/to/door.gh")
        {
            "ok": true,
            "data": {
                "definition_id": "abc12345",
                "file_name": "door.gh",
                "parameters": [
                    {"name": "Height", "nickname": "Lichthoehe", "type": "NumberSlider", "value": 2200},
                    {"name": "Width", "nickname": "Lichtbreite", "type": "NumberSlider", "value": 910}
                ],
                "outputs": [
                    {"name": "Geometry", "nickname": "Geo", "type": "Brep", "component_name": "Bake"}
                ]
            }
        }
    
    Notes:
        - The definition_id is required for all subsequent operations
        - Multiple definitions can be loaded simultaneously
        - Already-open paths are rejected rather than replaced from disk.
          Reuse their definition_id or choose a new iteration path.
        - Parameter identities are required to be unique; duplicate legacy
          slider/parameter rows fail verification instead of becoming
          ambiguous batch inputs
        - Use unload_grasshopper_definition to free memory when done
        - This is different from run_grasshopper which uses GrasshopperPlayer
    
    See Also:
        - set_grasshopper_parameter: Set input values
        - solve_grasshopper: Execute the definition
        - bake_grasshopper: Bake output geometry to Rhino
        - get_grasshopper_outputs: Retrieve computed values
    """
    if not isinstance(show_in_grasshopper, bool):
        return json.dumps(from_exception(
            ValueError("show_in_grasshopper must be a boolean"), code=ErrorCode.INVALID_PARAMS))
    if not file_path:
        return json.dumps(from_exception(
            ValueError("file_path is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    ext = file_path.lower()
    if not ext.endswith('.gh') and not ext.endswith('.ghx'):
        return json.dumps(from_exception(
            ValueError("file_path must be a .gh or .ghx file"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("load_grasshopper_definition", {
            "file_path": file_path
        })

        verification = _verify_parameter_identity(result)
        result["parameter_verification"] = verification
        if not verification["pass"]:
            return json.dumps(error(
                "Loaded definition returned inconsistent parameter identities",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))

        if show_in_grasshopper:
            presentation = json.loads(show_grasshopper_definition(
                ctx, result["definition_id"]))
            result["presentation"] = presentation
            if presentation.get("success") is not True:
                return json.dumps(error(
                    "Definition loaded, but canvas presentation failed; reuse the retained definition_id",
                    code=ErrorCode.VERIFICATION_FAILED, data=result))

        return json.dumps(ok(
            message=f"Loaded Grasshopper definition: {result.get('file_name', file_path)}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error loading Grasshopper definition: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
