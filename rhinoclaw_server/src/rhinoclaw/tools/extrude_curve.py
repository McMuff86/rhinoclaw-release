import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def extrude_curve(
    ctx: Context,
    curve_id: str,
    direction: List[float],
    distance: Optional[float] = None,
    cap: bool = True
) -> str:
    """
    Extrude a curve along a direction vector to create a surface or solid.
    
    Parameters:
    - curve_id: The GUID of the curve to extrude
    - direction: Extrusion direction as [x, y, z] vector
    - distance: Optional distance to extrude (if not provided, uses vector length)
    - cap: If True and curve is closed, cap the ends to create a solid (default: True)
    
    Returns:
    - New surface/brep ID
    
    Notes:
    - If the curve is closed and cap=True, creates a capped solid (Brep)
    - If the curve is open, creates an open surface
    - Direction vector will be normalized and scaled by distance if provided
    
    Examples:
    - Extrude circle upward: extrude_curve(circle_id, [0, 0, 1], distance=10, cap=True)
    - Extrude line sideways: extrude_curve(line_id, [1, 0, 0], distance=5)
    """
    # Validate parameters BEFORE connection
    if not curve_id:
        return json.dumps(from_exception(
            ValueError("curve_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not direction or len(direction) != 3:
        return json.dumps(from_exception(
            ValueError("direction must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    # Check direction is not zero vector
    if all(d == 0 for d in direction):
        return json.dumps(from_exception(
            ValueError("direction cannot be zero vector"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    # Validate distance BEFORE connection
    if distance is not None and distance <= 0:
        return json.dumps(from_exception(
            ValueError("distance must be positive"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        params = {
            "curve_id": curve_id,
            "direction": direction,
            "cap": cap
        }
        
        if distance is not None:
            params["distance"] = distance
        
        result = rhino.send_command("extrude_curve", params)
        
        return json.dumps(ok(
            message=f"Curve extruded successfully",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error extruding curve: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
