import json
from typing import Literal

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

ViewType = Literal["Top", "Bottom", "Left", "Right", "Front", "Back", "Perspective", "TwoPointPerspective"]

@mcp.tool()
def set_view(
    ctx: Context,
    view_type: ViewType,
    viewport_name: str = "Perspective"
) -> str:
    """
    Set the active viewport to a named view.

    Parameters:
    - view_type: The standard view to set ("Top", "Bottom", "Left", "Right", "Front", "Back", "Perspective", "TwoPointPerspective")
    - viewport_name: Name of the viewport to modify (default: "Perspective")

    Returns:
    Success message confirming the view change

    Examples:
    - set_view(view_type="Top") - Set to top view
    - set_view(view_type="Front", viewport_name="Top") - Set Top viewport to front view
    """
    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("set_view", {
            "view_type": view_type,
            "viewport_name": viewport_name
        })

        return json.dumps(ok(
            message=f"Viewport '{viewport_name}' set to {view_type} view",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error setting view: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))