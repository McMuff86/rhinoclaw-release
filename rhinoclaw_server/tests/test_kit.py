"""Offline tests for kit discovery, validation, and MCP wrappers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.config import reload_settings
from rhinoclaw.utils.kits import (
    RESULT_PREFIX,
    KitError,
    build_invoke_source,
    discover_kits,
    load_manifest,
    parse_invoke_output,
    resolve_entry,
)

LAYOUTTOOLS_KIT = (
    Path(__file__).resolve().parents[3] / "RhinoLayoutTools" / "rhinoclaw-kit.json"
)


@pytest.mark.parametrize("name", ["kit_list", "kit_describe", "kit_invoke"])
def test_registered_kit_tools_inject_context(name):
    from rhinoclaw.server import mcp

    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None
    assert "ctx" not in tool.parameters.get("properties", {})
    assert "ctx" not in tool.parameters.get("required", [])

MINIMAL_KIT = {
    "schema": "rhinoclaw-kit/1",
    "id": "demo_kit",
    "title": "Demo",
    "version": "0.1.0",
    "engine": "python3",
    "actions": [
        {
            "name": "hello",
            "alias": "Hello",
            "status": "callable",
            "entry": "scripts/hello.py",
            "invoke": "run",
            "summary": "Say hello",
            "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
        {
            "name": "clicky",
            "alias": "Clicky",
            "status": "interactive_only",
            "entry": "scripts/clicky.py",
            "summary": "Needs a pick",
        },
    ],
}


@pytest.fixture
def kit_dir(tmp_path, monkeypatch):
    root = tmp_path / "demo_kit"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "hello.py").write_text("def run(name='world'):\n    return {'ok': True}\n", encoding="utf-8")
    (root / "rhinoclaw-kit.json").write_text(json.dumps(MINIMAL_KIT), encoding="utf-8")
    monkeypatch.setenv("RHINOCLAW_KITS", str(root))
    reload_settings()
    yield root
    monkeypatch.undo()
    reload_settings()


class TestManifest:
    def test_load_minimal(self, kit_dir):
        kit = load_manifest(kit_dir / "rhinoclaw-kit.json")
        assert kit.id == "demo_kit"
        assert kit.action("hello").status == "callable"
        assert kit.action("clicky").status == "interactive_only"
        assert resolve_entry(kit, kit.action("hello")).name == "hello.py"

    def test_rejects_unknown_schema(self, tmp_path):
        path = tmp_path / "rhinoclaw-kit.json"
        path.write_text(json.dumps({**MINIMAL_KIT, "schema": "nope/1"}), encoding="utf-8")
        with pytest.raises(KitError, match="unsupported schema"):
            load_manifest(path)

    def test_rejects_path_escape(self, kit_dir):
        kit = load_manifest(kit_dir / "rhinoclaw-kit.json")
        bad = kit.action("hello")
        from dataclasses import replace

        escaped = replace(bad, entry="../secret.py")
        with pytest.raises(KitError, match="relative path"):
            resolve_entry(kit, escaped)

    def test_callable_requires_invoke(self, tmp_path):
        raw = json.loads(json.dumps(MINIMAL_KIT))
        del raw["actions"][0]["invoke"]
        path = tmp_path / "rhinoclaw-kit.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(KitError, match="invoke"):
            load_manifest(path)


class TestDiscover:
    def test_finds_explicit_kit(self, kit_dir):
        kits, errors = discover_kits()
        assert errors == []
        assert [k.id for k in kits] == ["demo_kit"]

    def test_scan_root_one_level(self, tmp_path, monkeypatch):
        root = tmp_path / "repos"
        kit = root / "other"
        kit.mkdir(parents=True)
        (kit / "scripts").mkdir()
        (kit / "scripts" / "hello.py").write_text("def run():\n    return {}\n", encoding="utf-8")
        (kit / "rhinoclaw-kit.json").write_text(json.dumps(MINIMAL_KIT), encoding="utf-8")
        monkeypatch.delenv("RHINOCLAW_KITS", raising=False)
        monkeypatch.setenv("RHINOCLAW_KITS_ROOT", str(root))
        # Unit fixture must not discover the developer's unrelated repositories.
        monkeypatch.setattr("rhinoclaw.utils.kits.default_scan_roots", lambda: [])
        reload_settings()
        try:
            kits, errors = discover_kits()
            assert errors == []
            assert any(k.id == "demo_kit" for k in kits)
        finally:
            monkeypatch.undo()
            reload_settings()


class TestInvokeSource:
    def test_embeds_args_as_json(self, kit_dir):
        source = build_invoke_source(kit_dir / "scripts" / "hello.py", "run", {"name": "Adi"})
        assert "importlib.util" in source
        assert "Adi" in source
        assert RESULT_PREFIX in source
        assert "fn(**args)" in source
        assert "entry_dir = os.path.dirname(entry)" in source
        assert "sys.path.insert(0, entry_dir)" in source

    def test_parse_output_ignores_prefix_noise(self):
        blob = json.dumps({"ok": True, "created": ["A"]})
        text = f"Python 3 script successfully executed! Print output: hello\n{RESULT_PREFIX}{blob}\n"
        assert parse_invoke_output(text)["created"] == ["A"]

    def test_parse_output_missing_marker(self):
        with pytest.raises(KitError, match="no RHINOCLAW_KIT_RESULT"):
            parse_invoke_output("just print noise")


class TestMcpTools:
    def test_kit_list(self, kit_dir):
        from rhinoclaw.tools.kit import kit_list

        parsed = json.loads(kit_list(MagicMock()))
        assert parsed["success"] is True
        assert parsed["data"]["kits"][0]["id"] == "demo_kit"

    def test_kit_describe(self, kit_dir):
        from rhinoclaw.tools.kit import kit_describe

        parsed = json.loads(kit_describe(MagicMock(), kit="demo_kit"))
        assert parsed["success"] is True
        names = [a["name"] for a in parsed["data"]["actions"]]
        assert names == ["hello", "clicky"]
        hello = parsed["data"]["actions"][0]
        assert hello["input_schema"]["properties"]["name"]["type"] == "string"

    def test_kit_invoke_rejects_interactive(self, kit_dir):
        from rhinoclaw.tools.kit import kit_invoke

        parsed = json.loads(kit_invoke(MagicMock(), kit="demo_kit", action="clicky"))
        assert parsed["success"] is False
        assert parsed["code"] == "UNSUPPORTED_OPERATION"

    def test_kit_invoke_sends_python3(self, kit_dir):
        from rhinoclaw.tools.kit import kit_invoke

        payload = {"ok": True, "created": ["L1"]}
        rhino = MagicMock()
        rhino.send_command.return_value = {
            "success": True,
            "method": "RhinoCode",
            "result": f"Python 3 script successfully executed! Print output: {RESULT_PREFIX}{json.dumps(payload)}",
        }
        with patch("rhinoclaw.tools.kit.get_rhino_connection", return_value=rhino):
            parsed = json.loads(kit_invoke(
                MagicMock(), kit="demo_kit", action="hello", args='{"name": "Adi"}'))

        assert parsed["success"] is True
        assert parsed["data"]["result"]["created"] == ["L1"]
        cmd, params = rhino.send_command.call_args[0]
        assert cmd == "execute_python3_code"
        assert "rhinoclaw_kit_action" in params["code"]
        assert "Adi" in params["code"]

    def test_kit_invoke_bad_json(self, kit_dir):
        from rhinoclaw.tools.kit import kit_invoke

        parsed = json.loads(kit_invoke(MagicMock(), kit="demo_kit", action="hello", args="{"))
        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    @pytest.mark.parametrize("domain_code", [None, "DRAFT_STALE"])
    def test_domain_refusal_is_not_reported_as_transport_success(self, kit_dir, domain_code):
        from rhinoclaw.tools.kit import kit_invoke

        payload = {"ok": False, "error": "Entwurf inzwischen geändert", "draft_id": "draft-1"}
        if domain_code:
            payload["code"] = domain_code
        rhino = MagicMock()
        rhino.send_command.return_value = {
            "success": True,
            "result": f"Print output: {RESULT_PREFIX}{json.dumps(payload)}",
        }
        with patch("rhinoclaw.tools.kit.get_rhino_connection", return_value=rhino):
            parsed = json.loads(kit_invoke(MagicMock(), kit="demo_kit", action="hello"))
        assert parsed["success"] is False
        assert parsed["code"] == (domain_code or "RHINO_ERROR")
        assert parsed["data"]["result"] == payload


@pytest.mark.skipif(not LAYOUTTOOLS_KIT.is_file(), reason="RhinoLayoutTools not beside RhinoClaw")
@pytest.mark.skipif(os.environ.get("RHINOCLAW_TEST_LOCAL_KITS") != "1",
                    reason="External integration: set RHINOCLAW_TEST_LOCAL_KITS=1 to audit installed sibling kits")
def test_layouttools_manifest_is_valid():
    kit = load_manifest(LAYOUTTOOLS_KIT)
    assert kit.id == "rhinolayouttools"
    callable_names = {a.name for a in kit.actions if a.status == "callable"}
    assert {"layout_batch", "layout_sync", "area_m2", "assembly_constraints", "gear_generator"} <= callable_names
    assembly = kit.action("assembly_constraints").input_schema["properties"]
    assert {"draft_open", "draft_apply", "draft_commit"} <= set(assembly["action"]["enum"])
    assert "expected_draft" in assembly
    for action in kit.actions:
        if action.status == "callable":
            resolve_entry(kit, action)
