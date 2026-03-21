"""
Tests for the create_group tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestCreateGroupValidation:
    """Tests for create_group parameter validation."""

    @patch("rhinoclaw.tools.create_group.get_rhino_connection")
    def test_missing_object_ids(self, mock_get_conn):
        from rhinoclaw.tools.create_group import create_group

        ctx = MagicMock()
        result = create_group(ctx, object_ids=[])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]

    @patch("rhinoclaw.tools.create_group.get_rhino_connection")
    def test_none_object_ids(self, mock_get_conn):
        from rhinoclaw.tools.create_group import create_group

        ctx = MagicMock()
        result = create_group(ctx, object_ids=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]


class TestCreateGroupSuccess:
    """Tests for successful group creation."""

    @patch("rhinoclaw.tools.create_group.get_rhino_connection")
    def test_create_group_success(self, mock_get_conn):
        from rhinoclaw.tools.create_group import create_group

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "group_id": "group-guid-123",
            "group_name": "Group 01",
            "object_count": 3
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = create_group(ctx, object_ids=["obj1", "obj2", "obj3"])
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Created group" in parsed["message"]
        assert parsed["data"]["group_id"] == "group-guid-123"
        assert parsed["data"]["object_count"] == 3

        mock_rhino.send_command.assert_called_once_with("create_group", {
            "object_ids": ["obj1", "obj2", "obj3"],
            "group_name": None
        })

    @patch("rhinoclaw.tools.create_group.get_rhino_connection")
    def test_create_named_group_success(self, mock_get_conn):
        from rhinoclaw.tools.create_group import create_group

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "group_id": "group-guid-456",
            "group_name": "MyGroup",
            "object_count": 2
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = create_group(ctx, object_ids=["obj1", "obj2"], name="MyGroup")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["group_name"] == "MyGroup"


class TestCreateGroupErrors:
    """Tests for create_group error handling."""

    @patch("rhinoclaw.tools.create_group.get_rhino_connection")
    def test_rhino_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.create_group import create_group

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Object not found")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = create_group(ctx, object_ids=["invalid-id"])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]
        assert "not found" in parsed["message"]

    @patch("rhinoclaw.tools.create_group.get_rhino_connection")
    def test_connection_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.create_group import create_group

        mock_get_conn.side_effect = Exception("Connection refused")

        ctx = MagicMock()
        result = create_group(ctx, object_ids=["obj1", "obj2"])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "refused" in parsed["message"].lower()