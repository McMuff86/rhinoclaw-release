import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.interaction_logger import interaction_logger
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_session_stats(ctx: Context) -> str:
    """
    Get statistics for the current MCP session.
    
    Returns interaction logging statistics including:
    - Session ID
    - Total tool calls
    - Success/error counts and rate
    - Tool usage breakdown
    
    Returns:
        {"ok": true, "data": {"session_id": "abc123", "total_calls": 15, "success_rate": 93.3, ...}}
    
    Use this to monitor agent performance and identify problematic tool patterns.
    """
    try:
        stats = interaction_logger.get_session_stats()
        
        return json.dumps(ok(
            message=f"Session {stats.get('session_id', 'unknown')}: {stats.get('total_calls', 0)} calls, {stats.get('success_rate', 0)}% success",
            data=stats
        ))
    except Exception as e:
        logger.error(f"Error getting session stats: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def new_session(ctx: Context) -> str:
    """
    Start a new interaction logging session.
    
    Creates a new session ID for grouping related tool calls.
    Use when starting a new modeling task or workflow.
    
    Returns:
        {"ok": true, "data": {"session_id": "abc123"}}
    """
    try:
        session_id = interaction_logger.new_session()
        
        return json.dumps(ok(
            message=f"New session started: {session_id}",
            data={"session_id": session_id}
        ))
    except Exception as e:
        logger.error(f"Error creating new session: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def set_logging_enabled(ctx: Context, enabled: bool) -> str:
    """
    Enable or disable interaction logging.
    
    Parameters:
    - enabled: True to enable logging, False to disable
    
    Returns:
        {"ok": true, "message": "Logging enabled"}
    
    Use to temporarily disable logging for sensitive operations.
    """
    try:
        interaction_logger.enabled = enabled
        
        return json.dumps(ok(
            message=f"Interaction logging {'enabled' if enabled else 'disabled'}",
            data={"enabled": enabled}
        ))
    except Exception as e:
        logger.error(f"Error setting logging state: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
