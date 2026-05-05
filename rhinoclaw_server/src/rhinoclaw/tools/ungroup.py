import json

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

        # Normalize plugin response: prefer object_count, fall back to objects_released.
        data = dict(result)
        if "object_count" not in data and "objects_released" in data:
            # Plugin returns total released across all groups; expose as object_count
            # of the (single) group operated on.
            data["object_count"] = data["objects_released"] // max(data.get("groups_ungrouped", 1), 1)
        data.setdefault("groups_ungrouped", 1)

        return json.dumps(ok(
            message=f"Ungrouped group with {data.get('object_count', 0)} objects",
            data=data
        ))
    except Exception as e:
        logger.error(f"Error ungrouping: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
