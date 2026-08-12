"""Tests for the build_gh_definition tool.

This is the first coverage for the GH *authoring* path. The C# engine
(GrasshopperDefinitionBuilder.cs) was dispatched + advertised but had no MCP
wrapper, so an agent could not author a .gh at all. These tests pin the
wrapper's contract: parameter validation, params forwarded to the plugin, and
the inner build status ("success" / "success_with_errors") passed through.
"""
import json
from unittest.mock import MagicMock, patch

SLIDER = {"type": "slider", "name": "Width", "default": 200, "min": 10, "max": 1000}
SCRIPT = {"type": "python3_script", "name": "Box", "code": "a = Width", "inputs": ["Width"]}
WIRE = {"from": "Width", "to": "Box", "to_input": "Width"}
CATALOG_OK = {
    "pass": True,
    "schema_version": 1,
    "global_match": True,
    "scope": "full_catalog",
    "authoring_search_complete": True,
    "evidence": {
        "contract": {
            "schema_version": 1,
            "component_count": 2534,
            "proxy_guid_sha256": "a" * 64,
            "component_contract_sha256": "b" * 64,
        },
        "runtime": {"proxy_count": 2534, "proxy_guid_sha256": "a" * 64},
        "used_component_count": 0,
        "used_components": [],
    },
}


def _verified(result):
    return {**result, "catalog_verification": CATALOG_OK}


class TestBuildGhDefinition:
    def test_success_passes_through_status(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified({
            "file_path": "C:/test/box.gh",
            "object_count": 3,
            "errors": [],
            "status": "success",
        })
        with patch(
            "rhinoclaw.tools.build_gh_definition.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = build_gh_definition(
                MagicMock(), "C:/test/box.gh", [SLIDER, SCRIPT], [WIRE]
            )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["status"] == "success"
        assert data["data"]["object_count"] == 3
        mock_rhino.send_command.assert_called_once()
        cmd, params = mock_rhino.send_command.call_args[0]
        assert cmd == "build_gh_definition"
        assert params["components"] == [SLIDER, SCRIPT]
        assert params["wires"] == [WIRE]
        assert params["catalog_contract"]["schema_version"] == 1
        assert params["catalog_contract"]["used_components"] == []

    def test_preserves_author_only_solution_runtime_and_catalog_evidence(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        solution = {
            "requested": False,
            "solve_count": 0,
            "solution_start_count": 0,
            "solution_end_count": 0,
            "runtime_messages_collected": False,
        }
        runtime_messages = []
        publication = {
            "published": True,
            "atomic": True,
            "staging_file_cleaned": True,
        }
        session_cleanup = {
            "complete": True,
            "document_absent_from_server": True,
        }
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified({
            "file_path": "C:/test/box.gh",
            "object_count": 1,
            "errors": [],
            "runtime_messages": runtime_messages,
            "solution": solution,
            "publication": publication,
            "session_cleanup": session_cleanup,
            "status": "success",
        })
        with patch(
            "rhinoclaw.tools.build_gh_definition.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = build_gh_definition(
                MagicMock(), "C:/test/box.gh", [SLIDER]
            )

        data = json.loads(result)["data"]
        assert data["solution"] == solution
        assert data["runtime_messages"] == runtime_messages
        assert data["publication"] == publication
        assert data["session_cleanup"] == session_cleanup
        assert data["catalog_verification"] == CATALOG_OK
        assert data["lint"]["valid"] is True

    def test_wires_default_to_empty_list(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified({
            "file_path": "C:/test/box.gh",
            "object_count": 1,
            "errors": [],
            "status": "success",
        })
        with patch(
            "rhinoclaw.tools.build_gh_definition.get_rhino_connection",
            return_value=mock_rhino,
        ):
            build_gh_definition(MagicMock(), "C:/test/box.gh", [SLIDER])

        _, params = mock_rhino.send_command.call_args[0]
        assert params["wires"] == []
        # description omitted when not provided
        assert "description" not in params

    def test_success_with_errors_passes_through(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified({
            "file_path": "C:/test/box.gh",
            "object_count": 2,
            "errors": [{"component": "Box", "message": "unwired input"}],
            "status": "success_with_errors",
        })
        with patch(
            "rhinoclaw.tools.build_gh_definition.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = build_gh_definition(MagicMock(), "C:/test/box.gh", [SCRIPT])

        data = json.loads(result)
        # Transport-level success, but the inner build status + errors survive.
        assert data["success"] is True
        assert data["data"]["status"] == "success_with_errors"
        assert len(data["data"]["errors"]) == 1
        assert "success_with_errors" in data["message"]
        assert "1 error" in data["message"]

    def test_description_forwarded(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified(
            {"status": "success", "object_count": 1}
        )
        with patch(
            "rhinoclaw.tools.build_gh_definition.get_rhino_connection",
            return_value=mock_rhino,
        ):
            build_gh_definition(
                MagicMock(), "C:/test/box.gh", [SLIDER], description="a box"
            )

        _, params = mock_rhino.send_command.call_args[0]
        assert params["description"] == "a box"

    def test_empty_path_fails(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        data = json.loads(build_gh_definition(MagicMock(), "", [SLIDER]))
        assert data["success"] is False
        assert "file_path is required" in data["message"]

    def test_wrong_extension_fails(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        data = json.loads(build_gh_definition(MagicMock(), "C:/test/box.py", [SLIDER]))
        assert data["success"] is False
        assert ".gh" in data["message"]

    def test_empty_components_fails(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        data = json.loads(build_gh_definition(MagicMock(), "C:/test/box.gh", []))
        assert data["success"] is False
        assert "components" in data["message"]

    def test_unauthorable_catalog_component_fails_before_roundtrip(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        unsafe = {
            "type": "sdk_component",
            "name": "Unsafe",
            "guid": "00000000-0000-0000-0000-000000000000",
        }
        with patch(
            "rhinoclaw.tools.build_gh_definition.get_rhino_connection",
        ) as connection:
            data = json.loads(build_gh_definition(
                MagicMock(), "C:/test/unsafe.gh", [unsafe]))

        assert data["success"] is False
        assert data["code"] == "INVALID_PARAMS"
        assert data["data"]["lint"]["valid"] is False
        assert any("not authorable" in value
                   for value in data["data"]["lint"]["errors"])
        connection.assert_not_called()

    def test_sdk_build_sends_exact_catalog_port_contract(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        box = {
            "type": "sdk_component",
            "name": "Box",
            "guid": "28061aae-04fb-4cb5-ac45-16f3b66bc0a4",
        }
        box_entry = {
            "guid": box["guid"],
            "name": "Center Box",
            "in": [
                {"n": "Base", "nn": "Base Plane", "t": "Plane"},
                {"n": "X", "nn": "X Size", "t": "Interval"},
                {"n": "Y", "nn": "Y Size", "t": "Interval"},
                {"n": "Z", "nn": "Z Size", "t": "Interval"},
            ],
            "out": [{"n": "Box", "nn": "Box", "t": "Box"}],
        }
        synthetic_catalog = {
            "meta": {"source": "synthetic unit-test catalog"},
            "components": [
                {
                    "guid": "11111111-1111-1111-1111-111111111111",
                    "name": "Unrelated",
                    "in": [],
                    "out": [],
                },
                box_entry,
            ],
        }
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _verified({
            "status": "success",
            "object_count": 1,
        })
        with (
            patch(
                "rhinoclaw.tools.build_gh_definition._catalog",
                return_value=synthetic_catalog,
            ),
            patch(
                "rhinoclaw.tools.build_gh_definition.get_rhino_connection",
                return_value=mock_rhino,
            ),
        ):
            build_gh_definition(MagicMock(), "C:/test/box.gh", [box])

        _, params = mock_rhino.send_command.call_args[0]
        contract = params["catalog_contract"]
        assert contract["component_count"] == len(
            synthetic_catalog["components"])
        assert len(contract["proxy_guid_sha256"]) == 64
        assert contract["used_components"] == [box_entry]
        assert [
            port["n"] for port in contract["used_components"][0]["in"]
        ] == ["Base", "X", "Y", "Z"]

    def test_old_plugin_success_without_verification_fails_closed(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "status": "success",
            "object_count": 1,
        }
        with patch(
            "rhinoclaw.tools.build_gh_definition.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = build_gh_definition(
                MagicMock(), "C:/test/old.gh", [SLIDER]
            )

        data = json.loads(result)
        assert data["success"] is False
        assert data["code"] == "VERIFICATION_FAILED"
        assert "update/restart" in data["message"]
        assert data["data"]["catalog_verification"] is None
        assert data["data"]["mutation_scope"] == "unknown_old_plugin_response"
