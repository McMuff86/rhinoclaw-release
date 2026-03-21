import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def set_object_properties(
    ctx: Context,
    object_id: Optional[str] = None,
    object_ids: Optional[List[str]] = None,
    name: Optional[str] = None,
    layer: Optional[str] = None,
    color: Optional[List[int]] = None,
    material_id: Optional[int] = None
) -> str:
    """
    Set properties on one or more objects.

    Supports both single object and batch operations. At least one property
    must be specified to modify.

    Parameters:
        object_id: GUID of a single object to modify
        object_ids: List of GUIDs for batch operations
        name: New name for the object(s)
        layer: Layer name to move object(s) to
        color: RGB color [r, g, b] where each value is 0-255
        material_id: Material index to assign

    Returns:
        Success message with count of modified objects

    Example:
        set_object_properties(object_id="abc-123", name="MyBox", layer="Geometry")
        set_object_properties(object_ids=["id1", "id2"], color=[255, 0, 0])
    """
    if not object_id and not object_ids:
        return json.dumps(from_exception(
            ValueError("Either object_id or object_ids must be provided"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if name is None and layer is None and color is None and material_id is None:
        return json.dumps(from_exception(
            ValueError("At least one property (name, layer, color, material_id) must be specified"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if color is not None:
        if not isinstance(color, list) or len(color) != 3:
            return json.dumps(from_exception(
                ValueError("Color must be [r, g, b] with values 0-255"),
                code=ErrorCode.INVALID_PARAMS
            ))
        for c in color:
            if not isinstance(c, int) or c < 0 or c > 255:
                return json.dumps(from_exception(
                    ValueError("Color values must be integers 0-255"),
                    code=ErrorCode.INVALID_PARAMS
                ))
    
    try:
        rhino = get_rhino_connection()
        
        params = {}
        if object_id:
            params["object_id"] = object_id
        if object_ids:
            params["object_ids"] = object_ids
        if name is not None:
            params["name"] = name
        if layer is not None:
            params["layer"] = layer
        if color is not None:
            params["color"] = color
        if material_id is not None:
            params["material_id"] = material_id
        
        result = rhino.send_command("set_object_properties", params)
        return json.dumps(ok(message="Object properties updated", data=result))
    except Exception as e:
        logger.error(f"Error setting object properties: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
