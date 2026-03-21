"""
Tests for the create_block tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestCreateBlockValidation:
    """Tests for create_block parameter validation."""

    @patch("rhinoclaw.tools.create_block.get_rhino_connection")
    def test_missing_name(self, mock_get_conn):
        from rhinoclaw.tools.create_block import create_block

        ctx = MagicMock()
        result = create_block(ctx, name="", object_ids=["obj1"], base_point=[0, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]

    @patch("rhinoclaw.tools.create_block.get_rhino_connection")
    def test_missing_object_ids(self, mock_get_conn):
        from rhinoclaw.tools.create_block import create_block

        ctx = MagicMock()
        result = create_block(ctx, name="TestBlock", object_ids=[], base_point=[0, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]

    @patch("rhinoclaw.tools.create_block.get_rhino_connection")
    def test_invalid_base_point(self, mock_get_conn):
        from rhinoclaw.tools.create_block import create_block

        ctx = MagicMock()
        result = create_block(ctx, name="TestBlock", object_ids=["obj1"], base_point=[0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]


class TestCreateBlockSuccess:
    """Tests for successful block creation."""

    @patch("rhinoclaw.tools.create_block.get_rhino_connection")
    def test_create_block_success(self, mock_get_conn):
        from rhinoclaw.tools.create_block import create_block

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "block_id": "block-guid-123",
            "block_name": "Chair",
            "object_count": 4
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = create_block(ctx, name="Chair", object_ids=["leg1", "leg2", "seat", "back"], base_point=[0, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Chair" in parsed["message"]
        assert parsed["data"]["block_id"] == "block-guid-123"
        assert parsed["data"]["object_count"] == 4

        mock_rhino.send_command.assert_called_once_with("create_block", {
            "name": "Chair",
            "object_ids": ["leg1", "leg2", "seat", "back"],
            "base_point": [0.0, 0.0, 0.0]
        })

    @patch("rhinoclaw.tools.create_block.get_rhino_connection")
    def test_create_block_with_custom_base_point(self, mock_get_conn):
        from rhinoclaw.tools.create_block import create_block

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "block_id": "block-guid-456",
            "block_name": "Table",
            "object_count": 2
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = create_block(ctx, name="Table", object_ids=["top", "legs"], base_point=[10, 20, 30])
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["block_name"] == "Table"


class TestCreateBlockErrors:
    """Tests for create_block error handling."""

    @patch("rhinoclaw.tools.create_block.get_rhino_connection")
    def test_rhino_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.create_block import create_block

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Object not found")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = create_block(ctx, name="TestBlock", object_ids=["invalid-id"], base_point=[0, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]
        assert "not found" in parsed["message"]

    @patch("rhinoclaw.tools.create_block.get_rhino_connection")
    def test_connection_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.create_block import create_block

        mock_get_conn.side_effect = Exception("Connection refused")

        ctx = MagicMock()
        result = create_block(ctx, name="TestBlock", object_ids=["obj1"], base_point=[0, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "refused" in parsed["message"].lower()