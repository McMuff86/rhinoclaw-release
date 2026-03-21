import json
from typing import List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def mirror_object(
    ctx: Context,
    object_id: str,
    plane_origin: List[float],
    plane_normal: List[float],
    delete_input: bool = False
) -> str:
    """
    Mirror an object across a plane.
    
    Parameters:
    - object_id: GUID of the object to mirror
    - plane_origin: [x, y, z] point on the mirror plane
    - plane_normal: [x, y, z] normal vector of the mirror plane
    - delete_input: If True, delete the original object (default: False)
    
    Returns:
    - New object GUID of the mirrored copy
    
    Examples:
    - Mirror across XY plane: plane_origin=[0,0,0], plane_normal=[0,0,1]
    - Mirror across YZ plane: plane_origin=[0,0,0], plane_normal=[1,0,0]
    - Mirror across XZ plane: plane_origin=[0,0,0], plane_normal=[0,1,0]
    """
    # Validate parameters before connecting
    if not object_id:
        return json.dumps(from_exception(
            ValueError("object_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not plane_origin or len(plane_origin) != 3:
        return json.dumps(from_exception(
            ValueError("plane_origin must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not plane_normal or len(plane_normal) != 3:
        return json.dumps(from_exception(
            ValueError("plane_normal must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("mirror_object", {
            "object_id": object_id,
            "plane_origin": plane_origin,
            "plane_normal": plane_normal,
            "delete_input": delete_input
        })
        
        return json.dumps(ok(
            message="Object mirrored successfully",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error mirroring object: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
