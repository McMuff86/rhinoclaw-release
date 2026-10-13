import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.responses import from_exception, from_result
from rhinoclaw.utils.errors import ErrorCode


@mcp.tool()
def create_leader(
    ctx: Context,
    points: List[List[float]],
    text: Optional[str] = None,
    name: Optional[str] = None,
    color: Optional[List[int]] = None,
) -> str:
    """
    Create a Leader annotation.

    Parameters:
    - points: List of [x, y, z] points (at least two)
    - text: Optional leader text
    - name: Optional name for the object
    - color: Optional [r, g, b] color values (0-255)

    Returns:
    A message indicating the created leader name.
    """
    try:
        rhino = get_rhino_connection()
        params: Dict[str, Any] = {
            "type": "LEADER",
            "params": {
                "points": points,
                "text": text or "",
            },
        }
        if name:
            params["name"] = name
        if color:
            params["color"] = color

        result = rhino.send_command("create_object", params)
        return json.dumps(from_result(result, message="Annotation created"))
    except Exception as exc:
        # A timeout may have created the annotation already. Never fall back
        # to a second mutation; preserve the receipt for result lookup.
        logger.error("Annotation creation failed: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.CREATE_OBJECT_ERROR))
