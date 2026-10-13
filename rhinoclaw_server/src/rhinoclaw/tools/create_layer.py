import json
from typing import List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def create_layer(
    ctx: Context,
    name: str = None,
    color: List[int] = None,
    parent: str = None,
) -> str:
    """Create a Rhino layer and return its native identity and attributes.

    name is optional. color is an optional [r, g, b] list (0-255).
    parent is the optional parent layer name.
    Returns the standard JSON success/message/data envelope; data contains
    the plugin's layer readback, including its id and name. Failures return
    success=false with a structured error code.
    """
    try:
        rhino = get_rhino_connection()
        command_params = {"name": name}
        if color is not None:
            command_params["color"] = color
        if parent is not None:
            command_params["parent"] = parent
        result = rhino.send_command("create_layer", command_params)
        return json.dumps(ok(message=f"Created layer: {result['name']}", data=result))
    except Exception as e:
        logger.error(f"Error creating layer: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.CREATE_LAYER_ERROR))
