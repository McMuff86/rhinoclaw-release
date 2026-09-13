import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rhinoclaw.tools.session_inventory import catalog_freshness, get_session_inventory


def script_module(name):
    if name == "session_preflight" and sys.version_info < (3, 11):
        pytest.skip("The standalone TOML MCP fallback requires Python 3.11+")
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("change", ["none", "version", "same_count_other_guid", "count"])
def test_freshness_checks_exact_proxy_inventory_and_version(change):
    catalog = {"meta": {"rhino_version": "9.1"}, "components": [{"guid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "in": []}]}
    runtime = {"proxy_guids": [catalog["components"][0]["guid"]], "runtime_identity": {"rhino_version": "9.1"}}
    if change == "version": runtime["runtime_identity"]["rhino_version"] = "9.2"
    if change == "same_count_other_guid": runtime["proxy_guids"] = ["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]
    if change == "count": runtime["proxy_guids"] = []
    result = catalog_freshness(catalog, runtime)
    assert (result["status"] == "stale") is (change != "none")
    assert result["ports_verified"] is False


async def test_transport_names_are_kept_separate():
    with patch("rhinoclaw.tools.session_inventory.mcp.list_tools", new=AsyncMock(return_value=[SimpleNamespace(name="mcp_composition")])), \
         patch("rhinoclaw.tools.session_inventory.get_rhino_connection") as connect:
        connect.return_value.send_command.return_value = {"commands": ["native_command"]}
        result = json.loads(await get_session_inventory(None))
    assert result["success"] is True
    assert result["data"]["mcp_only_names"] == ["mcp_composition"]
    assert result["data"]["tcp_only_names"] == ["native_command"]
    assert result["data"]["client_tool_exposure"].startswith("unknown")
    connect.return_value.send_command.assert_called_once_with("list_commands", {})


def test_stdio_launch_preserves_config_env_and_uses_writable_paths(tmp_path):
    client = script_module("session_preflight")
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.rhino]\ncommand="configured.exe"\nargs=["run", "rhinoclaw"]\n[mcp_servers.rhino.env]\nRHINOCLAW_AUTH_TOKEN="private-test-token"\nCUSTOM="preserved"\n', encoding="utf-8")
    output = tmp_path / "evidence"
    result = client.launch_settings(config, "rhino", output)
    assert result.command == "configured.exe" and result.args == ["run", "rhinoclaw"]
    assert result.env["CUSTOM"] == "preserved" and result.env["RHINOCLAW_AUTH_TOKEN"] == "private-test-token"
    assert Path(result.env["UV_CACHE_DIR"]).is_dir()
    assert Path(result.env["RHINOCLAW_LOG_DIR"]).parent == output


async def test_mcp_discovery_follows_pagination_and_rejects_loop():
    client = script_module("session_preflight")
    session = SimpleNamespace(list_tools=AsyncMock(side_effect=[SimpleNamespace(tools=["a"], nextCursor="next"), SimpleNamespace(tools=["b"], nextCursor=None)]))
    assert await client.list_all_tools(session) == ["a", "b"]
    session.list_tools = AsyncMock(return_value=SimpleNamespace(tools=[], nextCursor="same"))
    with pytest.raises(RuntimeError, match="cursor"):
        await client.list_all_tools(session)


async def test_startup_failure_is_not_misreported_as_tcp_or_exposure(tmp_path):
    client = script_module("session_preflight")
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.rhinoclaw]\ncommand="missing"\n[mcp_servers.rhinoclaw.env]\nRHINOCLAW_AUTH_TOKEN="private-test-token"\n', encoding="utf-8")
    args = SimpleNamespace(output=tmp_path / "out", config=config, server="rhinoclaw", client_tools="unavailable", timeout=2, call=None)
    with patch.object(client, "stdio_client", side_effect=RuntimeError("Cannot start private-test-token")):
        assert await client.run(args) == 2
    raw = (args.output / "preflight.json").read_text()
    assert "private-test-token" not in raw
    report = json.loads(raw)
    assert report["mcp_startup"] == "initializing" and report["calls"] == []
    assert report["client_exposure_cause"] == "not established by this fallback"


def test_refresh_carries_known_hang_exclusions_after_reset(tmp_path):
    generator = script_module("generate_gh_catalog")
    catalog = tmp_path / "catalog.json"
    guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    catalog.write_text(json.dumps({"meta": {}, "components": [{"guid": guid, "ports_skipped": "known hang"}]}))
    assert generator._known_skipped_guids(catalog, tmp_path / "missing") == {guid}


def test_unknown_ui_state_never_becomes_ready():
    from rhinoclaw.tools.check_setup import rhinoclaw_doctor
    with patch("rhinoclaw.tools.check_setup.get_rhino_connection") as connect, \
         patch("rhinoclaw.tools.check_setup.get_ui_state", return_value='{"success":false,"message":"probe failed"}'):
        connect.return_value.send_command.return_value = {"plugin_version": "0.7.14.0"}
        data = json.loads(rhinoclaw_doctor(None))["data"]
    assert not data["ready"]
    assert next(check for check in data["checks"] if check["check"] == "ui_state")["status"] == "FAIL"
