import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def chamfer_curves(
    ctx: Context,
    curve_id_1: str,
    curve_id_2: str,
    distance_1: float,
    distance_2: Optional[float] = None,
    point_on_curve_1: Optional[List[float]] = None,
    point_on_curve_2: Optional[List[float]] = None,
    join: bool = False,
    trim: bool = True
) -> str:
    """
    Create a chamfer (angled line) between two curves.
    
    Parameters:
    - curve_id_1: GUID of the first curve
    - curve_id_2: GUID of the second curve
    - distance_1: Chamfer distance from intersection along curve 1 (must be positive)
    - distance_2: Chamfer distance from intersection along curve 2 (default: same as distance_1)
    - point_on_curve_1: Optional [x, y, z] point near where chamfer should be on curve 1
    - point_on_curve_2: Optional [x, y, z] point near where chamfer should be on curve 2
    - join: If True, join the chamfer with the trimmed curves (default: False)
    - trim: If True, trim the original curves at chamfer points (default: True)
    
    Returns:
    - New curve IDs (chamfer line, and optionally joined curve)
    
    Notes:
    - Creates a straight line connecting points at specified distances from intersection
    - Original curves are trimmed at the chamfer points by default
    - If distance_2 is not specified, uses distance_1 for both curves (symmetric chamfer)
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
    
    if distance_1 <= 0:
        return json.dumps(from_exception(
            ValueError("distance_1 must be positive"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    # Use distance_1 for both if distance_2 not specified
    if distance_2 is None:
        distance_2 = distance_1
    elif distance_2 <= 0:
        return json.dumps(from_exception(
            ValueError("distance_2 must be positive"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("chamfer_curves", {
            "curve_id_1": curve_id_1,
            "curve_id_2": curve_id_2,
            "distance_1": distance_1,
            "distance_2": distance_2,
            "point_on_curve_1": point_on_curve_1,
            "point_on_curve_2": point_on_curve_2,
            "join": join,
            "trim": trim
        })
        
        return json.dumps(ok(
            message=f"Chamfer created with distances {distance_1}, {distance_2}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating chamfer: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
