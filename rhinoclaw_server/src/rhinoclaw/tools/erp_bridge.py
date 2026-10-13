import json

from mcp.server.fastmcp import Context

from rhinoclaw import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok


@mcp.tool()
def erp_list_tools(ctx: Context) -> str:
    """List the ERP tools exposed by the RhinoERPBridge plugin (Borm-ERP/BOM integration:
    article search in the ERP master data, BOM collection from the Rhino document,
    BOM validation/doctor). Returns an MCP-style manifest — for each tool: name,
    description and inputSchema (JSON Schema of its arguments).

    Workflow: call this FIRST to discover the available ERP tools and their schemas,
    then execute one via erp_invoke. Requires the RhinoERPBridge plugin (>= 0.12.7)
    to be installed in Rhino.
    """
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("erp_list_tools")

        return json.dumps(ok(
            message="ERP tool manifest retrieved successfully",
            data=result
        ), indent=2)
    except Exception as e:
        logger.error(f"Error listing ERP tools: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_COMMAND_FAILED))


@mcp.tool()
def erp_invoke(ctx: Context, tool: str, args: str = "{}") -> str:
    """Invoke one ERP tool of the RhinoERPBridge plugin (see erp_list_tools for the
    manifest). All current tools are read-only.

    Parameters:
    - tool: tool name from the manifest, e.g. "erp_search_article",
      "erp_get_article", "erp_collect_bom", "erp_validate_bom", "erp_info"
    - args: JSON object string matching the tool's inputSchema,
      e.g. '{"query": "scharnier", "maxResults": 10}' — pass "{}" for tools
      without arguments.

    The result is the bridge's envelope: {"ok": true, "result": ...} on success,
    {"ok": false, "error": "..."} when the tool itself failed.
    """
    try:
        try:
            parsed_args = json.loads(args) if args else {}
        except json.JSONDecodeError as je:
            return json.dumps(error(
                f"args is not valid JSON: {je}",
                code=ErrorCode.INVALID_PARAMS
            ))

        rhino = get_rhino_connection()
        result = rhino.send_command("erp_invoke", {"tool": tool, "args": parsed_args})

        return json.dumps(ok(
            message=f"ERP tool '{tool}' executed",
            data=result
        ), indent=2)
    except Exception as e:
        logger.error(f"Error invoking ERP tool '{tool}': {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_COMMAND_FAILED))
