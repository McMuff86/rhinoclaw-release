import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def explode_block(
    ctx: Context,
    instance_id: str
) -> str:
    """
    Explode a block instance into its constituent geometry.

    Parameters:
    - instance_id: ID of the block instance to explode

    Returns:
    JSON response with exploded object information

    Examples:
    - explode_block(instance_id="block_instance_123") - Explode the block instance
    """
    # Validate parameters before connecting
    if not instance_id or len(instance_id.strip()) == 0:
        return json.dumps(from_exception(
            ValueError("instance_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("explode_block", {
            "instance_id": instance_id
        })

        return json.dumps(ok(
            message=f"Exploded block instance to geometry",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error exploding block: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))