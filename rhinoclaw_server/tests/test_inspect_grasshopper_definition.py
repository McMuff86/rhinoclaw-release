"""Tests for the inspect_grasshopper_definition tool."""
import json
from unittest.mock import MagicMock, patch


class TestInspectValidation:
    """Validation happens server-side; the Python wrapper just forwards."""

    @patch("rhinoclaw.tools.inspect_grasshopper_definition.get_rhino_connection")
    def test_passes_file_path(self, mock_get_conn):
        from rhinoclaw.tools.inspect_grasshopper_definition import (
            inspect_grasshopper_definition,
        )

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "/tmp/example.gh",
            "file_name": "example.gh",
            "object_count": 5,
            "input_count": 0,
            "output_count": 0,
            "inputs": [],
            "outputs": [],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = inspect_grasshopper_definition(ctx, file_path="/tmp/example.gh")
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_rhino.send_command.assert_called_once_with(
            "inspect_grasshopper_definition",
            {"file_path": "/tmp/example.gh"},
        )

    @patch("rhinoclaw.tools.inspect_grasshopper_definition.get_rhino_connection")
    def test_include_components_flag(self, mock_get_conn):
        from rhinoclaw.tools.inspect_grasshopper_definition import (
            inspect_grasshopper_definition,
        )

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "/tmp/x.gh",
            "file_name": "x.gh",
            "object_count": 0,
            "input_count": 0,
            "output_count": 0,
            "inputs": [],
            "outputs": [],
            "components_by_type": [],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        inspect_grasshopper_definition(ctx, file_path="/tmp/x.gh", include_components=True)

        mock_rhino.send_command.assert_called_once_with(
            "inspect_grasshopper_definition",
            {"file_path": "/tmp/x.gh", "include_components": True},
        )

    @patch("rhinoclaw.tools.inspect_grasshopper_definition.get_rhino_connection")
    def test_only_player_inputs_flag(self, mock_get_conn):
        from rhinoclaw.tools.inspect_grasshopper_definition import (
            inspect_grasshopper_definition,
        )

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "/tmp/x.gh", "file_name": "x.gh",
            "object_count": 0, "input_count": 0, "output_count": 0,
            "inputs": [], "outputs": [],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        inspect_grasshopper_definition(ctx, file_path="/tmp/x.gh", only_player_inputs=True)

        mock_rhino.send_command.assert_called_once_with(
            "inspect_grasshopper_definition",
            {"file_path": "/tmp/x.gh", "only_player_inputs": True},
        )


class TestInspectSuccess:
    """Successful introspection returns the parameter surface."""

    @patch("rhinoclaw.tools.inspect_grasshopper_definition.get_rhino_connection")
    def test_returns_inputs_outputs(self, mock_get_conn):
        from rhinoclaw.tools.inspect_grasshopper_definition import (
            inspect_grasshopper_definition,
        )

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "/tmp/door.gh",
            "file_name": "door.gh",
            "object_count": 47,
            "input_count": 3,
            "output_count": 1,
            "inputs": [
                {"name": "Lichthoehe", "nickname": "h", "kind": "slider",
                 "type": "number", "value": 2200, "min": 1500, "max": 3000,
                 "decimals": 0, "component_guid": "abc",
                 "is_player_input": True},
                {"name": "Lichtbreite", "nickname": "w", "kind": "slider",
                 "type": "number", "value": 910, "min": 600, "max": 1200,
                 "decimals": 0, "component_guid": "def",
                 "is_player_input": True},
                {"name": "Bandseite", "nickname": "side", "kind": "prompt",
                 "type": "string", "prompt": "Bandseite waehlen",
                 "presets": ["Links", "Rechts"], "component_guid": "ghi",
                 "is_player_input": True},
            ],
            "outputs": [
                {"name": "Geometry", "nickname": "G", "type": "Brep",
                 "component_name": "Solid Difference",
                 "component_guid": "jkl", "param_index": 0},
            ],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = inspect_grasshopper_definition(ctx, file_path="/tmp/door.gh")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "3 inputs" in parsed["message"]
        assert "1 outputs" in parsed["message"]
        assert parsed["data"]["inputs"][0]["name"] == "Lichthoehe"
        assert parsed["data"]["inputs"][0]["is_player_input"] is True
        assert parsed["data"]["inputs"][2]["kind"] == "prompt"
        assert parsed["data"]["inputs"][2]["presets"] == ["Links", "Rechts"]


class TestPromptDefaultMerging:
    """Prompts absorb their upstream slider/panel defaults."""

    @patch("rhinoclaw.tools.inspect_grasshopper_definition.get_rhino_connection")
    def test_prompt_carries_slider_default(self, mock_get_conn):
        """In `only_player_inputs` mode, the slider feeding a Get-Number
        is gone from the list; the Get-Number itself carries value/min/max."""
        from rhinoclaw.tools.inspect_grasshopper_definition import (
            inspect_grasshopper_definition,
        )

        mock_rhino = MagicMock()
        # Plugin already filtered + merged. Slider isn't here; prompt has
        # everything baked in.
        mock_rhino.send_command.return_value = {
            "file_path": "/tmp/door.gh", "file_name": "door.gh",
            "object_count": 50, "input_count": 2, "output_count": 1,
            "inputs": [
                {
                    "name": "Lichthoehe",
                    "nickname": "Lichthoehe",
                    "kind": "prompt",
                    "type": "number",
                    "prompt": "Lichthoehe",
                    "presets": [],
                    "value": 2100,
                    "default": 2100,
                    "min": 1500,
                    "max": 3000,
                    "decimals": 0,
                    "is_player_input": True,
                    "component_guid": "prompt-1",
                    "default_source": {
                        "kind": "slider",
                        "component_guid": "slider-1",
                        "nickname": "Lichthoehe",
                        "name": "Lichthoehe",
                    },
                },
                {
                    "name": "Lichtbreite",
                    "nickname": "Lichtbreite",
                    "kind": "prompt",
                    "type": "number",
                    "prompt": "Lichtbreite",
                    "presets": [],
                    "value": 960,
                    "default": 960,
                    "min": 600,
                    "max": 1200,
                    "decimals": 0,
                    "is_player_input": True,
                    "component_guid": "prompt-2",
                    "default_source": {
                        "kind": "slider",
                        "component_guid": "slider-2",
                        "nickname": "Lichtbreite",
                        "name": "Lichtbreite",
                    },
                },
            ],
            "outputs": [],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = inspect_grasshopper_definition(
            ctx, file_path="/tmp/door.gh", only_player_inputs=True
        )
        parsed = json.loads(result)
        inputs = parsed["data"]["inputs"]

        # No slider listed on its own — the 21 internal sliders that
        # don't feed a prompt are gone, and the two that DO feed prompts
        # have been merged into the prompts.
        kinds = [i["kind"] for i in inputs]
        assert kinds == ["prompt", "prompt"]

        lichthoehe = inputs[0]
        assert lichthoehe["value"] == 2100
        assert lichthoehe["default"] == 2100
        assert lichthoehe["min"] == 1500
        assert lichthoehe["max"] == 3000
        assert lichthoehe["default_source"]["kind"] == "slider"
        assert lichthoehe["default_source"]["nickname"] == "Lichthoehe"

    @patch("rhinoclaw.tools.inspect_grasshopper_definition.get_rhino_connection")
    def test_unfiltered_view_keeps_default_source_relation(self, mock_get_conn):
        """In the unfiltered (default) view, sliders still appear but are
        flagged so the agent can see the prompt/default-source pairing."""
        from rhinoclaw.tools.inspect_grasshopper_definition import (
            inspect_grasshopper_definition,
        )

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "/tmp/door.gh", "file_name": "door.gh",
            "object_count": 4, "input_count": 2, "output_count": 0,
            "inputs": [
                {
                    "name": "Lichthoehe",
                    "nickname": "Lichthoehe",
                    "kind": "slider",
                    "type": "number",
                    "value": 2100, "min": 1500, "max": 3000, "decimals": 0,
                    "is_player_input": True,
                    "is_prompt_default_source": True,
                    "feeds_prompt_guid": "prompt-1",
                    "component_guid": "slider-1",
                },
                {
                    "name": "Lichthoehe",
                    "nickname": "Lichthoehe",
                    "kind": "prompt",
                    "type": "number",
                    "prompt": "Lichthoehe",
                    "presets": [],
                    "value": 2100, "default": 2100,
                    "min": 1500, "max": 3000, "decimals": 0,
                    "is_player_input": True,
                    "component_guid": "prompt-1",
                    "default_source": {
                        "kind": "slider",
                        "component_guid": "slider-1",
                        "nickname": "Lichthoehe",
                        "name": "Lichthoehe",
                    },
                },
            ],
            "outputs": [],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = inspect_grasshopper_definition(ctx, file_path="/tmp/door.gh")
        parsed = json.loads(result)
        inputs = parsed["data"]["inputs"]

        # Both appear; relationship is captured on both ends.
        slider = inputs[0]
        prompt = inputs[1]
        assert slider["is_prompt_default_source"] is True
        assert slider["feeds_prompt_guid"] == prompt["component_guid"]
        assert prompt["default_source"]["component_guid"] == slider["component_guid"]


class TestInspectErrors:
    """Failures from the plugin are propagated as structured errors."""

    @patch("rhinoclaw.tools.inspect_grasshopper_definition.get_rhino_connection")
    def test_file_not_found(self, mock_get_conn):
        from rhinoclaw.tools.inspect_grasshopper_definition import (
            inspect_grasshopper_definition,
        )

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception(
            "Grasshopper file not found: /no/such.gh"
        )
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = inspect_grasshopper_definition(ctx, file_path="/no/such.gh")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]
        assert "not found" in parsed["message"]

    @patch("rhinoclaw.tools.inspect_grasshopper_definition.get_rhino_connection")
    def test_connection_error(self, mock_get_conn):
        from rhinoclaw.tools.inspect_grasshopper_definition import (
            inspect_grasshopper_definition,
        )

        mock_get_conn.side_effect = Exception("Connection refused")

        ctx = MagicMock()
        result = inspect_grasshopper_definition(ctx, file_path="/tmp/x.gh")
        parsed = json.loads(result)

        assert parsed["success"] is False
