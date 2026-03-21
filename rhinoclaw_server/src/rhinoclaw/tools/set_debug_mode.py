from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp, set_debug_mode


@mcp.tool()
def set_debug_mode_tool(ctx: Context, enable: bool) -> str:
    """Enable or disable debug mode for enhanced logging."""
    try:
        set_debug_mode(enable)
        # Also send command to Rhino to set debug mode there
        rhino = get_rhino_connection()
        result = rhino.send_command("set_debug_mode", {"enable": enable})
        return f"Debug mode {'enabled' if enable else 'disabled'}"
    except Exception as e:
        logger.error(f"Error setting debug mode: {str(e)}")
        return f"Error: {str(e)}"
