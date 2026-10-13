import json
from typing import Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.utils.viewports import (
    require_verified_viewport_mutation,
    resolved_viewport_label,
    viewport_params,
)

ViewType = Literal["Top", "Bottom", "Left", "Right", "Front", "Back", "Perspective", "TwoPointPerspective"]

@mcp.tool()
def set_view(
    ctx: Context,
    view_type: ViewType,
    viewport_name: Optional[str] = None,
) -> str:
    """
    Set the active viewport to a named view.

    Parameters:
    - view_type: The standard view to set ("Top", "Bottom", "Left", "Right", "Front", "Back", "Perspective", "TwoPointPerspective")
    - viewport_name: Optional localized name, GUID, or `Layout::Detail`.
      Omit it to modify Rhino's active viewport.

    Returns:
    Success message confirming the view change

    Examples:
    - set_view(view_type="Top") - Set to top view
    - set_view(view_type="Front", viewport_name="Top") - Set Top viewport to front view
    """
    if not isinstance(view_type, str) or not view_type.strip():
        return json.dumps(from_exception(
            ValueError("view_type is required"),
            code=ErrorCode.INVALID_PARAMS,
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command(
            "set_view",
            viewport_params({"view_type": view_type}, viewport_name),
        )
        require_verified_viewport_mutation(result)
        resolved = resolved_viewport_label(result, viewport_name)

        return json.dumps(ok(
            message=f"Viewport '{resolved}' set to {view_type} view",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error setting view: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
