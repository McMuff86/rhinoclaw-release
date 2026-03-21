"""
Unload a Grasshopper definition from memory.

Use this to free memory when you're done with a Grasshopper definition.
"""

import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def unload_grasshopper_definition(
    ctx: Context,
    definition_id: str,
) -> str:
    """
    Unload a Grasshopper definition from memory.
    
    Frees the memory used by a loaded Grasshopper definition.
    Call this when you're done working with a definition.
    
    Parameters:
        definition_id: ID returned from load_grasshopper_definition
    
    Returns:
        JSON object containing:
        - definition_id: The unloaded definition ID
        - status: "unloaded" on success
    
    Example:
        >>> # Complete workflow with cleanup
        >>> result = load_grasshopper_definition(file_path="C:/path/to/door.gh")
        >>> definition_id = result["data"]["definition_id"]
        >>> 
        >>> try:
        ...     set_grasshopper_parameter(definition_id=definition_id, parameter_name="Height", value=2400)
        ...     solve_grasshopper(definition_id=definition_id)
        ...     bake_grasshopper(definition_id=definition_id, layer="Doors")
        ... finally:
        ...     # Always clean up
        ...     unload_grasshopper_definition(definition_id=definition_id)
    
    Notes:
        - The definition_id becomes invalid after unloading
        - Multiple definitions can be loaded simultaneously
        - Use list_grasshopper_definitions to see loaded definitions
    
    See Also:
        - load_grasshopper_definition: Load a definition
        - list_grasshopper_definitions: See all loaded definitions
    """
    if not definition_id:
        return json.dumps(from_exception(
            ValueError("definition_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("unload_grasshopper_definition", {
            "definition_id": definition_id
        })

        return json.dumps(ok(
            message=f"Unloaded Grasshopper definition: {definition_id}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error unloading Grasshopper definition: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
