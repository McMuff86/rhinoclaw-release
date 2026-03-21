import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def array_polar(
    ctx: Context,
    object_id: str,
    center: List[float],
    axis: List[float],
    count: int,
    angle: Optional[float] = None
) -> str:
    """
    Create a polar (radial) array of objects around a center point.
    
    Parameters:
    - object_id: GUID of the object to array
    - center: [x, y, z] center point of rotation
    - axis: [x, y, z] rotation axis vector (will be normalized)
    - count: Total number of objects in the array (including original)
    - angle: Total angle in degrees to fill (default: 360 for full circle)
    
    Returns:
    - List of new object GUIDs (does not include original)
    
    Examples:
    - Polar array of 6 objects in full circle around Z axis:
      center=[0,0,0], axis=[0,0,1], count=6
    - Polar array of 4 objects in 180 degrees:
      center=[0,0,0], axis=[0,0,1], count=4, angle=180
    """
    # Validate parameters before connecting
    if not object_id:
        return json.dumps(from_exception(
            ValueError("object_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not center or len(center) != 3:
        return json.dumps(from_exception(
            ValueError("center must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not axis or len(axis) != 3:
        return json.dumps(from_exception(
            ValueError("axis must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if count < 2:
        return json.dumps(from_exception(
            ValueError("count must be at least 2 (includes original)"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        total_angle = angle if angle is not None else 360.0
        rhino = get_rhino_connection()
        
        result = rhino.send_command("array_polar", {
            "object_id": object_id,
            "center": center,
            "axis": axis,
            "count": count,
            "angle": total_angle
        })
        
        return json.dumps(ok(
            message=f"Created polar array with {count} objects",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating polar array: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
