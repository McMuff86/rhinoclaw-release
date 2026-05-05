import json
from typing import Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

DistanceMetric = Literal["center", "closest"]


@mcp.tool()
def find_nearby(
    ctx: Context,
    point: List[float],
    radius: float,
    by: DistanceMetric = "center",
    limit: int = 100,
    layer: Optional[str] = None,
) -> str:
    """Find objects whose bounding box is within `radius` of `point`.

    Cheap O(n) AABB scan. Returns ID + name + layer + type + distance for
    each match, sorted ascending by distance.

    Parameters:
    - point: [x, y, z] query point.
    - radius: search radius in document units (must be > 0).
    - by: "center" (default) — distance from query point to bbox center;
      "closest" — distance to closest point on bbox surface (more accurate
      for large objects).
    - limit: max number of results (default 100).
    - layer: optional layer-name filter.

    Returns:
        {"success": true, "data": {
          "count": int,
          "search_point": [x, y, z],
          "search_radius": float,
          "distance_metric": "bbox_center" | "closest_point_on_bbox",
          "results": [{"id": "...", "name": "...", "layer": "...",
                       "type": "...", "distance": float}, ...]
        }}
    """
    try:
        if not isinstance(point, list) or len(point) < 3:
            return json.dumps(from_exception(
                ValueError("'point' must be a [x, y, z] list"),
                code=ErrorCode.INVALID_PARAMS,
            ))
        if radius <= 0:
            return json.dumps(from_exception(
                ValueError("'radius' must be > 0"),
                code=ErrorCode.INVALID_PARAMS,
            ))

        params: Dict[str, Any] = {"point": point, "radius": radius, "by": by, "limit": limit}
        if layer:
            params["layer"] = layer

        rhino = get_rhino_connection()
        result = rhino.send_command("find_nearby", params)
        return json.dumps(ok(
            message=f"Found {result.get('count', 0)} object(s) within {radius} of point",
            data=result,
        ))
    except Exception as e:
        logger.error(f"find_nearby failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
