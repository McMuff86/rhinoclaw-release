import json
from typing import List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

MeshFormat = Literal["OBJ", "STL", "3MF", "PLY", "OFF", "3DS", "FBX"]

@mcp.tool()
def export_mesh(
    ctx: Context,
    file_path: str,
    format: MeshFormat,
    object_ids: Optional[List[str]] = None,
    mesh_options: Optional[dict] = None
) -> str:
    """
    Export mesh geometry to external file formats.

    Parameters:
    - file_path: Full path where to save the mesh file
    - format: Mesh file format to export
    - object_ids: Optional list of specific object IDs to export (exports all if not specified)
    - mesh_options: Optional format-specific options (density, quality, etc.)

    Returns:
    JSON response with export information

    Examples:
    - export_mesh(file_path="C:/export/model.obj", format="OBJ") - Export all objects as OBJ
    - export_mesh(file_path="C:/export/part.stl", format="STL", object_ids=["obj1", "obj2"]) - Export specific objects as STL
    """
    # Validate parameters before connecting
    if not file_path:
        return json.dumps(from_exception(
            ValueError("file_path is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if not format:
        return json.dumps(from_exception(
            ValueError("format is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    # Validate format
    supported_formats = ["OBJ", "STL", "3MF", "PLY", "OFF", "3DS", "FBX"]
    if format.upper() not in supported_formats:
        return json.dumps(from_exception(
            ValueError(f"Unsupported format: {format}. Supported: {supported_formats}"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("export_mesh", {
            "file_path": file_path,
            "format": format.upper(),
            "object_ids": object_ids,
            "mesh_options": mesh_options
        })

        return json.dumps(ok(
            message=f"Exported mesh to {format.upper()} format",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error exporting mesh: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))