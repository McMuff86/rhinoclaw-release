import json
from typing import List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def insert_block(
    ctx: Context,
    block_name: str,
    position: List[float],
    scale: List[float] = None,
    rotation: List[float] = None
) -> str:
    """
    Insert a block instance at the specified position.

    Parameters:
    - block_name: Name of the block definition to insert
    - position: Position [x, y, z] to insert the block
    - scale: Optional scale factors [x, y, z] (default: [1, 1, 1])
    - rotation: Optional rotation angles [x, y, z] in degrees (default: [0, 0, 0])

    Returns:
    JSON response with block instance information

    Examples:
    - insert_block(block_name="Chair", position=[10, 0, 0])
    - insert_block(block_name="Table", position=[5, 5, 0], scale=[2, 2, 2])
    """
    # Validate parameters before connecting
    if not block_name or len(block_name.strip()) == 0:
        return json.dumps(from_exception(
            ValueError("block_name is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if position is None or len(position) != 3:
        return json.dumps(from_exception(
            ValueError("position must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if scale is not None and len(scale) != 3:
        return json.dumps(from_exception(
            ValueError("scale must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if rotation is not None and len(rotation) != 3:
        return json.dumps(from_exception(
            ValueError("rotation must be [x, y, z]"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        if scale is None:
            scale = [1.0, 1.0, 1.0]
        if rotation is None:
            rotation = [0.0, 0.0, 0.0]

        result = rhino.send_command("insert_block", {
            "block_name": block_name,
            "position": position,
            "scale": scale,
            "rotation": rotation
        })

        return json.dumps(ok(
            message=f"Inserted block instance of '{block_name}'",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error inserting block: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))