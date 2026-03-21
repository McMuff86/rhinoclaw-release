import json
from typing import Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

RenderQuality = Literal["draft", "good", "high", "none"]


@mcp.tool()
def set_render_settings(
    ctx: Context,
    width: Optional[int] = None,
    height: Optional[int] = None,
    quality: Optional[RenderQuality] = None
) -> str:
    """
    Configure render resolution and quality.

    Parameters:
    - width: Render width in pixels (requires height)
    - height: Render height in pixels (requires width)
    - quality: Render antialiasing quality ("draft", "good", "high", "none")

    Returns:
    Success message with updated render settings
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

    if quality is not None:
        quality = quality.lower()

    if quality is not None and quality not in ("draft", "good", "high", "none"):
        return json.dumps(from_exception(
            ValueError("quality must be one of: draft, good, high, none"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if width is None and quality is None:
        return json.dumps(from_exception(
            ValueError("At least one of width/height or quality must be provided"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()
        params = {}

        if width is not None:
            params["width"] = width
            params["height"] = height

        if quality is not None:
            params["quality"] = quality

        result = rhino.send_command("set_render_settings", params)

        details = []
        if width is not None:
            details.append(f"{width}x{height}")
        if quality is not None:
            details.append(f"quality={quality}")

        message = "Render settings updated"
        if details:
            message = f"{message} ({', '.join(details)})"

        return json.dumps(ok(
            message=message,
            data=result
        ))
    except Exception as e:
        logger.error(f"Error setting render settings: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
