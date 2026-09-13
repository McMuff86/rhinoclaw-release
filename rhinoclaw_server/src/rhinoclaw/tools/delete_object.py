import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def delete_object(ctx: Context, id: Optional[str] = None, name: Optional[str] = None, all: Optional[bool] = None) -> str:
    """Delete by exact id or name; all=True explicitly targets every active object.

    Returns JSON success/message/data. data retains native deleted IDs and any
    partial outcome. A successful transport alone does not establish deletion.
    """
    if not id and not name and all is not True:
        return json.dumps(from_exception(ValueError("Provide id, name or all=True"), code=ErrorCode.INVALID_PARAMS))
    try:
        params = {key: value for key, value in {"id": id, "name": name, "all": all}.items() if value is not None}
        result = get_rhino_connection().send_command("delete_object", params)
        if result.get("success") is False or result.get("deleted") is not True:
            response = from_exception(RuntimeError(result.get("message", "Deletion was not confirmed")),
                                      code=result.get("error_code", ErrorCode.RHINO_ERROR))
            response["data"] = result
            return json.dumps(response)
        return json.dumps(ok("Deleted requested object(s)", data=result))
    except Exception as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
