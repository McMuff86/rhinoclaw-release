import json
from typing import List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

ExportFormat = Literal["STEP", "IGES", "DWG", "DXF", "OBJ", "STL", "3MF", "FBX", "DAE"]


@mcp.tool()
def export_file(
    ctx: Context,
    file_path: str,
    export_format: Optional[ExportFormat] = None,
    object_ids: Optional[List[str]] = None
) -> str:
    """
    Export Rhino geometry to various file formats.
    
    Parameters:
    - file_path: Full path for the exported file (extension determines format if not specified)
    - export_format: Optional format override: STEP, IGES, DWG, DXF, OBJ, STL, 3MF, FBX, DAE
    - object_ids: Optional list of object GUIDs to export. If None, exports all objects.
    
    Returns:
        {"ok": true, "message": "Exported to STEP", "data": {"file_path": "...", "format": "STEP", "object_count": 5}}
    
    Supported formats:
    - STEP (.stp, .step): CAD interchange format
    - IGES (.igs, .iges): Legacy CAD format
    - DWG (.dwg): AutoCAD format
    - DXF (.dxf): AutoCAD exchange format
    - OBJ (.obj): Wavefront mesh format
    - STL (.stl): 3D printing format
    - 3MF (.3mf): Modern 3D printing format
    - FBX (.fbx): Autodesk exchange format
    - DAE (.dae): Collada format
    
    Notes:
    - If object_ids is empty, exports all visible geometry
    - Some formats only support meshes (STL, OBJ) - Breps will be meshed
    """
    if not file_path:
        return json.dumps(from_exception(
            ValueError("file_path is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    
    # Determine format from extension if not specified
    detected_format = export_format
    if not detected_format:
        ext = file_path.lower().split('.')[-1] if '.' in file_path else ''
        format_map = {
            'stp': 'STEP', 'step': 'STEP',
            'igs': 'IGES', 'iges': 'IGES',
            'dwg': 'DWG',
            'dxf': 'DXF',
            'obj': 'OBJ',
            'stl': 'STL',
            '3mf': '3MF',
            'fbx': 'FBX',
            'dae': 'DAE'
        }
        detected_format = format_map.get(ext)
        if not detected_format:
            return json.dumps(from_exception(
                ValueError(f"Cannot determine format from extension '.{ext}'. Specify export_format explicitly."),
                code=ErrorCode.INVALID_PARAMS
            ))
    
    try:
        rhino = get_rhino_connection()
        
        params = {
            "file_path": file_path,
            "format": detected_format.upper()
        }
        if object_ids:
            params["object_ids"] = object_ids
        
        result = rhino.send_command("export_file", params)
        
        return json.dumps(ok(
            message=f"Exported to {detected_format}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error exporting file: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
