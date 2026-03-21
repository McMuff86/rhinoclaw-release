from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp


@mcp.tool()
def create_material(ctx: Context, name: str, color: List[int], shine: Optional[float] = 0.5, material_type: Optional[str] = "custom", metallic: Optional[float] = 0.0, roughness: Optional[float] = 0.1) -> str:
    """Create a new Rhino render material.

    Parameters:
    - name: Name of the material
    - color: [r, g, b] color values (0-255)
    - shine: Shine value for custom materials (0.0-1.0), ignored for PBR
    - material_type: "custom" for legacy materials, "pbr" for physically based materials
    - metallic: Metallic value for PBR materials (0.0-1.0), ignored for custom
    - roughness: Roughness value for PBR materials (0.0-1.0), ignored for custom
    """
    try:
        rhino = get_rhino_connection()
        command_params = {
            "name": name,
            "color": color,
            "material_type": material_type,
            "shine": shine,
            "metallic": metallic,
            "roughness": roughness
        }
        result = rhino.send_command("create_material", command_params)
        return f"Created {material_type} material: {result['message']}"
    except Exception as e:
        logger.error(f"Error creating material: {str(e)}")
        return f"Error: {str(e)}"
