import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def copy_object(
    ctx: Context,
    object_id: str,
    translation: Optional[List[float]] = None,
    count: int = 1
) -> str:
    """
    Copy an object with optional translation.
    
    Parameters:
    - object_id: GUID of the object to copy
    - translation: Optional [x, y, z] translation vector for each copy (default: [0, 0, 0])
    - count: Number of copies to make (default: 1)
    
    Returns:
    - List of new object GUIDs
    
    Notes:
    - If translation is provided and count > 1, each copy is translated incrementally
      (first copy at 1x translation, second at 2x, etc.)
    """
    # Validate parameters before connecting
    if not object_id:
        return json.dumps(from_exception(
            ValueError("object_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    if count < 1:
        return json.dumps(from_exception(
            ValueError("count must be at least 1"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        result = rhino.send_command("copy_object", {
            "object_id": object_id,
            "translation": translation or [0, 0, 0],
            "count": count
        })
        
        return json.dumps(ok(
            message=f"Created {count} copy/copies",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error copying object: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
