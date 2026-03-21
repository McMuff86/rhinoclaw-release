import json
from typing import List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

@mcp.tool()
def zoom_selected(
    ctx: Context,
    object_ids: List[str] = None,
    viewport_name: str = "Perspective"
) -> str:
    """
    Zoom the viewport to show selected objects.

    Parameters:
    - object_ids: List of object GUIDs to zoom to. If empty, zooms to currently selected objects.
    - viewport_name: Name of the viewport to zoom (default: "Perspective")

    Returns:
    Success message confirming the zoom operation

    Examples:
    - zoom_selected() - Zoom to currently selected objects
    - zoom_selected(object_ids=["id1", "id2"]) - Zoom to specific objects
    """
    try:
        rhino = get_rhino_connection()

        if object_ids and len(object_ids) == 0:
            return json.dumps(from_exception(
                ValueError("object_ids list cannot be empty"),
                code=ErrorCode.INVALID_PARAMS
            ))

        result = rhino.send_command("zoom_selected", {
            "object_ids": object_ids,
            "viewport_name": viewport_name
        })

        return json.dumps(ok(
            message=f"Viewport '{viewport_name}' zoomed to selected objects",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error zooming to selected: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))