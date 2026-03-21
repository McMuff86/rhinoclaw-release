"""
Tests for the explode_block tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestExplodeBlockValidation:
    """Tests for explode_block parameter validation."""

    @patch("rhinoclaw.tools.explode_block.get_rhino_connection")
    def test_missing_instance_id(self, mock_get_conn):
        from rhinoclaw.tools.explode_block import explode_block

        ctx = MagicMock()
        result = explode_block(ctx, instance_id="")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]

    @patch("rhinoclaw.tools.explode_block.get_rhino_connection")
    def test_none_instance_id(self, mock_get_conn):
        from rhinoclaw.tools.explode_block import explode_block

        ctx = MagicMock()
        result = explode_block(ctx, instance_id=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]


class TestExplodeBlockSuccess:
    """Tests for successful block explosion."""

    @patch("rhinoclaw.tools.explode_block.get_rhino_connection")
    def test_explode_block_success(self, mock_get_conn):
        from rhinoclaw.tools.explode_block import explode_block

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "instance_id": "instance-guid-123",
            "object_ids": ["obj1", "obj2", "obj3", "obj4"],
            "object_count": 4
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = explode_block(ctx, instance_id="instance-guid-123")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Exploded block instance" in parsed["message"]
        assert parsed["data"]["object_ids"] == ["obj1", "obj2", "obj3", "obj4"]
        assert parsed["data"]["object_count"] == 4

        mock_rhino.send_command.assert_called_once_with("explode_block", {
            "instance_id": "instance-guid-123"
        })


class TestExplodeBlockErrors:
    """Tests for explode_block error handling."""

    @patch("rhinoclaw.tools.explode_block.get_rhino_connection")
    def test_rhino_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.explode_block import explode_block

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Block instance not found")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = explode_block(ctx, instance_id="invalid-instance")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]
        assert "not found" in parsed["message"]

    @patch("rhinoclaw.tools.explode_block.get_rhino_connection")
    def test_connection_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.explode_block import explode_block

        mock_get_conn.side_effect = Exception("Connection refused")

        ctx = MagicMock()
        result = explode_block(ctx, instance_id="instance-123")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "refused" in parsed["message"].lower()