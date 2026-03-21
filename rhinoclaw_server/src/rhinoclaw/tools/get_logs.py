import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_logs(
    ctx: Context,
    count: int = 50
) -> str:
    """
    Get recent log entries from the Rhino MCP server.
    
    Parameters:
    - count: Number of log entries to retrieve (default: 50, max: 100)
    
    Returns:
    - List of recent log messages with timestamps
    
    Notes:
    - Useful for debugging when commands fail
    - Logs include timestamps in format [HH:mm:ss.fff]
    - Logs are stored in memory and cleared on Rhino restart
    """
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("get_logs", {
            "count": min(count, 100)
        })
        
        return json.dumps(ok(
            message=f"Retrieved {result.get('count', 0)} log entries",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error getting logs: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def clear_logs(ctx: Context) -> str:
    """
    Clear the Rhino MCP server log buffer.
    
    Returns:
    - Confirmation message
    """
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("clear_logs", {})
        
        return json.dumps(ok(
            message="Log buffer cleared",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error clearing logs: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
