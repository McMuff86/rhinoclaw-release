"""Keep MCP discovery separate from the plugin's actual TCP registry."""
import hashlib
import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, mcp
from rhinoclaw.tools.find_gh_component import _catalog
from rhinoclaw.utils.gh_catalog import catalog_contract
from rhinoclaw.utils.responses import from_exception, ok


def catalog_freshness(catalog, runtime):
    contract = catalog_contract(catalog)
    guids = sorted(str(guid).lower() for guid in runtime["proxy_guids"])
    digest = hashlib.sha256("\n".join(guids).encode("utf-8")).hexdigest()
    same_guids = digest == contract["proxy_guid_sha256"] and len(guids) == contract["component_count"]
    same_version = runtime.get("runtime_identity", {}).get("rhino_version") == contract["source"]["rhino_version"]
    return {
        "status": "matching_proxy_inventory" if same_guids and same_version else "stale",
        "proxy_identity_match": same_guids, "rhino_version_match": same_version,
        "catalog_proxy_count": contract["component_count"], "runtime_proxy_count": len(guids),
        "catalog_source": contract["source"], "runtime_identity": runtime.get("runtime_identity"),
        "skipped_proxy_guids": contract["ports_skipped_guids"],
        "ports_verified": False,
        "authoring_policy": "Resolve every used GUID and keep the runtime component-contract gate; matching proxy IDs do not prove ports or plugin versions.",
        "refresh": "In a saved scratch Rhino only: uv run python scripts/generate_gh_catalog.py --reset. Known skipped proxies are carried forward. Restart the MCP server after publication.",
    }


@mcp.tool()
async def get_session_inventory(ctx: Context, include_grasshopper: bool = False) -> str:
    """Read separate live MCP/TCP registries and optionally GH catalog freshness.

    Lists the MCP server's schemas, not tools exposed by the calling agent.
    Name differences are diagnostic; composed MCP tools need not be TCP names.
    Optional GH inventory enumerates proxy IDs without CreateInstance, solving,
    loading plugins, refreshing the catalog or changing documents.
    """
    try:
        schemas = await mcp.list_tools()
        mcp_names = sorted(tool.name for tool in schemas)
        rhino = get_rhino_connection()
        tcp = rhino.send_command("list_commands", {})
        tcp_names = sorted(tcp["commands"])
        data = {
            "mcp_tools": mcp_names, "tcp_commands": tcp_names,
            "mcp_only_names": sorted(set(mcp_names) - set(tcp_names)),
            "tcp_only_names": sorted(set(tcp_names) - set(mcp_names)),
            "client_tool_exposure": "unknown; server registration is not client exposure",
            "scope": "separate_live_registries_not_a_one_to_one_mapping",
        }
        if include_grasshopper:
            data["grasshopper_catalog"] = catalog_freshness(_catalog(), rhino.send_command("get_gh_catalog_status", {}))
        return json.dumps(ok("Read live transport inventories", data=data))
    except Exception as exc:
        return json.dumps(from_exception(exc, code="SESSION_INVENTORY_ERROR"))
