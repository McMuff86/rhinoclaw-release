import json
from typing import Any, Dict, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_relationships(
    ctx: Context,
    object_id: str,
    touch_tolerance: Optional[float] = None,
    limit: int = 50,
) -> str:
    """Categorise other document objects by spatial relationship to a target.

    Three orthogonal relationship buckets:
    - **touching**: bbox-to-bbox distance is within `touch_tolerance` but
      interiors don't overlap.
    - **overlapping**: bboxes overlap (interiors share volume).
    - **aligned**: share a min/max coordinate on at least one axis,
      grouped per axis-and-side (`x_min`, `x_max`, `y_min`, `y_max`,
      `z_min`, `z_max`). Objects can be both aligned and touching/
      overlapping.

    Parameters:
    - object_id: GUID of the target.
    - touch_tolerance: bbox-distance threshold for "touching"
      (default `doc.ModelAbsoluteTolerance * 10`, min 0.001).
    - limit: max entries per bucket (default 50).

    Returns:
        {"success": true, "data": {
          "object_id": "...",
          "touch_tolerance": float,
          "touching":    [{"id":..,"name":..,"layer":..,"type":..}, ...],
          "overlapping": [...],
          "aligned": {"x_min": [...], "x_max": [...], "y_min": [...],
                      "y_max": [...], "z_min": [...], "z_max": [...]},
          "counts": {"touching": int, "overlapping": int, "aligned_total": int},
          "limit": int
        }}
    """
    try:
        if not object_id:
            return json.dumps(from_exception(
                ValueError("object_id is required"),
                code=ErrorCode.INVALID_PARAMS,
            ))

        params: Dict[str, Any] = {"object_id": object_id, "limit": limit}
        if touch_tolerance is not None:
            params["touch_tolerance"] = touch_tolerance

        rhino = get_rhino_connection()
        result = rhino.send_command("get_relationships", params)
        counts = result.get("counts", {})
        return json.dumps(ok(
            message=(
                f"{counts.get('touching', 0)} touching, "
                f"{counts.get('overlapping', 0)} overlapping, "
                f"{counts.get('aligned_total', 0)} aligned"
            ),
            data=result,
        ))
    except Exception as e:
        logger.error(f"get_relationships failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
