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
        {"success": true, "message": "Opened file", "data": {"file_path": "C:/path/to/file.3dm"}}
    
    Notes:
    - Opens the file in the current Rhino instance
    - Refuses to replace a document with unsaved changes or an active undo record
    - Uses native open and verifies the active path, object IDs and units against the archive
    - Reports an already-open document separately from a reload from disk
    - Document opening is not reversible through Rhino Undo
    """
    if not file_path or not file_path.strip():
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
        
        if result.get("success") is False:
            response = from_exception(RuntimeError(result.get("message", "Open verification failed")),
                                      code=result.get("error_code", ErrorCode.RHINO_ERROR))
            response["data"] = result
            return json.dumps(response)
        return json.dumps(ok(
            message=result.get("message", f"Opened file: {file_path}"),
            data=result
        ))
    except Exception as e:
        logger.error(f"Error opening file: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
