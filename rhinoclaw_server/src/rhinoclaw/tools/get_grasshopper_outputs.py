"""
Get output values from a solved Grasshopper definition.

This tool retrieves computed values without baking geometry to Rhino.
Useful for getting numeric results, dimensions, or other non-geometry outputs.
"""

import json
from typing import Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.gh_output_targets import validate_output_targets
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_grasshopper_outputs(
    ctx: Context,
    definition_id: str,
    output_names: Optional[List[str]] = None,
    output_targets: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Get output values from a solved Grasshopper definition.
    
    Retrieves computed values without baking geometry to Rhino.
    Useful for getting numeric results, dimensions, text, or other
    non-geometry outputs.
    
    Parameters:
        definition_id: ID returned from load_grasshopper_definition
        output_names: Optional list of output nicknames to retrieve.
                     If not specified, returns all outputs.
        output_targets: Exact component/output instance-GUID pairs returned by
                        load/get_grasshopper_outputs. Mutually exclusive with
                        output_names and recommended for duplicate nicknames.
    
    Returns:
        JSON object containing:
        - definition_id: The definition ID
        - schema_version: Output schema version (currently 2).
        - outputs: Dictionary of outputs. The first friendly key is
          "ComponentName.OutputName"; nickname collisions are retained under
          a key suffixed with stable component/output instance GUIDs:
            - component: Source component nickname
            - component_instance_id / output_instance_id: stable identity
            - output: Output nickname
            - type: Output type name
            - access: item/list/tree access declared by the output
            - values: Backward-compatible flattened/nested values
            - paths: Explicit GH paths with indices and per-item type,
              validity and real JSON null values
            - count: Number of values
    
    Example:
        >>> # Load and solve
        >>> result = load_grasshopper_definition(file_path="C:/path/to/calculator.gh")
        >>> definition_id = result["data"]["definition_id"]
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Length", value=5.0)
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Width", value=3.0)
        >>> solve_grasshopper(definition_id=definition_id)
        >>> 
        >>> # Get computed values
        >>> outputs = get_grasshopper_outputs(definition_id=definition_id)
        >>> area = outputs["data"]["outputs"]["Multiply.Result"]["values"][0]
        >>> print(f"Area: {area}")
        >>> 
        >>> # Get specific outputs only
        >>> outputs = get_grasshopper_outputs(
        ...     definition_id=definition_id,
        ...     output_names=["Result", "Total"]
        ... )
    
    Value Types:
        - Numbers: Returned as float/int
        - Strings: Returned as string
        - Booleans: Returned as bool
        - Points: Returned as {"x": float, "y": float, "z": float}
        - Vectors: Returned as {"x": float, "y": float, "z": float}
        - Planes: Returned as {"origin": {...}, "normal": {...}}
        - Colors: Returned as {"r": int, "g": int, "b": int, "a": int}
        - Intervals: Returned as {"min": float, "max": float}
        - Geometry: Returned as description string (use bake_grasshopper instead)
    
    Notes:
        - Definition must be solved first (solve_grasshopper)
        - For geometry outputs, use bake_grasshopper instead
        - Output names are matched case-insensitively
        - Multi-branch data retains every GH_Path in `paths`; `values` remains
          available for backward compatibility.
        - Duplicate component/output nicknames never discard an output; use
          component_instance_id + output_instance_id as canonical identity.
    
    See Also:
        - solve_grasshopper: Must be called first
        - bake_grasshopper: For geometry outputs
    """
    if not definition_id:
        return json.dumps(from_exception(
            ValueError("definition_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    if output_names is not None and output_targets is not None:
        return json.dumps(from_exception(
            ValueError("output_names and output_targets are mutually exclusive"),
            code=ErrorCode.INVALID_PARAMS,
        ))
    try:
        canonical_targets = validate_output_targets(output_targets) \
            if output_targets is not None else None
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    try:
        rhino = get_rhino_connection()

        params = {
            "definition_id": definition_id
        }
        
        if output_names is not None:
            params["output_names"] = output_names
        if canonical_targets is not None:
            params["output_targets"] = canonical_targets

        result = rhino.send_command("get_grasshopper_outputs", params)

        outputs = result.get("outputs", {})
        output_count = len(outputs)
        
        return json.dumps(ok(
            message=f"Retrieved {output_count} output(s) from definition",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error getting Grasshopper outputs: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
