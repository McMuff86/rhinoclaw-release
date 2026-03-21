import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def fillet_curves(
    ctx: Context,
    curve_id_1: str,
    curve_id_2: str,
    radius: float,
    point_on_curve_1: Optional[List[float]] = None,
    point_on_curve_2: Optional[List[float]] = None,
    join: bool = False
) -> str:
    """
    Create a fillet arc between two curves.
    
    Parameters:
    - curve_id_1: GUID of the first curve
    - curve_id_2: GUID of the second curve
    - radius: Fillet radius (must be positive)
    - point_on_curve_1: Optional [x, y, z] point near where fillet should be on curve 1
    - point_on_curve_2: Optional [x, y, z] point near where fillet should be on curve 2
    - join: If True, join the fillet with the trimmed curves (default: False)
    
    Returns:
    - New curve IDs (fillet arc, and optionally joined curve)
    
    Notes:
    - The fillet is created at the intersection or closest point of the curves
    - Original curves are trimmed if they intersect
    - If join=True, returns a single joined curve
    """
    # Validate parameters before connecting
    if not curve_id_1:
        return json.dumps(from_exception(
            ValueError("curve_id_1 is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not curve_id_2:
        return json.dumps(from_exception(
            ValueError("curve_id_2 is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if radius <= 0:
        return json.dumps(from_exception(
            ValueError("radius must be positive"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("fillet_curves", {
            "curve_id_1": curve_id_1,
            "curve_id_2": curve_id_2,
            "radius": radius,
            "point_on_curve_1": point_on_curve_1,
            "point_on_curve_2": point_on_curve_2,
            "join": join
        })
        
        return json.dumps(ok(
            message=f"Fillet created with radius {radius}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating fillet: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
