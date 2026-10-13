import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.responses import from_exception, from_result
from rhinoclaw.utils.errors import ErrorCode


@mcp.tool()
def create_text(
    ctx: Context,
    text: str,
    location: List[float],
    height: float = 1.0,
    name: Optional[str] = None,
    color: Optional[List[int]] = None,
) -> str:
    """
    Create a TEXT annotation at a location.

    Parameters:
    - text: Text content
    - location: [x, y, z] insertion point
    - height: Text height (model units)
    - name: Optional name
    - color: Optional [r, g, b]
    """
    try:
        rhino = get_rhino_connection()
        params: Dict[str, Any] = {
            "type": "TEXT",
            "params": {"text": text, "location": location, "height": height},
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
