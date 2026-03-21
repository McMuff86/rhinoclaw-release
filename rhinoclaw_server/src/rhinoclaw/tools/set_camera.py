import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


def _is_point(value: Optional[List[float]]) -> bool:
    return isinstance(value, list) and len(value) == 3


@mcp.tool()
def set_camera(
    ctx: Context,
    camera_location: List[float],
    target_location: Optional[List[float]] = None,
    lens_length: Optional[float] = None,
    viewport_name: str = "Perspective"
) -> str:
    """
    Set the camera position for a viewport.

    Parameters:
    - camera_location: Camera location [x, y, z]
    - target_location: Optional target location [x, y, z]
    - lens_length: Optional 35mm lens length
    - viewport_name: Name of the viewport to modify

    Returns:
    Success message with camera settings
    """
    if not _is_point(camera_location):
        return json.dumps(from_exception(
            ValueError("camera_location must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if target_location is not None and not _is_point(target_location):
        return json.dumps(from_exception(
            ValueError("target_location must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if lens_length is not None and lens_length <= 0:
        return json.dumps(from_exception(
            ValueError("lens_length must be positive"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()
        params = {
            "viewport_name": viewport_name,
            "camera_location": camera_location
        }

        if target_location is not None:
            params["target_location"] = target_location

        if lens_length is not None:
            params["lens_length"] = lens_length

        result = rhino.send_command("set_camera", params)

        return json.dumps(ok(
            message=f"Camera updated for viewport '{viewport_name}'",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error setting camera: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
