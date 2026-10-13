from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, from_result
import json
from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp


@mcp.tool()
def assign_material_to_layer(ctx: Context, layer_name: str, material_id: str) -> str:
    """Assign a render material to a specific layer."""
    if not layer_name:
        return json.dumps(from_exception(ValueError("layer_name is required"), code=ErrorCode.INVALID_PARAMS))
    if not material_id:
        return json.dumps(from_exception(ValueError("material_id is required"), code=ErrorCode.INVALID_PARAMS))

    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("assign_material_to_layer", {"layer_name": layer_name, "material_id": material_id})
        return json.dumps(from_result(result, message="Material assigned"))
    except Exception as e:
        logger.error(f"Error assigning material: {str(e)}")
        return json.dumps(from_exception(e))
