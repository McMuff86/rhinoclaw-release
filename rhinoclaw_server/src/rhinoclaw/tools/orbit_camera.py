import json
import math
from typing import Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.utils.viewports import resolved_viewport_label, viewport_params

Direction = Literal["right", "left", "up", "down"]

@mcp.tool()
def orbit_camera(
    ctx: Context,
    direction: Direction,
    angle_degrees: float = 15.0,
    viewport_name: Optional[str] = None,
) -> str:
    """
    Rotate the camera around the current target (orbit around the model).
    
    This rotates the camera position while keeping the target fixed, allowing
    you to orbit around the model in perspective view.

    Parameters:
    - direction: Direction to rotate ("right", "left", "up", "down")
    - angle_degrees: Angle to rotate in degrees (default: 15.0)
    - viewport_name: Optional localized name, GUID, or `Layout::Detail`.
      Omit it to orbit Rhino's active viewport.

    Returns:
    Success message confirming the camera rotation

    Examples:
    - orbit_camera(direction="right", angle_degrees=30) - Rotate camera 30° to the right
    - orbit_camera(direction="up", angle_degrees=15) - Rotate camera 15° up
    """
    try:
        normalized_direction = (
            direction.lower() if isinstance(direction, str) else ""
        )
        if normalized_direction not in {"right", "left", "up", "down"}:
            return json.dumps(from_exception(
                ValueError(f"Invalid direction: {direction}. Must be 'right', 'left', 'up', or 'down'"),
                code=ErrorCode.INVALID_PARAMS
            ))
        if (
            not isinstance(angle_degrees, (int, float))
            or not math.isfinite(angle_degrees)
            or angle_degrees <= 0
        ):
            return json.dumps(from_exception(
                ValueError("angle_degrees must be a positive finite number"),
                code=ErrorCode.INVALID_PARAMS,
            ))

        rhino = get_rhino_connection()
        result = rhino.send_command(
            "orbit_camera",
            viewport_params(
                {
                    "direction": normalized_direction,
                    "angle_degrees": float(angle_degrees),
                },
                viewport_name,
            ),
        )

        resolved = resolved_viewport_label(result, viewport_name)
        return json.dumps(ok(
            message=(
                f"Camera orbited {normalized_direction} by {angle_degrees}° "
                f"in viewport '{resolved}'"
            ),
            data=result,
        ))
    except Exception as e:
        logger.error(f"Error orbiting camera: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
