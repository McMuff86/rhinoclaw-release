from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.responses import from_exception


@mcp.tool()
def create_text_dot(
    ctx: Context,
    text: str,
    location: List[float],
    name: Optional[str] = None,
    color: Optional[List[int]] = None,
) -> str:
    """
    Create a TEXT_DOT annotation at a location.

    Parameters:
    - text: Text content
    - location: [x, y, z] position
    - name: Optional name
    - color: Optional [r, g, b]
    """
    try:
        rhino = get_rhino_connection()
        params: Dict[str, Any] = {
            "type": "TEXT_DOT",
            "params": {"text": text, "location": location},
        }
        if name:
            params["name"] = name
        if color:
            params["color"] = color
        result = rhino.send_command("create_object", params)
        return f"Created TEXT_DOT: {result.get('name', 'unnamed')}"
    except Exception as e:
        logger.warning(f"Falling back to RhinoScript for text dot: {str(e)}")
        try:
            loc = "[" + ",".join([str(c) for c in location]) + "]"
            safe_text = (text or "").replace("\\", "\\\\").replace("\"", "\\\"")
            set_name = (name or "").replace("\\", "\\\\").replace("\"", "\\\"")
            set_color = None
            if color and len(color) == 3:
                set_color = "(" + ",".join([str(int(c)) for c in color]) + ")"
            code = (
                "import rhinoscriptsyntax as rs\n"
                "_id = rs.AddTextDot(\"" + safe_text + "\", " + loc + ")\n"
            )
            if name:
                code += "rs.ObjectName(_id, \"" + set_name + "\")\n"
            if set_color:
                code += "rs.ObjectColor(_id, " + set_color + ")\n"
            rhino.send_command("execute_rhinoscript_python_code", {"code": code})
            return name and ("Created TEXT_DOT: " + name) or "Created TEXT_DOT"
        except Exception as e2:
            logger.error(f"Error creating text dot via fallback: {str(e2)}")
            err = from_exception(e2, code="CREATE_TEXT_DOT_FALLBACK_ERROR")
            return f"Error creating text dot: {err['message']}"


