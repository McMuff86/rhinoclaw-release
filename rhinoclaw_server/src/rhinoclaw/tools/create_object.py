import json
from typing import Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

ObjectType = Literal["POINT", "LINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "CURVE", "BOX", "SPHERE", "CONE", "CYLINDER", "PIPE", "SURFACE"]

@mcp.tool()
def create_object(
    ctx: Context,
    type: ObjectType = "BOX",
    name: Optional[str] = None,
    color: Optional[List[int]] = None,
    layer: Optional[str] = None,
    layer_color: Optional[List[int]] = None,
    params: Optional[Dict[str, Any]] = None,
    translation: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
) -> str:
    """
    Create a new object in the Rhino document.
    
    Parameters:
    - type: Object type ("POINT", "LINE", "POLYLINE", "CIRCLE", "ARC", "ELLIPSE", "CURVE", "BOX", "SPHERE", "CONE", "CYLINDER", "PIPE", "SURFACE")
    - name: Optional name for the object
    - color: Optional [r, g, b] color values (0-255) for the object (overrides layer color)
    - layer: Optional layer name to assign the object to (creates layer if not exists)
    - layer_color: Optional [r, g, b] color for new layer (only used when creating new layer)
    - params: Type-specific parameters dictionary (see documentation for each type)
    - translation: Optional [x, y, z] translation vector
    - rotation: Optional [x, y, z] rotation in radians
    - scale: Optional [x, y, z] scale factors

    The params dictionary is type-specific.
    For POINT, the params dictionary should contain the following keys:
    - x: x coordinate of the point
    - y: y coordinate of the point
    - z: z coordinate of the point

    For LINE, the params dictionary should contain the following keys:
    - start: [x, y, z] start point of the line
    - end: [x, y, z] end point of the line

    For POLYLINE, the params dictionary should contain the following keys:
    - points: List of [x, y, z] points that define the polyline

    For CIRCLE, the params dictionary should contain the following keys:
    - center: [x, y, z] center point of the circle
    - radius: Radius of the circle

    For ARC, the params dictionary should contain the following keys:
    - center: [x, y, z] center point of the arc
    - radius: Radius of the arc
    - angle: Angle of the arc in degrees

    For ELLIPSE, the params dictionary should contain the following keys:
    - center: [x, y, z] center point of the ellipse
    - radius_x: Radius of the ellipse along X axis
    - radius_y: Radius of the ellipse along Y axis

    For CURVE, the params dictionary should contain the following keys:
    - points: List of [x, y, z] control points that define the curve
    - degree: Degree of the curve (default is 3, if user asked for smoother curve, degree can be higher)
    If the curve is closed, the first and last points should be the same.

    For BOX, the params dictionary should contain the following keys:
    - width: Width of the box along X axis of the object
    - length: Length of the box along Y axis of the object
    - height: Height of the box along Z axis of the object

    For SPHERE, the params dictionary should contain the following key:
    - radius: Radius of the sphere

    For CONE, the params dictionary should contain the following keys:
    - radius: Radius of the cone
    - height: Height of the cone
    - cap: Boolean to indicate if the cone should be capped at the base, default is True

    For CYLINDER, the params dictionary should contain the following keys:
    - radius: Radius of the cylinder
    - height: Height of the cylinder
    - cap: Boolean to indicate if the cylinder should be capped at the base, default is True

    For SURFACE, the params dictionary should contain the following keys:
    - count : [number, number] Array of two numbers defining number of points in the u,v directions
    - points: List of [x, y, z] points that define the surface
    - degree: [number, number] (optional) Degree of the surface (default is 3, if user asked for smoother surface, degree can be higher)
    - closed: [bool, bool] (optional) Two booleans defining if the surface is closed in the u,v directions
    
    Returns:
        {"ok": true, "message": "Created BOX object: Box_1", "data": {"name": "Box_1", "id": "guid-here", "type": "BOX"}}
    
    Examples of params:
    - POINT: {"x": 0, "y": 0, "z": 0}
    - LINE: {"start": [0, 0, 0], "end": [1, 1, 1]}
    - POLYLINE: {"points": [[0, 0, 0], [1, 1, 1], [2, 2, 2]]}
    - CIRCLE: {"center": [0, 0, 0], "radius": 1.0}
    - CURVE: {"points": [[0, 0, 0], [1, 1, 1], [2, 2, 2]], "degree": 3}
    - BOX: {"width": 1.0, "length": 1.0, "height": 1.0}
    - SPHERE: {"radius": 1.0}
    - CONE: {"radius": 1.0, "height": 1.0, "cap": true}
    - CYLINDER: {"radius": 1.0, "height": 1.0, "cap": true}
    - SURFACE: {"count": [3, 3], "points": [[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0], [0, 2, 0], [1, 2, 0], [2, 2, 0]], "degree": [3, 3], "closed": [false, false]}
    """
    try:
        # Get the global connection
        rhino = get_rhino_connection()

        command_params = {
            "type": type,
            "params": params if params is not None else {}
        }

        if translation is not None: command_params["translation"] = translation
        if rotation is not None: command_params["rotation"] = rotation
        if scale is not None: command_params["scale"] = scale

        if name: command_params["name"] = name
        if color: command_params["color"] = color
        if layer: command_params["layer"] = layer
        if layer_color: command_params["layer_color"] = layer_color

        # Create the object
        result = rhino.send_command("create_object", command_params)  
        
        return json.dumps(ok(
            message=f"Created {type} object: {result['name']}",
            data={"name": result['name'], "id": result.get('id'), "type": type}
        ))
    except Exception as e:
        logger.error(f"Error creating object: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.CREATE_OBJECT_ERROR))
 