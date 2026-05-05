import json
from typing import Any, Dict, List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_objects_info(ctx: Context, ids: List[str]) -> str:
    """Bulk version of get_object_info — one TCP round-trip for N objects.

    Same per-object payload as `get_object_info` (name, layer, type,
    bounding box, geometry-type-specific details for Brep / Mesh /
    Surface / Curve). Missing or invalid IDs are reported separately
    rather than failing the whole call.

    Use this when you have a list of GUIDs (e.g. from `find_objects`,
    `find_nearby`, `get_selected_objects_info`) and want their full
    metadata in one shot. On Tailscale-class latencies the difference
    vs a per-ID loop is dramatic — 50 objects go from ~0.5s of round-
    trip to a single ~30ms call.

    Parameters:
    - ids: list of GUID strings.

    Returns:
        {"success": true, "data": {
          "count": int,
          "missing_count": int,
          "results": [
            {"id": "...", "name": "...", "layer": "...", "type": "...",
             "geometry_details": {...}, "brep_details"|...: {...}}, ...
          ],
          "missing": [{"id": "...", "reason": "invalid_guid"|"not_found"}, ...]
        }}
    """
    try:
        if not isinstance(ids, list) or len(ids) == 0:
            return json.dumps(from_exception(
                ValueError("'ids' must be a non-empty list of GUID strings"),
                code=ErrorCode.INVALID_PARAMS,
            ))

        params: Dict[str, Any] = {"ids": ids}
        rhino = get_rhino_connection()
        result = rhino.send_command("get_objects_info", params)
        return json.dumps(ok(
            message=f"Resolved {result.get('count', 0)} of {len(ids)} object(s) "
                    f"({result.get('missing_count', 0)} missing).",
            data=result,
        ))
    except Exception as e:
        logger.error(f"get_objects_info failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
