import json
from typing import Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

RenderDisplayMode = Literal["rendered", "raytraced"]


@mcp.tool()
def render_view(
    ctx: Context,
    viewport_name: str = "Perspective",
    width: Optional[int] = None,
    height: Optional[int] = None,
    filename: Optional[str] = None,
    display_mode: RenderDisplayMode = "rendered"
) -> str:
    """
    Render the current viewport to an image.

    Parameters:
    - viewport_name: Name of the viewport to render
    - width: Render width in pixels (requires height)
    - height: Render height in pixels (requires width)
    - filename: Optional output path (if omitted, returns base64 data)
    - display_mode: Display mode to render ("rendered", "raytraced")

    Returns:
    Success message with image data or file path
    """
    if (width is None) != (height is None):
        return json.dumps(from_exception(
            ValueError("width and height must be provided together"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if width is not None and width <= 0:
        return json.dumps(from_exception(
            ValueError("width must be positive"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if height is not None and height <= 0:
        return json.dumps(from_exception(
            ValueError("height must be positive"),
            code=ErrorCode.INVALID_PARAMS
        ))

    display_mode = display_mode.lower()
    if display_mode not in ("rendered", "raytraced"):
        return json.dumps(from_exception(
            ValueError("display_mode must be one of: rendered, raytraced"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()
        params = {
            "viewport_name": viewport_name,
            "display_mode": display_mode,
            "filename": filename
        }

        if width is not None:
            params["width"] = width
            params["height"] = height

        result = rhino.send_command("render_view", params)

        return json.dumps(ok(
            message=f"Rendered viewport '{viewport_name}'",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error rendering viewport: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
