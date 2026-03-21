import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def save_file(
    ctx: Context,
    file_path: Optional[str] = None
) -> str:
    """
    Save the current Rhino document.
    
    Parameters:
    - file_path: Optional path to save as. If not provided, saves to current location.
    
    Returns:
        {"ok": true, "message": "Saved file", "data": {"file_path": "C:/path/to/file.3dm"}}
    
    Notes:
    - If file_path is provided, performs "Save As" to new location
    - If file_path is None and document was never saved, returns an error
    - File path must end with .3dm
    """
    if file_path and not file_path.lower().endswith('.3dm'):
        return json.dumps(from_exception(
            ValueError("file_path must be a .3dm file"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        params = {}
        if file_path:
            params["file_path"] = file_path
        
        result = rhino.send_command("save_file", params)
        
        saved_path = result.get("file_path", file_path or "current document")
        return json.dumps(ok(
            message=f"Saved file: {saved_path}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error saving file: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
