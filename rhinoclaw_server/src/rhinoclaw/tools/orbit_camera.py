import json
from typing import Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

Direction = Literal["right", "left", "up", "down"]

@mcp.tool()
def orbit_camera(
    ctx: Context,
    direction: Direction,
    angle_degrees: float = 15.0,
    viewport_name: str = "Perspective"
) -> str:
    """
    Rotate the camera around the current target (orbit around the model).
    
    This rotates the camera position while keeping the target fixed, allowing
    you to orbit around the model in perspective view.

    Parameters:
    - direction: Direction to rotate ("right", "left", "up", "down")
    - angle_degrees: Angle to rotate in degrees (default: 15.0)
    - viewport_name: Name of the viewport to modify (default: "Perspective")

    Returns:
    Success message confirming the camera rotation

    Examples:
    - orbit_camera(direction="right", angle_degrees=30) - Rotate camera 30° to the right
    - orbit_camera(direction="up", angle_degrees=15) - Rotate camera 15° up
    """
    try:
        rhino = get_rhino_connection()
        
        # Map direction to RhinoScript direction codes
        # 0=right, 1=left, 2=down, 3=up
        direction_map = {
            "right": 0,
            "left": 1,
            "down": 2,
            "up": 3
        }
        
        direction_code = direction_map.get(direction.lower())
        if direction_code is None:
            return json.dumps(from_exception(
                ValueError(f"Invalid direction: {direction}. Must be 'right', 'left', 'up', or 'down'"),
                code=ErrorCode.INVALID_PARAMS
            ))
        
        # Use RhinoScript to rotate camera
        code = f"""
import rhinoscriptsyntax as rs
rs.RotateCamera(view="{viewport_name}", direction={direction_code}, angle={angle_degrees})
"""
        
        result = rhino.send_command("execute_rhinoscript_python_code", {
            "code": code
        })
        
        return json.dumps(ok(
            message=f"Camera rotated {direction} by {angle_degrees}° in viewport '{viewport_name}'",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error orbiting camera: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
