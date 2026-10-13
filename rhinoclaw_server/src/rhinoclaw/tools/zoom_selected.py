import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.utils.viewports import resolved_viewport_label, viewport_params

@mcp.tool()
def zoom_selected(
    ctx: Context,
    object_ids: Optional[List[str]] = None,
    viewport_name: Optional[str] = None,
) -> str:
    """
    Zoom the viewport to show selected objects.

    Parameters:
    - object_ids: List of object GUIDs to zoom to. If empty, zooms to currently selected objects.
    - viewport_name: Optional localized name, GUID, or `Layout::Detail`.
      Omit it to zoom Rhino's active viewport.

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

        result = rhino.send_command(
            "zoom_selected",
            viewport_params({"object_ids": object_ids}, viewport_name),
        )
        resolved = resolved_viewport_label(result, viewport_name)

        return json.dumps(ok(
            message=f"Viewport '{resolved}' zoomed to selected objects",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error zooming to selected: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
