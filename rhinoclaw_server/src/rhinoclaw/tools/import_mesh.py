import json
from typing import Literal

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

MeshFormat = Literal["OBJ", "STL", "3MF", "PLY", "OFF", "3DS", "FBX"]

@mcp.tool()
def import_mesh(
    ctx: Context,
    file_path: str,
    format: MeshFormat = None,
    import_mode: Literal["merge", "replace"] = "merge"
) -> str:
    """
    Import mesh geometry from external file formats.

    Parameters:
    - file_path: Full path to the mesh file to import
    - format: Mesh file format (auto-detected from extension if not specified)
    - import_mode: Whether to merge with existing document ("merge") or replace current document ("replace")

    Returns:
    JSON response with import information

    Examples:
    - import_mesh(file_path="C:/models/cube.obj") - Import OBJ file
    - import_mesh(file_path="C:/models/part.stl", format="STL") - Import STL file
    - import_mesh(file_path="C:/models/assembly.3mf", import_mode="replace") - Replace document with 3MF
    """
    # Validate parameters before connecting
    if not file_path:
        return json.dumps(from_exception(
            ValueError("file_path is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    # Auto-detect format from extension if not specified
    if not format:
        import os
        _, ext = os.path.splitext(file_path.lower())
        format_map = {
            '.obj': 'OBJ',
            '.stl': 'STL',
            '.3mf': '3MF',
            '.ply': 'PLY',
            '.off': 'OFF',
            '.3ds': '3DS',
            '.fbx': 'FBX'
        }
        format = format_map.get(ext)
        if not format:
            return json.dumps(from_exception(
                ValueError(f"Unsupported file extension: {ext}. Supported: {list(format_map.keys())}"),
                code=ErrorCode.INVALID_PARAMS
            ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("import_mesh", {
            "file_path": file_path,
            "format": format,
            "import_mode": import_mode
        })

        return json.dumps(ok(
            message=f"Imported {format} mesh file",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error importing mesh: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))