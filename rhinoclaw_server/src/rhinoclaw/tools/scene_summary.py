import json
from typing import Any, Dict

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def scene_summary(
    ctx: Context,
    include_layers: bool = True,
    include_types: bool = True,
) -> str:
    """High-level overview of the active document.

    Cheap O(n) walk of the object table. Useful as a first call when an
    agent picks up an unfamiliar `.3dm` — answers "how many objects",
    "what kinds", "which layers do they live on", "where in space".

    Parameters:
    - include_layers: include per-layer counts and bounding boxes
      (default True).
    - include_types: include per-Rhino-type counts (Brep, Mesh, Curve,
      …) sorted descending (default True).

    Returns:
        {"success": true, "data": {
          "object_count": int,
          "doc_bbox": {"min": [x,y,z], "max": [...], "size": [...], "center": [...]} | null,
          "types":  {"Brep": 30, "Curve": 12, ...},          # if include_types
          "layers": {"Default": {"count": 25, "bbox": {...}}, ...}  # if include_layers
        }}
    """
    try:
        params: Dict[str, Any] = {
            "include_layers": include_layers,
            "include_types": include_types,
        }
        rhino = get_rhino_connection()
        result = rhino.send_command("scene_summary", params)
        return json.dumps(ok(
            message=f"Scene contains {result.get('object_count', 0)} object(s)",
            data=result,
        ))
    except Exception as e:
        logger.error(f"scene_summary failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
