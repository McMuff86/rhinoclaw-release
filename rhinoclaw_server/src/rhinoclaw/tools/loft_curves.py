import json
from typing import List, Literal

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

LoftType = Literal["normal", "loose", "tight", "straight"]

@mcp.tool()
def loft_curves(
    ctx: Context,
    curve_ids: List[str],
    closed: bool = False,
    loft_type: LoftType = "normal"
) -> str:
    """
    Create a lofted surface or solid between multiple curves.
    
    Parameters:
    - curve_ids: List of curve GUIDs to loft between (minimum 2 curves, order matters)
    - closed: If True, create a closed loft (connects last curve back to first)
    - loft_type: Type of loft interpolation:
        - "normal": Standard loft through curves
        - "loose": Loose fit (curves influence but don't pass exactly through)
        - "tight": Tight fit with more control points
        - "straight": Straight sections between curves (ruled surface)
    
    Returns:
    - New surface/brep ID(s)
    
    Notes:
    - Curves should be oriented consistently (same direction)
    - Curves can be open or closed but should be similar in structure
    - For closed lofts, at least 3 curves are recommended
    """
    # Validate parameters BEFORE connection (important for tests)
    if not curve_ids or len(curve_ids) < 2:
        return json.dumps(from_exception(
            ValueError("At least 2 curve IDs are required for loft operation"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    loft_type_upper = loft_type.upper()
    if loft_type_upper not in ["NORMAL", "LOOSE", "TIGHT", "STRAIGHT"]:
        return json.dumps(from_exception(
            ValueError(f"Invalid loft_type '{loft_type}'. Must be 'normal', 'loose', 'tight', or 'straight'"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("loft_curves", {
            "curve_ids": curve_ids,
            "closed": closed,
            "loft_type": loft_type_upper
        })
        
        return json.dumps(ok(
            message=f"Loft created from {len(curve_ids)} curves",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating loft: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
