from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp


@mcp.tool()
def assign_material_to_layer(ctx: Context, layer_name: str, material_id: str) -> str:
    """Assign a render material to a specific layer."""
    if not layer_name:
        return "Error: layer_name is required"
    if not material_id:
        return "Error: material_id is required"
    
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("assign_material_to_layer", {"layer_name": layer_name, "material_id": material_id})
        return f"Assigned material: {result['message']}"
    except Exception as e:
        logger.error(f"Error assigning material: {str(e)}")
        return f"Error: {str(e)}"
