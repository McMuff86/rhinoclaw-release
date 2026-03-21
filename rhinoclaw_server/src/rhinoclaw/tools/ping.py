import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def ping(ctx: Context) -> str:
    """Send a ping to the Rhino plugin to check connectivity."""
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("ping", {})
        return json.dumps(ok(
            message=f"Pong from Rhino at {result['timestamp']}",
            data={"timestamp": result['timestamp']}
        ))
    except Exception as e:
        logger.error(f"Error in ping: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.CONNECTION_ERROR))
