import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def find_objects(
    ctx: Context,
    layer: Optional[str] = None,
    layers: Optional[List[str]] = None,
    type: Optional[str] = None,
    types: Optional[List[str]] = None,
    name_contains: Optional[str] = None,
    name_regex: Optional[str] = None,
    min_volume: Optional[float] = None,
    max_volume: Optional[float] = None,
    min_x: Optional[float] = None,
    max_x: Optional[float] = None,
    min_y: Optional[float] = None,
    max_y: Optional[float] = None,
    min_z: Optional[float] = None,
    max_z: Optional[float] = None,
    selected: Optional[bool] = None,
    has_material: Optional[bool] = None,
    limit: int = 500,
) -> str:
    """Select document objects by attribute / geometry filter.

    Fast O(n) walk on the object table; cheap filters first (layer,
    type, name), expensive ones last (volume — only computed when
    bounds are given). Every parameter is optional; absent parameters
    mean "don't filter on this dimension".

    Parameters:
    - `layer` / `layers`: exact layer name match (single or list).
    - `type` / `types`: ObjectType name (Brep, Mesh, Curve, Surface,
      PointObject, InstanceReference, …).
    - `name_contains`: case-insensitive substring on object name.
    - `name_regex`: .NET regex against the object name.
    - `min_volume` / `max_volume`: only meaningful for closed solids
      (Breps with `IsSolid`, closed meshes). Non-volumetric objects
      are excluded when either bound is set.
    - `min_x` / `max_x` / …_z: half-open bounding-box-center filter.
      Object's bbox center must fall inside `[min_*, max_*]`.
    - `selected`: restrict to currently selected objects.
    - `has_material`: only objects with (or without) a material assigned.
    - `limit`: max number of results (default 500).

    Returns:
        {"success": true, "data": {
          "count": int,
          "scanned": int,
          "limit": int,
          "truncated": bool,
          "results": [{"id": "...", "name": "...", "layer": "...",
                       "type": "...", "center": [x,y,z], "volume": ...}, ...]
        }}

    Example:
        find_objects(layer="Walls", type="Brep", min_volume=0.5)
    """
    try:
        params: Dict[str, Any] = {"limit": limit}
        if layer is not None:          params["layer"] = layer
        if layers is not None:         params["layers"] = layers
        if type is not None:           params["type"] = type
        if types is not None:          params["types"] = types
        if name_contains is not None:  params["name_contains"] = name_contains
        if name_regex is not None:     params["name_regex"] = name_regex
        if min_volume is not None:     params["min_volume"] = min_volume
        if max_volume is not None:     params["max_volume"] = max_volume
        if min_x is not None:          params["min_x"] = min_x
        if max_x is not None:          params["max_x"] = max_x
        if min_y is not None:          params["min_y"] = min_y
        if max_y is not None:          params["max_y"] = max_y
        if min_z is not None:          params["min_z"] = min_z
        if max_z is not None:          params["max_z"] = max_z
        if selected is not None:       params["selected"] = selected
        if has_material is not None:   params["has_material"] = has_material

        rhino = get_rhino_connection()
        result = rhino.send_command("find_objects", params)
        return json.dumps(ok(
            message=f"Matched {result.get('count', 0)} of "
                    f"{result.get('scanned', 0)} object(s).",
            data=result,
        ))
    except Exception as e:
        logger.error(f"find_objects failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
