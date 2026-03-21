"""Tests for Grasshopper API tools (SDK-based)."""
import pytest
import json
from unittest.mock import MagicMock, patch


class TestLoadGrasshopperDefinition:
    """Tests for load_grasshopper_definition tool."""

    def test_load_success(self):
        """Test successful definition loading."""
        from rhinoclaw.tools.load_grasshopper_definition import load_grasshopper_definition

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "file_path": "C:/test/door.gh",
            "file_name": "door.gh",
            "parameters": [
                {"name": "Height", "nickname": "Lichthoehe", "type": "NumberSlider", "value": 2200}
            ],
            "outputs": [
                {"name": "Geometry", "nickname": "Geo", "type": "Brep", "component_name": "Bake"}
            ],
            "object_count": 15
        }

        with patch("rhinoclaw.tools.load_grasshopper_definition.get_rhino_connection", return_value=mock_rhino):
            result = load_grasshopper_definition(mock_ctx, "C:/test/door.gh")

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["definition_id"] == "abc12345"
        assert len(result_data["data"]["parameters"]) == 1
        assert len(result_data["data"]["outputs"]) == 1
        mock_rhino.send_command.assert_called_once_with("load_grasshopper_definition", {
            "file_path": "C:/test/door.gh"
        })

    def test_load_empty_path(self):
        """Test load with empty path fails."""
        from rhinoclaw.tools.load_grasshopper_definition import load_grasshopper_definition

        mock_ctx = MagicMock()

        result = load_grasshopper_definition(mock_ctx, "")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "file_path is required" in result_data["message"]

    def test_load_wrong_extension(self):
        """Test load with non-.gh/.ghx file fails."""
        from rhinoclaw.tools.load_grasshopper_definition import load_grasshopper_definition

        mock_ctx = MagicMock()

        result = load_grasshopper_definition(mock_ctx, "C:/test/script.py")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert ".gh" in result_data["message"] or ".ghx" in result_data["message"]

    def test_load_ghx_file(self):
        """Test loading .ghx file succeeds."""
        from rhinoclaw.tools.load_grasshopper_definition import load_grasshopper_definition

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "xyz98765",
            "file_path": "C:/test/door.ghx",
            "file_name": "door.ghx",
            "parameters": [],
            "outputs": [],
            "object_count": 5
        }

        with patch("rhinoclaw.tools.load_grasshopper_definition.get_rhino_connection", return_value=mock_rhino):
            result = load_grasshopper_definition(mock_ctx, "C:/test/door.ghx")

        result_data = json.loads(result)
        assert result_data["success"] is True


class TestSetGrasshopperParameter:
    """Tests for set_grasshopper_parameter tool."""

    def test_set_number_parameter(self):
        """Test setting a number parameter."""
        from rhinoclaw.tools.set_grasshopper_parameter import set_grasshopper_parameter

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "parameter_name": "Lichthoehe",
            "parameter_type": "NumberSlider",
            "value": 2400,
            "status": "set"
        }

        with patch("rhinoclaw.tools.set_grasshopper_parameter.get_rhino_connection", return_value=mock_rhino):
            result = set_grasshopper_parameter(mock_ctx, "abc12345", "Lichthoehe", 2400)

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["value"] == 2400
        assert result_data["data"]["parameter_type"] == "NumberSlider"

    def test_set_string_parameter(self):
        """Test setting a string parameter."""
        from rhinoclaw.tools.set_grasshopper_parameter import set_grasshopper_parameter

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "parameter_name": "Label",
            "parameter_type": "Panel",
            "value": "Door A",
            "status": "set"
        }

        with patch("rhinoclaw.tools.set_grasshopper_parameter.get_rhino_connection", return_value=mock_rhino):
            result = set_grasshopper_parameter(mock_ctx, "abc12345", "Label", "Door A")

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["value"] == "Door A"

    def test_set_boolean_parameter(self):
        """Test setting a boolean parameter."""
        from rhinoclaw.tools.set_grasshopper_parameter import set_grasshopper_parameter

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "parameter_name": "Enabled",
            "parameter_type": "BooleanToggle",
            "value": True,
            "status": "set"
        }

        with patch("rhinoclaw.tools.set_grasshopper_parameter.get_rhino_connection", return_value=mock_rhino):
            result = set_grasshopper_parameter(mock_ctx, "abc12345", "Enabled", True)

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["value"] is True

    def test_set_missing_definition_id(self):
        """Test set with missing definition_id fails."""
        from rhinoclaw.tools.set_grasshopper_parameter import set_grasshopper_parameter

        mock_ctx = MagicMock()

        result = set_grasshopper_parameter(mock_ctx, "", "Param", 100)
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "definition_id is required" in result_data["message"]

    def test_set_missing_parameter_name(self):
        """Test set with missing parameter_name fails."""
        from rhinoclaw.tools.set_grasshopper_parameter import set_grasshopper_parameter

        mock_ctx = MagicMock()

        result = set_grasshopper_parameter(mock_ctx, "abc12345", "", 100)
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "parameter_name is required" in result_data["message"]

    def test_set_none_value(self):
        """Test set with None value fails."""
        from rhinoclaw.tools.set_grasshopper_parameter import set_grasshopper_parameter

        mock_ctx = MagicMock()

        result = set_grasshopper_parameter(mock_ctx, "abc12345", "Param", None)
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "value is required" in result_data["message"]


class TestSolveGrasshopper:
    """Tests for solve_grasshopper tool."""

    def test_solve_success(self):
        """Test successful solve."""
        from rhinoclaw.tools.solve_grasshopper import solve_grasshopper

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "status": "solved",
            "errors": [],
            "warnings": []
        }

        with patch("rhinoclaw.tools.solve_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = solve_grasshopper(mock_ctx, "abc12345")

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["status"] == "solved"
        assert len(result_data["data"]["errors"]) == 0

    def test_solve_with_errors(self):
        """Test solve with component errors."""
        from rhinoclaw.tools.solve_grasshopper import solve_grasshopper

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "status": "solved_with_errors",
            "errors": [
                {"component": "Divide", "message": "Division by zero"}
            ],
            "warnings": []
        }

        with patch("rhinoclaw.tools.solve_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = solve_grasshopper(mock_ctx, "abc12345")

        result_data = json.loads(result)
        assert result_data["success"] is True  # Still succeeds, just with errors
        assert result_data["data"]["status"] == "solved_with_errors"
        assert len(result_data["data"]["errors"]) == 1

    def test_solve_expire_all_false(self):
        """Test solve with expire_all=False."""
        from rhinoclaw.tools.solve_grasshopper import solve_grasshopper

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "status": "solved",
            "errors": [],
            "warnings": []
        }

        with patch("rhinoclaw.tools.solve_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = solve_grasshopper(mock_ctx, "abc12345", expire_all=False)

        mock_rhino.send_command.assert_called_once_with("solve_grasshopper", {
            "definition_id": "abc12345",
            "expire_all": False
        })

    def test_solve_missing_definition_id(self):
        """Test solve with missing definition_id fails."""
        from rhinoclaw.tools.solve_grasshopper import solve_grasshopper

        mock_ctx = MagicMock()

        result = solve_grasshopper(mock_ctx, "")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "definition_id is required" in result_data["message"]


class TestBakeGrasshopper:
    """Tests for bake_grasshopper tool."""

    def test_bake_success(self):
        """Test successful bake."""
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "baked_count": 5,
            "baked_objects": [
                {"id": "guid-1", "component": "Bake", "output": "Geo"},
                {"id": "guid-2", "component": "Bake", "output": "Geo"}
            ],
            "layer": "Doors"
        }

        with patch("rhinoclaw.tools.bake_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = bake_grasshopper(mock_ctx, "abc12345", layer="Doors")

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["baked_count"] == 5
        assert len(result_data["data"]["baked_objects"]) == 2

    def test_bake_specific_components(self):
        """Test baking specific components only."""
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "baked_count": 2,
            "baked_objects": [],
            "layer": None
        }

        with patch("rhinoclaw.tools.bake_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = bake_grasshopper(mock_ctx, "abc12345", component_names=["Frame", "Panel"])

        mock_rhino.send_command.assert_called_once_with("bake_grasshopper", {
            "definition_id": "abc12345",
            "component_names": ["Frame", "Panel"]
        })

    def test_bake_missing_definition_id(self):
        """Test bake with missing definition_id fails."""
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        mock_ctx = MagicMock()

        result = bake_grasshopper(mock_ctx, "")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "definition_id is required" in result_data["message"]


class TestGetGrasshopperOutputs:
    """Tests for get_grasshopper_outputs tool."""

    def test_get_outputs_success(self):
        """Test successful output retrieval."""
        from rhinoclaw.tools.get_grasshopper_outputs import get_grasshopper_outputs

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "outputs": {
                "Multiply.Result": {
                    "component": "Multiply",
                    "output": "Result",
                    "type": "Number",
                    "values": [15.0],
                    "count": 1
                }
            }
        }

        with patch("rhinoclaw.tools.get_grasshopper_outputs.get_rhino_connection", return_value=mock_rhino):
            result = get_grasshopper_outputs(mock_ctx, "abc12345")

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert "Multiply.Result" in result_data["data"]["outputs"]
        assert result_data["data"]["outputs"]["Multiply.Result"]["values"] == [15.0]

    def test_get_specific_outputs(self):
        """Test getting specific outputs only."""
        from rhinoclaw.tools.get_grasshopper_outputs import get_grasshopper_outputs

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "outputs": {
                "Result": {
                    "component": "Add",
                    "output": "Result",
                    "type": "Number",
                    "values": [10.0],
                    "count": 1
                }
            }
        }

        with patch("rhinoclaw.tools.get_grasshopper_outputs.get_rhino_connection", return_value=mock_rhino):
            result = get_grasshopper_outputs(mock_ctx, "abc12345", output_names=["Result"])

        mock_rhino.send_command.assert_called_once_with("get_grasshopper_outputs", {
            "definition_id": "abc12345",
            "output_names": ["Result"]
        })

    def test_get_outputs_missing_definition_id(self):
        """Test get outputs with missing definition_id fails."""
        from rhinoclaw.tools.get_grasshopper_outputs import get_grasshopper_outputs

        mock_ctx = MagicMock()

        result = get_grasshopper_outputs(mock_ctx, "")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "definition_id is required" in result_data["message"]


class TestUnloadGrasshopperDefinition:
    """Tests for unload_grasshopper_definition tool."""

    def test_unload_success(self):
        """Test successful unload."""
        from rhinoclaw.tools.unload_grasshopper_definition import unload_grasshopper_definition

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "status": "unloaded"
        }

        with patch("rhinoclaw.tools.unload_grasshopper_definition.get_rhino_connection", return_value=mock_rhino):
            result = unload_grasshopper_definition(mock_ctx, "abc12345")

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["status"] == "unloaded"

    def test_unload_missing_definition_id(self):
        """Test unload with missing definition_id fails."""
        from rhinoclaw.tools.unload_grasshopper_definition import unload_grasshopper_definition

        mock_ctx = MagicMock()

        result = unload_grasshopper_definition(mock_ctx, "")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "definition_id is required" in result_data["message"]


class TestListGrasshopperDefinitions:
    """Tests for list_grasshopper_definitions tool."""

    def test_list_success(self):
        """Test successful list."""
        from rhinoclaw.tools.list_grasshopper_definitions import list_grasshopper_definitions

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definitions": [
                {"definition_id": "abc12345", "file_path": "C:/test/door.gh", "file_name": "door.gh", "object_count": 15},
                {"definition_id": "def67890", "file_path": "C:/test/window.gh", "file_name": "window.gh", "object_count": 10}
            ],
            "count": 2
        }

        with patch("rhinoclaw.tools.list_grasshopper_definitions.get_rhino_connection", return_value=mock_rhino):
            result = list_grasshopper_definitions(mock_ctx)

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["count"] == 2
        assert len(result_data["data"]["definitions"]) == 2

    def test_list_empty(self):
        """Test listing when no definitions loaded."""
        from rhinoclaw.tools.list_grasshopper_definitions import list_grasshopper_definitions

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definitions": [],
            "count": 0
        }

        with patch("rhinoclaw.tools.list_grasshopper_definitions.get_rhino_connection", return_value=mock_rhino):
            result = list_grasshopper_definitions(mock_ctx)

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["count"] == 0


class TestGrasshopperApiWorkflow:
    """Integration-style tests for the full workflow."""

    def test_complete_workflow(self):
        """Test the complete load -> set -> solve -> bake workflow."""
        from rhinoclaw.tools.load_grasshopper_definition import load_grasshopper_definition
        from rhinoclaw.tools.set_grasshopper_parameter import set_grasshopper_parameter
        from rhinoclaw.tools.solve_grasshopper import solve_grasshopper
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper
        from rhinoclaw.tools.unload_grasshopper_definition import unload_grasshopper_definition

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()

        # Mock responses for each step
        mock_rhino.send_command.side_effect = [
            # load_grasshopper_definition
            {
                "definition_id": "abc12345",
                "file_path": "C:/test/door.gh",
                "file_name": "door.gh",
                "parameters": [{"name": "Height", "nickname": "H", "type": "NumberSlider", "value": 2200}],
                "outputs": [],
                "object_count": 10
            },
            # set_grasshopper_parameter
            {
                "definition_id": "abc12345",
                "parameter_name": "H",
                "parameter_type": "NumberSlider",
                "value": 2400,
                "status": "set"
            },
            # solve_grasshopper
            {
                "definition_id": "abc12345",
                "status": "solved",
                "errors": [],
                "warnings": []
            },
            # bake_grasshopper
            {
                "definition_id": "abc12345",
                "baked_count": 3,
                "baked_objects": [{"id": "guid-1", "component": "Bake", "output": "Geo"}],
                "layer": "Doors"
            },
            # unload_grasshopper_definition
            {
                "definition_id": "abc12345",
                "status": "unloaded"
            }
        ]

        # Execute workflow
        with patch("rhinoclaw.tools.load_grasshopper_definition.get_rhino_connection", return_value=mock_rhino), \
             patch("rhinoclaw.tools.set_grasshopper_parameter.get_rhino_connection", return_value=mock_rhino), \
             patch("rhinoclaw.tools.solve_grasshopper.get_rhino_connection", return_value=mock_rhino), \
             patch("rhinoclaw.tools.bake_grasshopper.get_rhino_connection", return_value=mock_rhino), \
             patch("rhinoclaw.tools.unload_grasshopper_definition.get_rhino_connection", return_value=mock_rhino):

            # 1. Load
            result = load_grasshopper_definition(mock_ctx, "C:/test/door.gh")
            result_data = json.loads(result)
            assert result_data["success"] is True
            definition_id = result_data["data"]["definition_id"]

            # 2. Set parameter
            result = set_grasshopper_parameter(mock_ctx, definition_id, "H", 2400)
            result_data = json.loads(result)
            assert result_data["success"] is True

            # 3. Solve
            result = solve_grasshopper(mock_ctx, definition_id)
            result_data = json.loads(result)
            assert result_data["success"] is True
            assert result_data["data"]["status"] == "solved"

            # 4. Bake
            result = bake_grasshopper(mock_ctx, definition_id, layer="Doors")
            result_data = json.loads(result)
            assert result_data["success"] is True
            assert result_data["data"]["baked_count"] == 3

            # 5. Cleanup
            result = unload_grasshopper_definition(mock_ctx, definition_id)
            result_data = json.loads(result)
            assert result_data["success"] is True

        # Verify all commands were called
        assert mock_rhino.send_command.call_count == 5
