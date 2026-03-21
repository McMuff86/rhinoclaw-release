"""
List all currently loaded Grasshopper definitions.

Use this to see what definitions are currently in memory.
"""

import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def list_grasshopper_definitions(
    ctx: Context,
) -> str:
    """
    List all currently loaded Grasshopper definitions.
    
    Returns information about all Grasshopper definitions that have been
    loaded into memory using load_grasshopper_definition.
    
    Returns:
        JSON object containing:
        - definitions: Array of loaded definitions with:
            - definition_id: The definition ID (use for other operations)
            - file_path: Full path to the .gh/.ghx file
            - file_name: Just the filename
            - object_count: Number of Grasshopper objects in definition
        - count: Total number of loaded definitions
    
    Example:
        >>> # Load some definitions
        >>> load_grasshopper_definition(file_path="C:/path/to/door.gh")
        >>> load_grasshopper_definition(file_path="C:/path/to/window.gh")
        >>> 
        >>> # List loaded definitions
        >>> result = list_grasshopper_definitions()
        >>> for defn in result["data"]["definitions"]:
        ...     print(f"{defn['file_name']}: {defn['definition_id']}")
        door.gh: abc12345
        window.gh: def67890
    
    Notes:
        - Definitions stay loaded until unload_grasshopper_definition is called
        - Each definition uses memory - unload when done
        - Loading the same file again replaces the previous definition
    
    See Also:
        - load_grasshopper_definition: Load a definition
        - unload_grasshopper_definition: Unload when done
    """
    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("list_grasshopper_definitions", {})

        definitions = result.get("definitions", [])
        count = result.get("count", len(definitions))
        
        return json.dumps(ok(
            message=f"Found {count} loaded Grasshopper definition(s)",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error listing Grasshopper definitions: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
