"""
Tests for the insert_block tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestInsertBlockValidation:
    """Tests for insert_block parameter validation."""

    @patch("rhinoclaw.tools.insert_block.get_rhino_connection")
    def test_missing_block_name(self, mock_get_conn):
        from rhinoclaw.tools.insert_block import insert_block

        ctx = MagicMock()
        result = insert_block(ctx, block_name="", position=[0, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]

    @patch("rhinoclaw.tools.insert_block.get_rhino_connection")
    def test_invalid_position(self, mock_get_conn):
        from rhinoclaw.tools.insert_block import insert_block

        ctx = MagicMock()
        result = insert_block(ctx, block_name="TestBlock", position=[0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]


class TestInsertBlockSuccess:
    """Tests for successful block insertion."""

    @patch("rhinoclaw.tools.insert_block.get_rhino_connection")
    def test_insert_block_success(self, mock_get_conn):
        from rhinoclaw.tools.insert_block import insert_block

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "instance_id": "instance-guid-123",
            "block_name": "Chair",
            "position": [10, 0, 0],
            "scale": [1, 1, 1],
            "rotation": [0, 0, 0]
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = insert_block(ctx, block_name="Chair", position=[10, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Chair" in parsed["message"]
        assert parsed["data"]["instance_id"] == "instance-guid-123"
        assert parsed["data"]["position"] == [10, 0, 0]

        mock_rhino.send_command.assert_called_once_with("insert_block", {
            "block_name": "Chair",
            "position": [10, 0, 0],
            "scale": [1.0, 1.0, 1.0],
            "rotation": [0.0, 0.0, 0.0]
        })

    @patch("rhinoclaw.tools.insert_block.get_rhino_connection")
    def test_insert_block_with_scale_and_rotation(self, mock_get_conn):
        from rhinoclaw.tools.insert_block import insert_block

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "instance_id": "instance-guid-456",
            "block_name": "Table",
            "position": [5, 5, 0],
            "scale": [2, 2, 2],
            "rotation": [0, 0, 45]
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = insert_block(ctx, block_name="Table", position=[5, 5, 0], scale=[2, 2, 2], rotation=[0, 0, 45])
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["scale"] == [2, 2, 2]
        assert parsed["data"]["rotation"] == [0, 0, 45]


class TestInsertBlockErrors:
    """Tests for insert_block error handling."""

    @patch("rhinoclaw.tools.insert_block.get_rhino_connection")
    def test_rhino_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.insert_block import insert_block

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Block definition not found")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = insert_block(ctx, block_name="NonExistentBlock", position=[0, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]
        assert "not found" in parsed["message"]

    @patch("rhinoclaw.tools.insert_block.get_rhino_connection")
    def test_connection_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.insert_block import insert_block

        mock_get_conn.side_effect = Exception("Connection refused")

        ctx = MagicMock()
        result = insert_block(ctx, block_name="TestBlock", position=[0, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "refused" in parsed["message"].lower()