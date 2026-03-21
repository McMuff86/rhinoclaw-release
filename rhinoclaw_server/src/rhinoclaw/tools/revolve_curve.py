import json
from typing import List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def revolve_curve(
    ctx: Context,
    curve_id: str,
    axis_start: List[float],
    axis_end: List[float],
    angle: float = 360.0
) -> str:
    """
    Revolve a curve around an axis to create a surface of revolution.
    
    Parameters:
    - curve_id: The GUID of the curve to revolve
    - axis_start: Start point of the revolution axis as [x, y, z]
    - axis_end: End point of the revolution axis as [x, y, z]
    - angle: Angle of revolution in degrees (default: 360 for full revolution)
    
    Returns:
    - New surface/brep ID
    
    Notes:
    - The curve is revolved around the line defined by axis_start to axis_end
    - For 360° revolution, creates a closed surface (like a vase or sphere)
    - For partial revolution, creates an open surface
    - Curve should not cross the axis of revolution
    
    Examples:
    - Revolve profile around Z-axis: revolve_curve(profile_id, [0,0,0], [0,0,1], 360)
    - Create half-pipe: revolve_curve(arc_id, [0,0,0], [1,0,0], 180)
    """
    # Validate parameters BEFORE connection
    if not curve_id:
        return json.dumps(from_exception(
            ValueError("curve_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not axis_start or len(axis_start) != 3:
        return json.dumps(from_exception(
            ValueError("axis_start must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not axis_end or len(axis_end) != 3:
        return json.dumps(from_exception(
            ValueError("axis_end must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    # Check axis is not zero length
    if axis_start == axis_end:
        return json.dumps(from_exception(
            ValueError("axis_start and axis_end cannot be the same point"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if angle == 0:
        return json.dumps(from_exception(
            ValueError("angle cannot be zero"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("revolve_curve", {
            "curve_id": curve_id,
            "axis_start": axis_start,
            "axis_end": axis_end,
            "angle": angle
        })
        
        return json.dumps(ok(
            message=f"Curve revolved {angle}° successfully",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error revolving curve: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
