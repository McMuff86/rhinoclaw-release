import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def create_linear_dimension(
    ctx: Context,
    start_point: List[float],
    end_point: List[float],
    text_point: List[float],
    dimension_style: Optional[str] = None
) -> str:
    """
    Create a linear dimension between two points.
    
    Parameters:
    - start_point: [x, y, z] first point of the dimension
    - end_point: [x, y, z] second point of the dimension
    - text_point: [x, y, z] location for the dimension text/line
    - dimension_style: Optional name of dimension style to use
    
    Returns:
    - Object ID, dimension type, and measured distance
    
    Examples:
    - Horizontal dimension:
      start_point=[0,0,0], end_point=[10,0,0], text_point=[5,2,0]
    - Vertical dimension:
      start_point=[0,0,0], end_point=[0,0,10], text_point=[2,0,5]
    
    Notes:
    - The text_point determines where the dimension line is placed
    - Distance from text_point to the line between start/end determines offset
    """
    # Validate parameters before connecting
    if not start_point or len(start_point) != 3:
        return json.dumps(from_exception(
            ValueError("start_point must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not end_point or len(end_point) != 3:
        return json.dumps(from_exception(
            ValueError("end_point must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not text_point or len(text_point) != 3:
        return json.dumps(from_exception(
            ValueError("text_point must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        params = {
            "start_point": start_point,
            "end_point": end_point,
            "text_point": text_point
        }
        if dimension_style:
            params["dimension_style"] = dimension_style
        
        result = rhino.send_command("create_linear_dimension", params)
        
        return json.dumps(ok(
            message="Linear dimension created",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating linear dimension: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
