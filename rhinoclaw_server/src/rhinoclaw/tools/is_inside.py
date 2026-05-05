import json
from typing import Any, Dict, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def is_inside(
    ctx: Context,
    object_id: str,
    container_id: str,
    tolerance: Optional[float] = None,
    strictly_inside: bool = True,
) -> str:
    """Check whether `object_id` is contained inside `container_id`.

    Two strategies are tried in order:
    1. AABB reject — if bounding boxes don't even contain each other,
       returns false immediately.
    2. If the container is a closed Brep (solid), uses
       `Brep.IsPointInside` on the contained object's bbox center
       (and, in strict mode, all 8 corners). Otherwise the AABB result
       stands.

    Parameters:
    - object_id: GUID of the object whose containment is tested.
    - container_id: GUID of the container.
    - tolerance: defaults to `doc.ModelAbsoluteTolerance`.
    - strictly_inside: if true (default), every corner must be inside;
      if false, only the bbox center is tested.

    Returns:
        {"success": true, "data": {
          "is_inside": bool,
          "method": "bbox_reject" | "bbox_only" | "brep_point_in_volume",
          "object_id": "...", "container_id": "...",
          "strictly_inside": bool (when applicable)
        }}
    """
    try:
        if not object_id or not container_id:
            return json.dumps(from_exception(
                ValueError("object_id and container_id are required"),
                code=ErrorCode.INVALID_PARAMS,
            ))

        params: Dict[str, Any] = {
            "object_id": object_id,
            "container_id": container_id,
            "strictly_inside": strictly_inside,
        }
        if tolerance is not None:
            params["tolerance"] = tolerance

        rhino = get_rhino_connection()
        result = rhino.send_command("is_inside", params)
        verdict = "inside" if result.get("is_inside") else "outside"
        return json.dumps(ok(
            message=f"Object is {verdict} container ({result.get('method', 'unknown')})",
            data=result,
        ))
    except Exception as e:
        logger.error(f"is_inside failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
