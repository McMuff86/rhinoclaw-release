import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_object_properties(
    ctx: Context,
    object_id: Optional[str] = None,
    object_ids: Optional[List[str]] = None
) -> str:
    """
    Get geometric properties of objects including bounding box, area, volume, and centroid.

    Supports both single object and batch operations. Use `object_id` for a single object
    or `object_ids` for multiple objects.

    Parameters:
        object_id: GUID of a single object to query
        object_ids: List of GUIDs for batch operations

    Returns:
        For single object: Properties dict with bounding_box, area, volume, centroid, surface_area
        For batch: List of property dicts, one per object

    Properties returned:
        - bounding_box: { min: [x,y,z], max: [x,y,z], dimensions: [w,h,d] }
        - area: Surface area for surfaces/breps, None for curves/points
        - volume: Volume for closed solids, None for open geometry
        - centroid: Center of mass [x,y,z]
        - surface_area: Surface area for breps
        - is_solid: Whether the object is a closed solid
        - curve_length: Length for curves, None otherwise

    Example:
        get_object_properties(object_id="abc-123-...")
        get_object_properties(object_ids=["id1", "id2", "id3"])
    """
    if not object_id and not object_ids:
        return json.dumps(from_exception(
            ValueError("Either object_id or object_ids must be provided"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    try:
        rhino = get_rhino_connection()
        
        params = {}
        if object_id:
            params["object_id"] = object_id
        if object_ids:
            params["object_ids"] = object_ids
        
        result = rhino.send_command("get_object_properties", params)
        return json.dumps(ok(message="Object properties retrieved", data=result))
    except Exception as e:
        logger.error(f"Error getting object properties: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
