import json
from typing import List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def create_block(
    ctx: Context,
    name: str,
    object_ids: List[str],
    base_point: List[float] = None
) -> str:
    """
    Create a block definition from objects.

    Parameters:
    - name: Name for the block definition
    - object_ids: List of object IDs to include in the block
    - base_point: Optional base point [x, y, z] for the block (default: [0, 0, 0])

    Returns:
    JSON response with block definition information

    Examples:
    - create_block(name="Chair", object_ids=["leg1", "leg2", "seat", "back"])
    - create_block(name="Table", object_ids=["top", "legs"], base_point=[0, 0, 0])
    """
    # Validate parameters before connecting
    if not name or len(name.strip()) == 0:
        return json.dumps(from_exception(
            ValueError("name is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if not object_ids or len(object_ids) == 0:
        return json.dumps(from_exception(
            ValueError("object_ids is required and cannot be empty"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if base_point is not None and len(base_point) != 3:
        return json.dumps(from_exception(
            ValueError("base_point must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        if base_point is None:
            base_point = [0.0, 0.0, 0.0]

        result = rhino.send_command("create_block", {
            "name": name,
            "object_ids": object_ids,
            "base_point": base_point
        })

        return json.dumps(ok(
            message=f"Created block definition '{name}' with {len(object_ids)} objects",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error creating block: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))