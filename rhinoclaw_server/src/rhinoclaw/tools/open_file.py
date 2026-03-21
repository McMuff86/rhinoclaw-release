import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def open_file(
    ctx: Context,
    file_path: str
) -> str:
    """
    Open a Rhino 3DM file.
    
    Parameters:
    - file_path: Full path to the .3dm file to open
    
    Returns:
        {"ok": true, "message": "Opened file", "data": {"file_path": "C:/path/to/file.3dm"}}
    
    Notes:
    - Opens the file in the current Rhino instance
    - Any unsaved changes in the current document will be lost
    - Use save_file first if you need to preserve current work
    """
    if not file_path:
        return json.dumps(from_exception(
            ValueError("file_path is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if not file_path.lower().endswith('.3dm'):
        return json.dumps(from_exception(
            ValueError("file_path must be a .3dm file"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("open_file", {
            "file_path": file_path
        })
        
        return json.dumps(ok(
            message=f"Opened file: {file_path}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error opening file: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
