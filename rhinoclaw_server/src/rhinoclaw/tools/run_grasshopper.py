import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def run_grasshopper(
    ctx: Context,
    file_path: str
) -> str:
    """
    Run a Grasshopper definition file using Rhino's Grasshopper Player.

    Parameters:
    - file_path: Full path to the .gh Grasshopper definition file to run

    Returns:
        {"ok": true, "message": "Ran Grasshopper definition", "data": {"file_path": "C:/path/to/file.gh"}}

    Notes:
    - Executes the Grasshopper definition using Rhino's GrasshopperPlayer command
    - The Grasshopper definition will process and create geometry in the active Rhino document
    - Any outputs from the Grasshopper definition will be baked to the Rhino document
    - Use this for automated Grasshopper processing without opening the Grasshopper interface
    """
    if not file_path:
        return json.dumps(from_exception(
            ValueError("file_path is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if not file_path.lower().endswith('.gh'):
        return json.dumps(from_exception(
            ValueError("file_path must be a .gh file"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("run_grasshopper", {
            "file_path": file_path
        })

        return json.dumps(ok(
            message=f"Ran Grasshopper definition: {file_path}",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error running Grasshopper definition: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))