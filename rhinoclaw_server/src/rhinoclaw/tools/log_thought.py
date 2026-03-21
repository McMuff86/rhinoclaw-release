from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp


@mcp.tool()
def log_thought(ctx: Context, thought: str) -> str:
    """Log the AI's thought process to Rhino for debugging."""
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("log_thought", {"thought": thought})
        return f"Thought logged: {thought[:50]}..."
    except Exception as e:
        logger.error(f"Error logging thought: {str(e)}")
        return f"Error: {str(e)}"
