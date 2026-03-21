from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.responses import from_exception


@mcp.tool()
def create_text(
    ctx: Context,
    text: str,
    location: List[float],
    height: float = 1.0,
    name: Optional[str] = None,
    color: Optional[List[int]] = None,
) -> str:
    """
    Create a TEXT annotation at a location.

    Parameters:
    - text: Text content
    - location: [x, y, z] insertion point
    - height: Text height (model units)
    - name: Optional name
    - color: Optional [r, g, b]
    """
    try:
        rhino = get_rhino_connection()
        params: Dict[str, Any] = {
            "type": "TEXT",
            "params": {"text": text, "location": location, "height": height},
        }
        if name:
            params["name"] = name
        if color:
            params["color"] = color
        result = rhino.send_command("create_object", params)
        return f"Created TEXT: {result.get('name', 'unnamed')}"
    except Exception as e:
        logger.warning(f"Falling back to RhinoScript for text: {str(e)}")
        try:
            # IronPython 2.7 compatible, set optional name/color
            loc = "[" + ",".join([str(c) for c in location]) + "]"
            safe_text = (text or "").replace("\\", "\\\\").replace("\"", "\\\"")
            set_name = (name or "").replace("\\", "\\\\").replace("\"", "\\\"")
            set_color = None
            if color and len(color) == 3:
                set_color = "(" + ",".join([str(int(c)) for c in color]) + ")"
            code = (
                "import rhinoscriptsyntax as rs\n"
                "_id = rs.AddText(\"" + safe_text + "\", " + loc + ", height=" + str(height) + ")\n"
            )
            if name:
                code += "rs.ObjectName(_id, \"" + set_name + "\")\n"
            if set_color:
                code += "rs.ObjectColor(_id, " + set_color + ")\n"
            rhino.send_command("execute_rhinoscript_python_code", {"code": code})
            return name and ("Created TEXT: " + name) or "Created TEXT"
        except Exception as e2:
            logger.error(f"Error creating text via fallback: {str(e2)}")
            err = from_exception(e2, code="CREATE_TEXT_FALLBACK_ERROR")
            return f"Error creating text: {err['message']}"


