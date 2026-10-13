import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.utils.viewports import resolved_viewport_label, viewport_params

@mcp.tool()
def zoom_extents(
    ctx: Context,
    viewport_name: Optional[str] = None,
    include_hidden: bool = True
) -> str:
    """
    Zoom the viewport to show all objects.

    Parameters:
    - viewport_name: Optional localized name, GUID, or `Layout::Detail`.
      Omit it to zoom Rhino's active viewport.
    - include_hidden: Whether to include hidden objects in the zoom calculation

    Returns:
    Success message confirming the zoom operation

    Examples:
    - zoom_extents() - Zoom the active viewport to show all objects
    - zoom_extents(viewport_name="Top", include_hidden=False) - Zoom top view excluding hidden objects
    """
    try:
        rhino = get_rhino_connection()

        result = rhino.send_command(
            "zoom_extents",
            viewport_params({"include_hidden": include_hidden}, viewport_name),
        )
        resolved = resolved_viewport_label(result, viewport_name)

        return json.dumps(ok(
            message=f"Viewport '{resolved}' zoomed to extents",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error zooming to extents: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
