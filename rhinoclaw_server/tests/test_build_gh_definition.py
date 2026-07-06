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


class TestBuildGhDefinition:
    def test_success_passes_through_status(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test/box.gh",
            "object_count": 3,
            "errors": [],
            "status": "success",
        }
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

    def test_wires_default_to_empty_list(self):
        from rhinoclaw.tools.build_gh_definition import build_gh_definition

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test/box.gh",
            "object_count": 1,
            "errors": [],
            "status": "success",
        }
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
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test/box.gh",
            "object_count": 2,
            "errors": [{"component": "Box", "message": "unwired input"}],
            "status": "success_with_errors",
        }
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
        mock_rhino.send_command.return_value = {"status": "success", "object_count": 1}
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
