import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_command_history(
    ctx: Context,
    lines: Optional[int] = 20
) -> str:
    """
    Get recent Rhino command history and current prompt status.
    
    Use this tool to see what Rhino is currently doing or asking for.
    Essential for debugging when commands seem stuck or unresponsive.
    
    Parameters:
    - lines: Number of recent command history lines to return (default: 20)
    
    Returns:
        {
            "ok": true,
            "data": {
                "command_prompt": "Select objects:",
                "history": ["Command: Box", "Width: 10", ...],
                "history_count": 20
            }
        }
    
    Notes:
    - command_prompt shows what Rhino is currently asking for
    - history shows recent command line output
    - Use this before/after commands to understand Rhino's state
    """
    lines = lines if lines is not None else 20
    lines = max(1, min(lines, 100))  # Clamp to 1-100
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("get_command_history", {
            "lines": lines
        })
        
        return json.dumps(ok(
            message="Command history retrieved",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error getting command history: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
