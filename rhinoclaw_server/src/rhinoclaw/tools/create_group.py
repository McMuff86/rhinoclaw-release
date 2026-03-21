import json
from typing import List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def create_group(
    ctx: Context,
    object_ids: List[str],
    name: str = None
) -> str:
    """
    Create a group from multiple objects.

    Parameters:
    - object_ids: List of object IDs to include in the group
    - name: Optional name for the group

    Returns:
    JSON response with group information

    Examples:
    - create_group(object_ids=["obj1", "obj2", "obj3"]) - Create unnamed group
    - create_group(object_ids=["obj1", "obj2"], name="MyGroup") - Create named group
    """
    # Validate parameters before connecting
    if not object_ids or len(object_ids) == 0:
        return json.dumps(from_exception(
            ValueError("At least one object_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("create_group", {
            "object_ids": object_ids,
            "group_name": name
        })

        return json.dumps(ok(
            message=f"Created group with {len(object_ids)} objects",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating group: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))