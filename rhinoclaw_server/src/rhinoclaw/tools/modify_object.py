import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def modify_object(
    ctx: Context,
    id: Optional[str] = None,
    name: Optional[str] = None,
    new_name: Optional[str] = None,
    new_color: Optional[List[int]] = None,
    layer: Optional[str] = None,
    translation: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    visible: Optional[bool] = None
) -> str:
    """
    Modify an existing object in the Rhino document.
    
    Parameters:
    - id: The GUID of the object to modify (provide either id or name)
    - name: The name of the object to modify (provide either id or name)
    - new_name: New name for the object
    - new_color: [r, g, b] color values (0-255)
    - layer: Name of the layer to assign the object to
    - translation: [x, y, z] translation vector
    - rotation: [x, y, z] rotation in radians
    - scale: [x, y, z] scale factors
    - visible: Boolean to set visibility
    
    Returns:
        {"ok": true, "message": "Modified object: Box_1", "data": {"name": "Box_1", "id": "guid-here"}}
    """
    try:
        # Get the global connection
        rhino = get_rhino_connection()
        
        params : Dict[str, Any] = {}
        
        if id is not None:
            params["id"] = id
        if name is not None:
            params["name"] = name
        if new_name is not None:
            params["new_name"] = new_name
        if new_color is not None:
            params["new_color"] = new_color
        if layer is not None:
            params["layer"] = layer
        if translation is not None:
            params["translation"] = translation
        if rotation is not None:
            params["rotation"] = rotation
        if scale is not None:
            params["scale"] = scale
        if visible is not None:
            params["visible"] = visible
            
        result = rhino.send_command("modify_object", params)
        
        return json.dumps(ok(
            message=f"Modified object: {result['name']}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error modifying object: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))