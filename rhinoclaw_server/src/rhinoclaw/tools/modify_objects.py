import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def modify_objects(
    ctx: Context,
    objects: List[Dict[str, Any]],
    all: Optional[bool] = None
) -> str:
    """
    Modify multiple objects at once in the Rhino document.
    
    Parameters:
    - objects: A List of objects, each containing the parameters for a single object modification 
    - all: If true, apply the first object's modifications to ALL objects in the document

    Each object dictionary can have the following fields:
    - id: The GUID of the object to modify (required unless 'all' is true)
    - new_color: [r, g, b] color values (0-255)
    - translation: [x, y, z] translation vector
    - rotation: [x, y, z] rotation in radians
    - scale: [x, y, z] scale factors
    - visible: Boolean to set visibility

    Returns:
        {"ok": true, "message": "Modified 5 objects", "data": {"modified": 5}}
    """
    try:
        rhino = get_rhino_connection()
        command_params = {"objects": objects}
        if all:
            command_params["all"] = all
        result = rhino.send_command("modify_objects", command_params)
        
        return json.dumps(ok(
            message=f"Modified {result['modified']} objects",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error modifying objects: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))

