import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def list_block_definitions(
    ctx: Context,
    name_filter: Optional[str] = None,
    include_bbox: bool = False
) -> str:
    """
    List block (instance) definitions in the active document — compact and
    filterable.

    Use this instead of ad-hoc execute_rhinoscript block queries: unfiltered
    global queries used to produce huge, truncated responses. Pass
    name_filter to narrow down; with more than 100 matches the list is
    capped and `truncated: true` is returned.

    Parameters:
    - name_filter: Optional case-insensitive substring filter on the
      definition name (e.g. "Glutz").
    - include_bbox: Include each definition's bounding box (min/max in
      block coordinates). Off by default — it touches every definition
      object, so only request it when you need sizes.

    Returns:
        {"success": true, "data": {
            "definitions": [{"name", "id", "object_count",
                             "instance_count", "bbox"?, "source_archive"?}],
            "count": <returned>, "total_count": <matched>,
            "truncated": false}}

    Examples:
    - list_block_definitions()                       # overview, compact
    - list_block_definitions(name_filter="topaz")    # targeted lookup
    - list_block_definitions(name_filter="5632", include_bbox=True)
    """
    try:
        rhino = get_rhino_connection()
        params = {"include_bbox": bool(include_bbox)}
        if name_filter is not None:
            params["name_filter"] = name_filter
        result = rhino.send_command("list_block_definitions", params)

        count = result.get("count") if isinstance(result, dict) else None
        total = result.get("total_count") if isinstance(result, dict) else None
        message = f"{count} block definition(s)"
        if total is not None and count is not None and total > count:
            message += f" (of {total} matches — truncated, narrow with name_filter)"
        return json.dumps(ok(message=message, data=result))
    except Exception as e:
        logger.error(f"Error listing block definitions: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
