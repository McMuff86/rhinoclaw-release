import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.responses import from_exception, from_result
from rhinoclaw.utils.errors import ErrorCode


@mcp.tool()
def create_text_dot(
    ctx: Context,
    text: str,
    location: List[float],
    name: Optional[str] = None,
    color: Optional[List[int]] = None,
) -> str:
    """
    Create a TEXT_DOT annotation at a location.

    Parameters:
    - text: Text content
    - location: [x, y, z] position
    - name: Optional name
    - color: Optional [r, g, b]
    """
    try:
        rhino = get_rhino_connection()
        params: Dict[str, Any] = {
            "type": "TEXT_DOT",
            "params": {"text": text, "location": location},
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
