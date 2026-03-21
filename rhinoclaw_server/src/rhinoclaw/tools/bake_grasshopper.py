"""
Bake output geometry from a solved Grasshopper definition to Rhino.

This tool creates actual Rhino geometry objects from the computed
Grasshopper outputs.
"""

import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def bake_grasshopper(
    ctx: Context,
    definition_id: str,
    component_names: Optional[List[str]] = None,
    layer: Optional[str] = None,
) -> str:
    """
    Bake output geometry from a solved Grasshopper definition to Rhino.
    
    Creates actual Rhino geometry objects from the computed Grasshopper outputs.
    The definition must be solved first using solve_grasshopper.
    
    Parameters:
        definition_id: ID returned from load_grasshopper_definition
        component_names: Optional list of component nicknames to bake.
                        If not specified, bakes all output geometry.
        layer: Optional layer name for the baked geometry.
               Creates the layer if it doesn't exist.
    
    Returns:
        JSON object containing:
        - definition_id: The definition ID
        - baked_count: Number of objects baked
        - baked_objects: Array of baked objects with:
            - id: Rhino object GUID
            - component: Source component nickname
            - output: Source output nickname
        - layer: Target layer name (if specified)
    
    Example:
        >>> # Complete workflow
        >>> result = load_grasshopper_definition(file_path="C:/path/to/door.gh")
        >>> definition_id = result["data"]["definition_id"]
        >>> 
        >>> # Configure
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Height", value=2400)
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Width", value=1000)
        >>> 
        >>> # Solve
        >>> solve_grasshopper(definition_id=definition_id)
        >>> 
        >>> # Bake to specific layer
        >>> bake_result = bake_grasshopper(
        ...     definition_id=definition_id,
        ...     layer="Doors"
        ... )
        >>> print(f"Baked {bake_result['data']['baked_count']} objects")
        >>> 
        >>> # Optionally bake only specific components
        >>> bake_grasshopper(
        ...     definition_id=definition_id,
        ...     component_names=["Frame", "Panel"],
        ...     layer="Door_Parts"
        ... )
    
    Notes:
        - Definition must be solved first (solve_grasshopper)
        - Supports Brep, Surface, Mesh, Curve, Point, Line geometry
        - Objects supporting IGH_BakeAwareData use native baking
        - Created layer inherits default layer properties
        - Returns GUIDs of all created Rhino objects
    
    See Also:
        - solve_grasshopper: Must be called first
        - get_grasshopper_outputs: Get values without baking
        - unload_grasshopper_definition: Clean up when done
    """
    if not definition_id:
        return json.dumps(from_exception(
            ValueError("definition_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        params = {
            "definition_id": definition_id
        }
        
        if component_names is not None:
            params["component_names"] = component_names
        if layer is not None:
            params["layer"] = layer

        result = rhino.send_command("bake_grasshopper", params)

        baked_count = result.get("baked_count", 0)
        layer_name = result.get("layer", "Default")
        
        return json.dumps(ok(
            message=f"Baked {baked_count} object(s) to layer '{layer_name}'",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error baking Grasshopper geometry: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
