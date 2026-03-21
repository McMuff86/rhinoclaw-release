"""
Set a parameter value in a loaded Grasshopper definition.

This tool allows programmatic control of Grasshopper input parameters
without using the interactive GrasshopperPlayer approach.
"""

import json
from typing import Any, Optional, Union

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def set_grasshopper_parameter(
    ctx: Context,
    definition_id: str,
    parameter_name: str,
    value: Union[str, int, float, bool, list],
) -> str:
    """
    Set a parameter value in a loaded Grasshopper definition.
    
    Parameters:
        definition_id: ID returned from load_grasshopper_definition
        parameter_name: Parameter nickname (case-insensitive)
        value: Value to set (type depends on parameter type):
            - NumberSlider/Number: numeric value (int or float)
            - Integer: integer value
            - String/Panel: string value
            - Boolean/BooleanToggle: boolean value
            - Point: [x, y, z] array or "x,y,z" string
    
    Returns:
        JSON object containing:
        - definition_id: The definition ID
        - parameter_name: The parameter that was set
        - parameter_type: The detected parameter type
        - value: The value that was set
        - status: "set" on success
    
    Example:
        >>> # First load the definition
        >>> result = load_grasshopper_definition(file_path="C:/path/to/door.gh")
        >>> definition_id = result["data"]["definition_id"]
        >>> 
        >>> # Set parameters
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Lichthoehe", value=2400)
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Lichtbreite", value=1000)
        >>> 
        >>> # Solve and bake
        >>> solve_grasshopper(definition_id=definition_id)
        >>> bake_grasshopper(definition_id=definition_id)
    
    Notes:
        - Parameter name matching is case-insensitive
        - Matches against both Name and Nickname
        - Call solve_grasshopper after setting parameters to compute results
        - Value must be compatible with the parameter type
    
    See Also:
        - load_grasshopper_definition: Load definition first
        - solve_grasshopper: Execute after setting parameters
    """
    if not definition_id:
        return json.dumps(from_exception(
            ValueError("definition_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if not parameter_name:
        return json.dumps(from_exception(
            ValueError("parameter_name is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if value is None:
        return json.dumps(from_exception(
            ValueError("value is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("set_grasshopper_parameter", {
            "definition_id": definition_id,
            "parameter_name": parameter_name,
            "value": value
        })

        return json.dumps(ok(
            message=f"Set parameter '{parameter_name}' = {value}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error setting Grasshopper parameter: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
