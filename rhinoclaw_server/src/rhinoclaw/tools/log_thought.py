from rhinoclaw.utils.responses import from_exception, from_result
import json
from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp


@mcp.tool()
def log_thought(ctx: Context, thought: str) -> str:
    """Log the AI's thought process to Rhino for debugging."""
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("log_thought", {"thought": thought})
        return json.dumps(from_result(result, message="Thought logged"))
    except Exception as e:
        logger.error(f"Error logging thought: {str(e)}")
        return json.dumps(from_exception(e))
