"""Tests for Grasshopper API tools (SDK-based)."""
import pytest
import json
from unittest.mock import MagicMock, patch


def _solve_result(
    definition_id="abc12345",
    runtime_messages=None,
    expire_all=True,
):
    runtime_messages = runtime_messages or []
    counts = {
        level: sum(
            message.get("level") == level for message in runtime_messages
        )
        for level in ("remark", "warning", "error")
    }
    legacy = {
        level: [
            {
                "component": message["component"],
                "message": message["message"],
            }
            for message in runtime_messages
            if message.get("level") == level
        ]
        for level in counts
    }
    return {
        "definition_id": definition_id,
        "status": "solved" if counts["error"] == 0 else "solved_with_errors",
        "errors": legacy["error"],
        "warnings": legacy["warning"],
        "remarks": legacy["remark"],
        "runtime_messages": runtime_messages,
        "solution": {
            "requested": True,
            "solve_count": 1,
            "solution_start_count": 1,
            "solution_end_count": 1,
            "expire_all_objects": expire_all,
            "mode": "Silent",
            "state": "PostProcess",
            "duration_ms": 1.0,
            "runtime_messages_collected": True,
            "runtime_message_count": len(runtime_messages),
            "runtime_message_counts": counts,
        },
    }


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
                {
                    "name": "Height",
                    "nickname": "Lichthoehe",
                    "type": "NumberSlider",
                    "value": 2200,
                    "parameter_instance_id":
                        "11111111-1111-1111-1111-111111111111",
                    "settable_by_instance_id": True,
                }
            ],
            "parameter_identity": "parameter_instance_id",
            "settable_parameter_count": 1,
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
            "parameter_identity": "parameter_instance_id",
            "settable_parameter_count": 0,
            "outputs": [],
            "object_count": 5
        }

        with patch("rhinoclaw.tools.load_grasshopper_definition.get_rhino_connection", return_value=mock_rhino):
            result = load_grasshopper_definition(mock_ctx, "C:/test/door.ghx")

        result_data = json.loads(result)
        assert result_data["success"] is True

    def test_load_rejects_duplicate_parameter_identity(self):
        from rhinoclaw.tools.load_grasshopper_definition import (
            load_grasshopper_definition,
        )

        parameter_id = "11111111-1111-1111-1111-111111111111"
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "file_path": "C:/test/duplicate.gh",
            "file_name": "duplicate.gh",
            "parameters": [
                {
                    "parameter_instance_id": parameter_id,
                    "settable_by_instance_id": True,
                },
                {
                    "parameter_instance_id": parameter_id,
                    "settable_by_instance_id": True,
                },
            ],
            "parameter_identity": "parameter_instance_id",
            "settable_parameter_count": 2,
            "outputs": [],
            "object_count": 2,
        }
        with patch(
            "rhinoclaw.tools.load_grasshopper_definition.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = load_grasshopper_definition(
                MagicMock(), "C:/test/duplicate.gh")
        payload = json.loads(result)
        assert payload["success"] is False
        assert payload["code"] == "VERIFICATION_FAILED"
        assert payload["data"]["parameter_verification"]["pass"] is False


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


class TestSetGrasshopperParameters:
    """Tests for exact, atomic loaded-definition parameter batches."""

    first_id = "11111111-1111-1111-1111-111111111111"
    second_id = "22222222-2222-2222-2222-222222222222"

    def test_atomic_batch_success_and_canonical_request(self):
        from rhinoclaw.tools.set_grasshopper_parameters import (
            set_grasshopper_parameters,
        )

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "status": "set",
            "atomic": True,
            "selector": "parameter_instance_id",
            "mutation_attempted": True,
            "assignment_count": 2,
            "assignments": [
                {
                    "parameter_instance_id": self.first_id,
                    "requested_value": 2400,
                    "readback_match": True,
                },
                {
                    "parameter_instance_id": self.second_id,
                    "requested_value": True,
                    "readback_match": True,
                },
            ],
        }
        requested = [
            {"parameter_instance_id": self.first_id.upper(), "value": 2400},
            {"parameter_instance_id": self.second_id, "value": True},
        ]
        with patch(
            "rhinoclaw.tools.set_grasshopper_parameters.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = set_grasshopper_parameters(
                MagicMock(), "abc12345", requested)

        payload = json.loads(result)
        assert payload["success"] is True
        assert payload["data"]["verification"]["pass"] is True
        mock_rhino.send_command.assert_called_once_with(
            "set_grasshopper_parameters",
            {
                "definition_id": "abc12345",
                "assignments": [
                    {"parameter_instance_id": self.first_id, "value": 2400},
                    {"parameter_instance_id": self.second_id, "value": True},
                ],
            },
        )

    @pytest.mark.parametrize(
        "assignments",
        [
            [],
            [{"parameter_instance_id": "not-a-guid", "value": 1}],
            [{"parameter_instance_id": first_id, "value": None}],
            [
                {"parameter_instance_id": first_id, "value": 1},
                {"parameter_instance_id": first_id.upper(), "value": 2},
            ],
            [{"parameter_instance_id": first_id, "value": 1, "name": "x"}],
        ],
    )
    def test_invalid_batches_fail_before_connection(self, assignments):
        from rhinoclaw.tools.set_grasshopper_parameters import (
            set_grasshopper_parameters,
        )

        with patch(
            "rhinoclaw.tools.set_grasshopper_parameters.get_rhino_connection"
        ) as connection:
            result = set_grasshopper_parameters(
                MagicMock(), "abc12345", assignments)
        assert json.loads(result)["success"] is False
        connection.assert_not_called()

    def test_plugin_preflight_maps_to_precondition_failed(self):
        from rhinoclaw.tools.set_grasshopper_parameters import (
            set_grasshopper_parameters,
        )

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "status": "preflight_failed",
            "atomic": True,
            "mutation_attempted": False,
            "issues": [{"code": "INVALID_PARAMETER_VALUE"}],
        }
        with patch(
            "rhinoclaw.tools.set_grasshopper_parameters.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = set_grasshopper_parameters(MagicMock(), "abc12345", [{
                "parameter_instance_id": self.first_id,
                "value": 999999,
            }])
        payload = json.loads(result)
        assert payload["success"] is False
        assert payload["code"] == "PRECONDITION_FAILED"
        assert payload["data"]["mutation_attempted"] is False

    @pytest.mark.parametrize(
        ("rollback_complete", "expected_code"),
        [(True, "VERIFICATION_FAILED"), (False, "PARTIAL_MUTATION")],
    )
    def test_failed_commit_classifies_rollback(
        self, rollback_complete, expected_code
    ):
        from rhinoclaw.tools.set_grasshopper_parameters import (
            set_grasshopper_parameters,
        )

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "status": "failed_after_mutation",
            "atomic": True,
            "mutation_attempted": True,
            "failure": "readback mismatch",
            "rollback": {
                "attempted": True,
                "complete": rollback_complete,
                "issues": [] if rollback_complete else [{"stage": "readback"}],
            },
        }
        with patch(
            "rhinoclaw.tools.set_grasshopper_parameters.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = set_grasshopper_parameters(MagicMock(), "abc12345", [{
                "parameter_instance_id": self.first_id,
                "value": 1,
            }])
        payload = json.loads(result)
        assert payload["success"] is False
        assert payload["code"] == expected_code


class TestSolveGrasshopper:
    """Tests for solve_grasshopper tool."""

    def test_solve_success(self):
        """Test successful solve."""
        from rhinoclaw.tools.solve_grasshopper import solve_grasshopper

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = _solve_result()

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
        runtime_messages = [{
            "component": "Divide",
            "component_name": "Division",
            "component_id": "11111111-1111-1111-1111-111111111111",
            "component_type": "Grasshopper.Components.Division",
            "level": "error",
            "message": "Division by zero",
        }]
        mock_rhino.send_command.return_value = _solve_result(
            runtime_messages=runtime_messages)

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
        mock_rhino.send_command.return_value = _solve_result(expire_all=False)

        with patch("rhinoclaw.tools.solve_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = solve_grasshopper(mock_ctx, "abc12345", expire_all=False)

        assert json.loads(result)["success"] is True
        mock_rhino.send_command.assert_called_once_with("solve_grasshopper", {
            "definition_id": "abc12345",
            "expire_all": False
        })

    def test_solve_rejects_missing_cycle_evidence(self):
        from rhinoclaw.tools.solve_grasshopper import solve_grasshopper

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "status": "solved",
            "errors": [],
            "warnings": [],
        }
        with patch(
            "rhinoclaw.tools.solve_grasshopper.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = solve_grasshopper(MagicMock(), "abc12345")
        payload = json.loads(result)
        assert payload["success"] is False
        assert payload["code"] == "VERIFICATION_FAILED"
        assert payload["data"]["verification"]["pass"] is False

    def test_solve_rejects_runtime_message_count_mismatch(self):
        from rhinoclaw.tools.solve_grasshopper import solve_grasshopper

        mock_rhino = MagicMock()
        inconsistent = _solve_result()
        inconsistent["solution"]["runtime_message_count"] = 1
        mock_rhino.send_command.return_value = inconsistent
        with patch(
            "rhinoclaw.tools.solve_grasshopper.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = solve_grasshopper(MagicMock(), "abc12345")
        payload = json.loads(result)
        assert payload["success"] is False
        assert payload["code"] == "VERIFICATION_FAILED"

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
        baked = {
            "definition_id": "abc12345",
            "baked_count": 2,
            "baked_objects": [
                {"id": "11111111-1111-1111-1111-111111111111",
                 "component": "Bake", "output": "Geo"},
                {"id": "22222222-2222-2222-2222-222222222222",
                 "component": "Bake", "output": "Geo"},
            ],
            "layer": "Doors"
        }

        def route(command, params):
            if command == "bake_grasshopper":
                return baked
            assert command == "get_objects_info"
            return {
                "count": 2,
                "missing_count": 0,
                "results": [
                    {"id": "11111111-1111-1111-1111-111111111111"},
                    {"id": "22222222-2222-2222-2222-222222222222"},
                ],
                "missing": [],
            }

        mock_rhino.send_command.side_effect = route

        with patch("rhinoclaw.tools.bake_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = bake_grasshopper(mock_ctx, "abc12345", layer="Doors")

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["baked_count"] == 2
        assert len(result_data["data"]["baked_objects"]) == 2
        assert result_data["data"]["verification"]["pass"] is True

    def test_bake_specific_components(self):
        """Test baking specific components only."""
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        baked = {
            "definition_id": "abc12345",
            "baked_count": 2,
            "baked_objects": [
                {"id": "11111111-1111-1111-1111-111111111111"},
                {"id": "22222222-2222-2222-2222-222222222222"},
            ],
            "layer": None
        }

        mock_rhino.send_command.side_effect = [
            baked,
            {
                "count": 2,
                "missing_count": 0,
                "results": [
                    {"id": "11111111-1111-1111-1111-111111111111"},
                    {"id": "22222222-2222-2222-2222-222222222222"},
                ],
                "missing": [],
            },
        ]

        with patch("rhinoclaw.tools.bake_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = bake_grasshopper(mock_ctx, "abc12345", component_names=["Frame", "Panel"])

        assert mock_rhino.send_command.call_args_list[0].args == (
            "bake_grasshopper",
            {
                "definition_id": "abc12345",
                "component_names": ["Frame", "Panel"],
            },
        )

    def test_bake_exact_output_target_is_canonicalized(self):
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        component_id = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
        output_id = "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = [
            {
                "definition_id": "abc12345",
                "baked_count": 1,
                "baked_objects": [{
                    "id": "11111111-1111-1111-1111-111111111111",
                }],
            },
            {
                "count": 1,
                "missing_count": 0,
                "results": [{
                    "id": "11111111-1111-1111-1111-111111111111",
                }],
                "missing": [],
            },
        ]
        with patch(
            "rhinoclaw.tools.bake_grasshopper.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = json.loads(bake_grasshopper(
                MagicMock(),
                "abc12345",
                output_targets=[{
                    "component_instance_id": component_id,
                    "output_instance_id": output_id,
                }],
            ))

        assert result["success"] is True
        assert mock_rhino.send_command.call_args_list[0].args == (
            "bake_grasshopper",
            {
                "definition_id": "abc12345",
                "output_targets": [{
                    "component_instance_id": component_id.lower(),
                    "output_instance_id": output_id.lower(),
                }],
            },
        )

    def test_bake_rejects_ambiguous_selector_contract_before_connection(self):
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        with patch(
            "rhinoclaw.tools.bake_grasshopper.get_rhino_connection",
        ) as connection:
            result = json.loads(bake_grasshopper(
                MagicMock(),
                "abc12345",
                component_names=["Result"],
                output_targets=[{
                    "component_instance_id":
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "output_instance_id":
                        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                }],
            ))

        assert result["success"] is False
        assert result["code"] == "INVALID_PARAMS"
        connection.assert_not_called()

    def test_bake_rejects_inconsistent_report_as_partial_mutation(self):
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "baked_count": 2,
            "baked_objects": [
                {"id": "11111111-1111-1111-1111-111111111111"},
            ],
        }
        with patch(
            "rhinoclaw.tools.bake_grasshopper.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = json.loads(bake_grasshopper(MagicMock(), "abc12345"))

        assert result["success"] is False
        assert result["code"] == "PARTIAL_MUTATION"
        assert result["data"]["verification"]["pass"] is False
        assert mock_rhino.send_command.call_count == 1

    def test_bake_rejects_missing_active_object_as_partial_mutation(self):
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = [
            {
                "definition_id": "abc12345",
                "baked_count": 1,
                "baked_objects": [
                    {"id": "11111111-1111-1111-1111-111111111111"},
                ],
            },
            {
                "count": 0,
                "missing_count": 1,
                "results": [],
                "missing": [{"id": "11111111-1111-1111-1111-111111111111"}],
            },
        ]
        with patch(
            "rhinoclaw.tools.bake_grasshopper.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = json.loads(bake_grasshopper(MagicMock(), "abc12345"))

        assert result["success"] is False
        assert result["code"] == "PARTIAL_MUTATION"
        assert result["data"]["verification"]["pass"] is False

    def test_bake_zero_objects_is_verification_failure(self):
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "baked_count": 0,
            "baked_objects": [],
        }
        with patch(
            "rhinoclaw.tools.bake_grasshopper.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = json.loads(bake_grasshopper(MagicMock(), "abc12345"))

        assert result["success"] is False
        assert result["code"] == "VERIFICATION_FAILED"
        assert mock_rhino.send_command.call_count == 1

    def test_guarded_bakeaware_preflight_failure_preserves_evidence(self):
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "baked_count": 0,
            "baked_objects": [],
            "bake_mode": "guarded_bake_aware",
            "guarded_bake_aware": True,
            "mutation_attempted": False,
            "bake_status": "preflight_failed",
            "failure": "mixed BakeAware/non-BakeAware batch",
            "evidence": [],
        }
        with patch(
            "rhinoclaw.tools.bake_grasshopper.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = json.loads(bake_grasshopper(
                MagicMock(),
                "abc12345",
                output_targets=[{
                    "component_instance_id":
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "output_instance_id":
                        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                }],
            ))

        assert result["success"] is False
        assert result["code"] == "PRECONDITION_FAILED"
        assert result["data"]["mutation_attempted"] is False
        assert mock_rhino.send_command.call_count == 1

    def test_guarded_bakeaware_failure_after_mutation_is_partial(self):
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "baked_count": 0,
            "baked_objects": [],
            "bake_mode": "guarded_bake_aware",
            "guarded_bake_aware": True,
            "mutation_attempted": True,
            "bake_status": "failed_after_mutation",
            "failure": "native BakeGeometry returned false",
            "covered_state_restored": True,
            "unmeasured_state": ["visualarq_plugin_private_state"],
            "evidence": [{"success": False}],
        }
        with patch(
            "rhinoclaw.tools.bake_grasshopper.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = json.loads(bake_grasshopper(
                MagicMock(),
                "abc12345",
                output_targets=[{
                    "component_instance_id":
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "output_instance_id":
                        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                }],
            ))

        assert result["success"] is False
        assert result["code"] == "PARTIAL_MUTATION"
        assert result["data"]["covered_state_restored"] is True
        assert "visualarq_plugin_private_state" in \
            result["data"]["unmeasured_state"]
        assert mock_rhino.send_command.call_count == 1

    def test_guarded_bakeaware_success_still_requires_active_readback(self):
        from rhinoclaw.tools.bake_grasshopper import bake_grasshopper

        object_id = "11111111-1111-4111-8111-111111111111"
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = [
            {
                "definition_id": "abc12345",
                "baked_count": 1,
                "baked_objects": [{"id": object_id}],
                "bake_mode": "guarded_bake_aware",
                "guarded_bake_aware": True,
                "mutation_attempted": True,
                "bake_status": "success",
                "invocation_count": 1,
                "evidence": [{
                    "success": True,
                    "ownership_proven": True,
                    "goo_type": "VisualARQ.GhVaWall",
                }],
            },
            {
                "count": 1,
                "missing_count": 0,
                "results": [{"id": object_id}],
                "missing": [],
            },
        ]
        with patch(
            "rhinoclaw.tools.bake_grasshopper.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = json.loads(bake_grasshopper(
                MagicMock(),
                "abc12345",
                output_targets=[{
                    "component_instance_id":
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "output_instance_id":
                        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                }],
            ))

        assert result["success"] is True
        assert result["data"]["verification"]["pass"] is True
        assert result["data"]["bake_mode"] == "guarded_bake_aware"
        assert mock_rhino.send_command.call_args_list[1].args == (
            "get_objects_info", {"ids": [object_id]})

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

    def test_get_exact_output_target(self):
        from rhinoclaw.tools.get_grasshopper_outputs import (
            get_grasshopper_outputs,
        )

        component_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        output_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definition_id": "abc12345",
            "outputs": {},
            "output_count": 0,
        }
        with patch(
            "rhinoclaw.tools.get_grasshopper_outputs.get_rhino_connection",
            return_value=mock_rhino,
        ):
            result = json.loads(get_grasshopper_outputs(
                MagicMock(),
                "abc12345",
                output_targets=[{
                    "component_instance_id": component_id,
                    "output_instance_id": output_id,
                }],
            ))

        assert result["success"] is True
        mock_rhino.send_command.assert_called_once_with(
            "get_grasshopper_outputs",
            {
                "definition_id": "abc12345",
                "output_targets": [{
                    "component_instance_id": component_id,
                    "output_instance_id": output_id,
                }],
            },
        )

    @pytest.mark.parametrize(
        "targets",
        [
            [],
            [{}],
            [{
                "component_instance_id": "not-a-guid",
                "output_instance_id":
                    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            }],
            [{
                "component_instance_id":
                    "00000000-0000-0000-0000-000000000000",
                "output_instance_id":
                    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            }],
        ],
    )
    def test_get_rejects_invalid_exact_targets(self, targets):
        from rhinoclaw.tools.get_grasshopper_outputs import (
            get_grasshopper_outputs,
        )

        with patch(
            "rhinoclaw.tools.get_grasshopper_outputs.get_rhino_connection",
        ) as connection:
            result = json.loads(get_grasshopper_outputs(
                MagicMock(), "abc12345", output_targets=targets))

        assert result["success"] is False
        assert result["code"] == "INVALID_PARAMS"
        connection.assert_not_called()

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
                "parameters": [{
                    "name": "Height",
                    "nickname": "H",
                    "type": "NumberSlider",
                    "value": 2200,
                    "parameter_instance_id":
                        "11111111-1111-1111-1111-111111111111",
                    "settable_by_instance_id": True,
                }],
                "parameter_identity": "parameter_instance_id",
                "settable_parameter_count": 1,
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
            _solve_result(),
            # bake_grasshopper
            {
                "definition_id": "abc12345",
                "baked_count": 1,
                "baked_objects": [{
                    "id": "11111111-1111-1111-1111-111111111111",
                    "component": "Bake",
                    "output": "Geo",
                }],
                "layer": "Doors"
            },
            # independent active-object readback
            {
                "count": 1,
                "missing_count": 0,
                "results": [{
                    "id": "11111111-1111-1111-1111-111111111111",
                }],
                "missing": [],
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
            assert result_data["data"]["baked_count"] == 1
            assert result_data["data"]["verification"]["pass"] is True

            # 5. Cleanup
            result = unload_grasshopper_definition(mock_ctx, definition_id)
            result_data = json.loads(result)
            assert result_data["success"] is True

        # Verify all commands were called
        assert mock_rhino.send_command.call_count == 6
