import json

from mcp.server.fastmcp import Context

from rhinoclaw import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_document_info(ctx: Context) -> str:
    """Get detailed information about the current Rhino document"""
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("get_document_info")
        
        return json.dumps(ok(
            message="Document info retrieved successfully",
            data=result
        ), indent=2)
    except Exception as e:
        logger.error(f"Error getting document info from Rhino: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.DOC_INFO_ERROR))