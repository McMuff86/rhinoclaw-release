import json
from typing import Any, Dict, List, Literal

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

ObjectType = Literal["POINT", "LINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "CURVE", "BOX", "SPHERE", "CONE", "CYLINDER", "PIPE", "SURFACE"]

@mcp.tool()
def create_objects(
    ctx: Context,
    objects: List[Dict[str, Any]]
) -> str:
    """
    Create multiple objects at once in the Rhino document.
    
    Parameters:
    - objects: A list of dictionaries, each containing the parameters for a single object

    Each object dictionary MUST contain:
    - type: Object type - one of: "POINT", "LINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "CURVE", "BOX", "SPHERE", "CONE", "CYLINDER", "PIPE", "SURFACE"
    - name: Name for the object (required for batch creation)
    - params: Type-specific parameters dictionary (see create_object for each type)
    
    Optional fields:
    - color: [r, g, b] color values (0-255) for the object
    - translation: [x, y, z] translation vector
    - rotation: [x, y, z] rotation in radians
    - scale: [x, y, z] scale factors

    Returns:
        {"ok": true, "message": "Created 3 objects", "data": {"count": 3, "objects": [...]}}
    
    Examples of params:
    [
        {
            "type": "POINT",
            "name": "Point 1",
            "params": {"x": 0, "y": 0, "z": 0}
        },
        {
            "type": "LINE",
            "name": "Line 1",
            "params": {"start": [0, 0, 0], "end": [1, 1, 1]}
        },
        {
            "type": "POLYLINE",
            "name": "Polyline 1",
            "params": {"points": [[0, 0, 0], [1, 1, 1], [2, 2, 2]]}
        },
        {
            "type": "CURVE",
            "name": "Curve 1",
            "params": {"points": [[0, 0, 0], [1, 1, 1], [2, 2, 2]], "degree": 3}
        },
        {
            "type": "BOX",
            "name": "Box 1",
            "color": [255, 0, 0],
            "params": {"width": 1.0, "length": 1.0, "height": 1.0},
            "translation": [0, 0, 0],
            "rotation": [0, 0, 0],
            "scale": [1, 1, 1]
        },
        {
            "type": "SPHERE",
            "name": "Sphere 1",
            "color": [0, 255, 0],
            "params": {"radius": 1.0},
            "translation": [0, 0, 0],
            "rotation": [0, 0, 0],
            "scale": [1, 1, 1]
        }
    ]
    """
    try:
        rhino = get_rhino_connection()
        command_params = {}
        for obj in objects:
            command_params[obj["name"]] = obj
        result = rhino.send_command("create_objects", command_params)
        
        return json.dumps(ok(
            message=f"Created {len(result)} objects",
            data={"count": len(result), "objects": result}
        ))
    except Exception as e:
        logger.error(f"Error creating objects: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.CREATE_OBJECT_ERROR))

