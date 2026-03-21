import json
from typing import List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def ungroup(
    ctx: Context,
    group_id: str
) -> str:
    """
    Ungroup objects from a group.

    Parameters:
    - group_id: ID of the group to ungroup

    Returns:
    JSON response with ungrouped object information

    Examples:
    - ungroup(group_id="group123") - Ungroup the specified group
    """
    # Validate parameters before connecting
    if not group_id or len(group_id.strip()) == 0:
        return json.dumps(from_exception(
            ValueError("group_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("ungroup", {
            "group_id": group_id
        })

        return json.dumps(ok(
            message=f"Ungrouped group with {result.get('object_count', 0)} objects",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error ungrouping: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))