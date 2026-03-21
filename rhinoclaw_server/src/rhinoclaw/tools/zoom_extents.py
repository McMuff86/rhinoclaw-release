import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

@mcp.tool()
def zoom_extents(
    ctx: Context,
    viewport_name: str = "Perspective",
    include_hidden: bool = True
) -> str:
    """
    Zoom the viewport to show all objects.

    Parameters:
    - viewport_name: Name of the viewport to zoom (default: "Perspective")
    - include_hidden: Whether to include hidden objects in the zoom calculation

    Returns:
    Success message confirming the zoom operation

    Examples:
    - zoom_extents() - Zoom perspective viewport to show all objects
    - zoom_extents(viewport_name="Top", include_hidden=False) - Zoom top view excluding hidden objects
    """
    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("zoom_extents", {
            "viewport_name": viewport_name,
            "include_hidden": include_hidden
        })

        return json.dumps(ok(
            message=f"Viewport '{viewport_name}' zoomed to extents",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error zooming to extents: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))