import json
from typing import List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

CornerStyle = Literal["sharp", "round", "smooth", "chamfer"]


@mcp.tool()
def offset_curve(
    ctx: Context,
    curve_id: str,
    distance: float,
    plane_origin: Optional[List[float]] = None,
    plane_normal: Optional[List[float]] = None,
    corner_style: CornerStyle = "sharp"
) -> str:
    """
    Offset a curve by a specified distance.
    
    Parameters:
    - curve_id: GUID of the curve to offset
    - distance: Offset distance (positive = right side, negative = left side)
    - plane_origin: Optional [x, y, z] origin point for offset plane (default: curve start point)
    - plane_normal: Optional [x, y, z] normal vector for offset plane (default: [0, 0, 1] for XY plane)
    - corner_style: Corner style - "sharp", "round", "smooth", or "chamfer" (default: "sharp")
    
    Returns:
    - List of new offset curve IDs
    
    Notes:
    - Works with both open and closed curves
    - For closed curves, positive distance offsets outward, negative inward
    - Multiple curves may be returned if the offset self-intersects
    """
    # Validate parameters before connecting
    if not curve_id:
        return json.dumps(from_exception(
            ValueError("curve_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if distance == 0:
        return json.dumps(from_exception(
            ValueError("distance cannot be zero"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    valid_styles = ["sharp", "round", "smooth", "chamfer"]
    if corner_style not in valid_styles:
        return json.dumps(from_exception(
            ValueError(f"corner_style must be one of: {valid_styles}"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("offset_curve", {
            "curve_id": curve_id,
            "distance": distance,
            "plane_origin": plane_origin,
            "plane_normal": plane_normal or [0, 0, 1],
            "corner_style": corner_style
        })
        
        return json.dumps(ok(
            message=f"Offset curve created",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error offsetting curve: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
