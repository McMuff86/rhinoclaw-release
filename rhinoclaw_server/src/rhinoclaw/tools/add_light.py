import json
from typing import List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

LightType = Literal["point", "directional", "spot"]


def _is_point(value: Optional[List[float]]) -> bool:
    return isinstance(value, list) and len(value) == 3


def _is_color(value: Optional[List[int]]) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(
        isinstance(channel, int) and 0 <= channel <= 255 for channel in value
    )


@mcp.tool()
def add_light(
    ctx: Context,
    light_type: LightType,
    location: Optional[List[float]] = None,
    direction: Optional[List[float]] = None,
    target: Optional[List[float]] = None,
    color: Optional[List[int]] = None,
    intensity: float = 1.0,
    name: Optional[str] = None,
    spot_angle_degrees: Optional[float] = 45.0
) -> str:
    """
    Add a light to the document.

    Parameters:
    - light_type: "point", "directional", or "spot"
    - location: Light location [x, y, z] (required for point/spot)
    - direction: Direction vector [x, y, z] (required for directional)
    - target: Target point [x, y, z] (required for spot)
    - color: [r, g, b] color values (0-255)
    - intensity: Light intensity (> 0)
    - name: Optional light name
    - spot_angle_degrees: Spotlight cone angle in degrees (spot only)

    Returns:
    Success message with light ID
    """
    if not light_type:
        return json.dumps(from_exception(
            ValueError("light_type is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    light_type = light_type.lower()

    if color is None:
        color = [255, 255, 255]

    if not _is_color(color):
        return json.dumps(from_exception(
            ValueError("color must be [r, g, b] with values 0-255"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if intensity <= 0:
        return json.dumps(from_exception(
            ValueError("intensity must be positive"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if light_type == "point":
        if not _is_point(location):
            return json.dumps(from_exception(
                ValueError("location is required for point lights"),
                code=ErrorCode.INVALID_PARAMS
            ))
    elif light_type == "directional":
        if not _is_point(direction):
            return json.dumps(from_exception(
                ValueError("direction is required for directional lights"),
                code=ErrorCode.INVALID_PARAMS
            ))
    elif light_type == "spot":
        if not _is_point(location) or not _is_point(target):
            return json.dumps(from_exception(
                ValueError("location and target are required for spot lights"),
                code=ErrorCode.INVALID_PARAMS
            ))
        if spot_angle_degrees is not None and spot_angle_degrees <= 0:
            return json.dumps(from_exception(
                ValueError("spot_angle_degrees must be positive"),
                code=ErrorCode.INVALID_PARAMS
            ))
    else:
        return json.dumps(from_exception(
            ValueError("light_type must be one of: point, directional, spot"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()
        params = {
            "light_type": light_type,
            "color": color,
            "intensity": intensity
        }

        if name:
            params["name"] = name

        if location is not None:
            params["location"] = location

        if direction is not None:
            params["direction"] = direction

        if target is not None:
            params["target"] = target

        if light_type == "spot" and spot_angle_degrees is not None:
            params["spot_angle_degrees"] = spot_angle_degrees

        result = rhino.send_command("add_light", params)

        return json.dumps(ok(
            message=f"Added {light_type} light",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error adding light: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
