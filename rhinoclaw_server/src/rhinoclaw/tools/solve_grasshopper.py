"""
Solve a loaded Grasshopper definition.

This tool triggers the Grasshopper solver to compute all outputs
based on the current parameter values.
"""

import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def solve_grasshopper(
    ctx: Context,
    definition_id: str,
    expire_all: bool = True,
) -> str:
    """
    Solve a loaded Grasshopper definition.
    
    Triggers the Grasshopper solver to compute all outputs based on
    the current parameter values. Call this after setting parameters
    and before baking or retrieving outputs.
    
    Parameters:
        definition_id: ID returned from load_grasshopper_definition
        expire_all: If True, forces full recalculation of all components.
                   If False, only recalculates components with expired inputs.
                   Default: True
    
    Returns:
        JSON object containing:
        - definition_id: The definition ID
        - status: "solved" or "solved_with_errors"
        - errors: Array of error messages (if any)
        - warnings: Array of warning messages (if any)
    
    Example:
        >>> # Load and configure
        >>> result = load_grasshopper_definition(file_path="C:/path/to/door.gh")
        >>> definition_id = result["data"]["definition_id"]
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Height", value=2400)
        >>> 
        >>> # Solve
        >>> solve_result = solve_grasshopper(definition_id=definition_id)
        >>> if solve_result["data"]["status"] == "solved":
        ...     # Now we can bake or get outputs
        ...     bake_grasshopper(definition_id=definition_id)
    
    Notes:
        - Must be called before bake_grasshopper or get_grasshopper_outputs
        - Errors from components are reported but don't stop execution
        - Some components may produce warnings that are informational
        - Use expire_all=False for faster incremental updates
    
    See Also:
        - set_grasshopper_parameter: Set inputs before solving
        - bake_grasshopper: Bake geometry after solving
        - get_grasshopper_outputs: Retrieve values after solving
    """
    if not definition_id:
        return json.dumps(from_exception(
            ValueError("definition_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("solve_grasshopper", {
            "definition_id": definition_id,
            "expire_all": expire_all
        })

        # Format message based on status
        status = result.get("status", "unknown")
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])
        
        if status == "solved":
            message = "Definition solved successfully"
        else:
            message = f"Definition solved with {len(errors)} error(s) and {len(warnings)} warning(s)"

        return json.dumps(ok(
            message=message,
            data=result
        ))
    except Exception as e:
        logger.error(f"Error solving Grasshopper definition: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
