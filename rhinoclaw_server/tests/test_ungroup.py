"""
Tests for the ungroup tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestUngroupValidation:
    """Tests for ungroup parameter validation."""

    @patch("rhinoclaw.tools.ungroup.get_rhino_connection")
    def test_missing_group_id(self, mock_get_conn):
        from rhinoclaw.tools.ungroup import ungroup

        ctx = MagicMock()
        result = ungroup(ctx, group_id="")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]

    @patch("rhinoclaw.tools.ungroup.get_rhino_connection")
    def test_none_group_id(self, mock_get_conn):
        from rhinoclaw.tools.ungroup import ungroup

        ctx = MagicMock()
        result = ungroup(ctx, group_id=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]


class TestUngroupSuccess:
    """Tests for successful ungrouping."""

    @patch("rhinoclaw.tools.ungroup.get_rhino_connection")
    def test_ungroup_success(self, mock_get_conn):
        from rhinoclaw.tools.ungroup import ungroup

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "group_id": "group-guid-123",
            "object_ids": ["obj1", "obj2", "obj3"],
            "object_count": 3
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = ungroup(ctx, group_id="group-guid-123")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Ungrouped objects" in parsed["message"]
        assert parsed["data"]["object_ids"] == ["obj1", "obj2", "obj3"]
        assert parsed["data"]["object_count"] == 3

        mock_rhino.send_command.assert_called_once_with("ungroup", {
            "group_id": "group-guid-123"
        })


class TestUngroupErrors:
    """Tests for ungroup error handling."""

    @patch("rhinoclaw.tools.ungroup.get_rhino_connection")
    def test_rhino_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.ungroup import ungroup

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Group not found")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = ungroup(ctx, group_id="invalid-group")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]
        assert "not found" in parsed["message"]

    @patch("rhinoclaw.tools.ungroup.get_rhino_connection")
    def test_connection_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.ungroup import ungroup

        mock_get_conn.side_effect = Exception("Connection refused")

        ctx = MagicMock()
        result = ungroup(ctx, group_id="group-123")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "refused" in parsed["message"].lower()