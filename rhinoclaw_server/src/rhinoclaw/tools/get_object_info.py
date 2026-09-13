import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_object_info(ctx: Context, id: Optional[str] = None, name: Optional[str] = None) -> str:
    """Read one object's exact identity, geometry and attributes.

    Provide id or name; id takes precedence. Returns JSON success/message/data;
    the former raw object record is now under data, including id, name, type,
    layer, color, bounding_box, geometry and attributes when available.
    """
    if not id and not name:
        return json.dumps(from_exception(ValueError("Provide id or name"), code=ErrorCode.INVALID_PARAMS))
    try:
        result = get_rhino_connection().send_command("get_object_info", {"id": id, "name": name})
        if result.get("success") is False:
            response = from_exception(RuntimeError(result.get("message", "Object read failed")), code=ErrorCode.RHINO_ERROR)
            response["data"] = result
            return json.dumps(response)
        return json.dumps(ok("Read object information", data=result))
    except Exception as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
