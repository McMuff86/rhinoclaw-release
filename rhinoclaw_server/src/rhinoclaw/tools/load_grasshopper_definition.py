"""
Load a Grasshopper definition file and return information about its parameters.

This tool uses the Grasshopper SDK directly to load .gh/.ghx files,
providing programmatic access to parameters without opening the Grasshopper UI.
"""

import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def load_grasshopper_definition(
    ctx: Context,
    file_path: str,
) -> str:
    """
    Load a Grasshopper definition file and return information about its parameters.
    
    The definition is stored in memory for subsequent operations like
    set_grasshopper_parameter, solve_grasshopper, bake_grasshopper, etc.
    
    Parameters:
        file_path: Full path to the .gh or .ghx Grasshopper definition file
    
    Returns:
        JSON object containing:
        - definition_id: Unique identifier for subsequent operations
        - file_path: Path to the loaded file
        - file_name: Just the filename
        - parameters: List of input parameters with:
            - name: Parameter display name
            - nickname: Parameter nickname (use this for set_grasshopper_parameter)
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
        - Use unload_grasshopper_definition to free memory when done
        - This is different from run_grasshopper which uses GrasshopperPlayer
    
    See Also:
        - set_grasshopper_parameter: Set input values
        - solve_grasshopper: Execute the definition
        - bake_grasshopper: Bake output geometry to Rhino
        - get_grasshopper_outputs: Retrieve computed values
    """
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

        return json.dumps(ok(
            message=f"Loaded Grasshopper definition: {result.get('file_name', file_path)}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error loading Grasshopper definition: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
