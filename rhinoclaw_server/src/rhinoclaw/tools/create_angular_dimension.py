import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def create_angular_dimension(
    ctx: Context,
    vertex: List[float],
    start_point: List[float],
    end_point: List[float],
    text_point: List[float],
    dimension_style: Optional[str] = None
) -> str:
    """
    Create an angular dimension measuring the angle between two lines meeting at a vertex.
    
    Parameters:
    - vertex: [x, y, z] the common point where both lines meet
    - start_point: [x, y, z] a point on the first line (defines first ray from vertex)
    - end_point: [x, y, z] a point on the second line (defines second ray from vertex)
    - text_point: [x, y, z] location for the dimension arc and text
    - dimension_style: Optional name of dimension style to use
    
    Returns:
    - Object ID, dimension type, and measured angle in degrees
    
    Examples:
    - 90-degree angle:
      vertex=[0,0,0], start_point=[10,0,0], end_point=[0,10,0], text_point=[5,5,0]
    - 45-degree angle:
      vertex=[0,0,0], start_point=[10,0,0], end_point=[10,10,0], text_point=[8,4,0]
    
    Notes:
    - The vertex is the corner point of the angle
    - The angle is measured from start_point ray to end_point ray
    - text_point determines where the arc annotation appears
    """
    # Validate parameters before connecting
    if not vertex or len(vertex) != 3:
        return json.dumps(from_exception(
            ValueError("vertex must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
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
            "vertex": vertex,
            "start_point": start_point,
            "end_point": end_point,
            "text_point": text_point
        }
        if dimension_style:
            params["dimension_style"] = dimension_style
        
        result = rhino.send_command("create_angular_dimension", params)
        
        return json.dumps(ok(
            message="Angular dimension created",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating angular dimension: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
