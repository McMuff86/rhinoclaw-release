import json
from typing import List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

MeshDensity = Literal["coarse", "normal", "fine", "extra_fine"]
MeshQuality = Literal["fast", "normal", "accurate"]

@mcp.tool()
def mesh_from_brep(
    ctx: Context,
    object_ids: List[str],
    density: MeshDensity = "normal",
    quality: MeshQuality = "normal",
    max_edge_length: Optional[float] = None,
    min_edge_length: Optional[float] = None
) -> str:
    """
    Convert Brep (solid) geometry to mesh representation.

    Parameters:
    - object_ids: List of object IDs to convert to mesh
    - density: Mesh density preset ("coarse", "normal", "fine", "extra_fine")
    - quality: Mesh quality preset ("fast", "normal", "accurate")
    - max_edge_length: Maximum edge length for mesh faces (optional)
    - min_edge_length: Minimum edge length for mesh faces (optional)

    Returns:
    JSON response with mesh conversion information

    Examples:
    - mesh_from_brep(object_ids=["brep1", "brep2"]) - Convert Breps to normal density meshes
    - mesh_from_brep(object_ids=["solid1"], density="fine", quality="accurate") - High quality mesh
    - mesh_from_brep(object_ids=["obj1"], max_edge_length=0.1) - Custom edge length constraint
    """
    # Validate parameters before connecting
    if not object_ids or len(object_ids) == 0:
        return json.dumps(from_exception(
            ValueError("At least one object_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("mesh_from_brep", {
            "object_ids": object_ids,
            "density": density,
            "quality": quality,
            "max_edge_length": max_edge_length,
            "min_edge_length": min_edge_length
        })

        return json.dumps(ok(
            message=f"Converted {len(object_ids)} Brep objects to mesh",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error converting Brep to mesh: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))