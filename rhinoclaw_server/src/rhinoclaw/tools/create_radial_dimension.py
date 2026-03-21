import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def create_radial_dimension(
    ctx: Context,
    center: List[float],
    radius_point: List[float],
    is_diameter: bool = False,
    dimension_style: Optional[str] = None
) -> str:
    """
    Create a radial dimension showing radius or diameter.
    
    Parameters:
    - center: [x, y, z] center point of the circle/arc
    - radius_point: [x, y, z] a point on the circle/arc circumference
    - is_diameter: If True, show diameter; if False (default), show radius
    - dimension_style: Optional name of dimension style to use
    
    Returns:
    - Object ID, dimension type, radius, and diameter values
    
    Examples:
    - Radius dimension for circle at origin with radius 10:
      center=[0,0,0], radius_point=[10,0,0], is_diameter=False
    - Diameter dimension:
      center=[0,0,0], radius_point=[10,0,0], is_diameter=True
    
    Notes:
    - The radius is calculated from center to radius_point
    - The dimension text/leader extends from center through radius_point
    - For arcs, radius_point should be on the arc
    """
    # Validate parameters before connecting
    if not center or len(center) != 3:
        return json.dumps(from_exception(
            ValueError("center must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not radius_point or len(radius_point) != 3:
        return json.dumps(from_exception(
            ValueError("radius_point must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        params = {
            "center": center,
            "radius_point": radius_point,
            "is_diameter": is_diameter
        }
        if dimension_style:
            params["dimension_style"] = dimension_style
        
        result = rhino.send_command("create_radial_dimension", params)
        
        dim_type = "Diameter" if is_diameter else "Radius"
        return json.dumps(ok(
            message=f"{dim_type} dimension created",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating radial dimension: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
