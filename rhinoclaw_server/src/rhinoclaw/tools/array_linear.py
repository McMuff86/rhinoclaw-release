import json
from typing import List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def array_linear(
    ctx: Context,
    object_id: str,
    direction: List[float],
    count: int,
    spacing: float
) -> str:
    """
    Create a linear array of objects.
    
    Parameters:
    - object_id: GUID of the object to array
    - direction: [x, y, z] unit vector for array direction (will be normalized)
    - count: Total number of objects in the array (including original)
    - spacing: Distance between each object along the direction
    
    Returns:
    - List of new object GUIDs (does not include original)
    
    Examples:
    - Array 5 objects along X axis with 10 unit spacing:
      direction=[1,0,0], count=5, spacing=10
    - Array 3 objects along diagonal:
      direction=[1,1,0], count=3, spacing=15
    """
    # Validate parameters before connecting
    if not object_id:
        return json.dumps(from_exception(
            ValueError("object_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not direction or len(direction) != 3:
        return json.dumps(from_exception(
            ValueError("direction must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if count < 2:
        return json.dumps(from_exception(
            ValueError("count must be at least 2 (includes original)"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if spacing <= 0:
        return json.dumps(from_exception(
            ValueError("spacing must be positive"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("array_linear", {
            "object_id": object_id,
            "direction": direction,
            "count": count,
            "spacing": spacing
        })
        
        return json.dumps(ok(
            message=f"Created linear array with {count} objects",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating linear array: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
