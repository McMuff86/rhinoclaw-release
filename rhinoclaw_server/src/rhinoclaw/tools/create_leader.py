from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.responses import from_exception


@mcp.tool()
def create_leader(
    ctx: Context,
    points: List[List[float]],
    text: Optional[str] = None,
    name: Optional[str] = None,
    color: Optional[List[int]] = None,
) -> str:
    """
    Create a Leader annotation.

    Parameters:
    - points: List of [x, y, z] points (at least two)
    - text: Optional leader text
    - name: Optional name for the object
    - color: Optional [r, g, b] color values (0-255)

    Returns:
    A message indicating the created leader name.
    """
    try:
        rhino = get_rhino_connection()
        params: Dict[str, Any] = {
            "type": "LEADER",
            "params": {
                "points": points,
                "text": text or "",
            },
        }
        if name:
            params["name"] = name
        if color:
            params["color"] = color

        result = rhino.send_command("create_object", params)
        return f"Created LEADER: {result.get('name', 'unnamed')}"
    except Exception as e:
        logger.warning(f"Falling back to RhinoScript for leader: {str(e)}")
        try:
            # IronPython 2.7 compatible script (no f-strings)
            pts_list = ",".join(["[" + ",".join([str(c) for c in p]) + "]" for p in points])
            txt = (text or "").replace("\\", "\\\\").replace("\"", "\\\"")
            set_name = (name or "").replace("\\", "\\\\").replace("\"", "\\\"")
            set_color = None
            if color and len(color) == 3:
                set_color = "(" + ",".join([str(int(c)) for c in color]) + ")"

            code = (
                "import rhinoscriptsyntax as rs\n"
                "pts = [" + pts_list + "]\n"
                "_id = rs.AddLeader(pts, None, \"" + txt + "\")\n"
            )
            if name:
                code += "rs.ObjectName(_id, \"" + set_name + "\")\n"
            if set_color:
                code += "rs.ObjectColor(_id, " + set_color + ")\n"
            rhino.send_command("execute_rhinoscript_python_code", {"code": code})
            return name and ("Created LEADER: " + name) or "Created LEADER"
        except Exception as e2:
            logger.error(f"Error creating leader via fallback: {str(e2)}")
            err = from_exception(e2, code="CREATE_LEADER_FALLBACK_ERROR")
            return f"Error creating leader: {err['message']}"


