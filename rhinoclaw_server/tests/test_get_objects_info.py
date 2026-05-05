"""Tests for the get_objects_info bulk tool."""
import json
from unittest.mock import MagicMock, patch


class TestGetObjectsInfo:
    @patch("rhinoclaw.tools.get_objects_info.get_rhino_connection")
    def test_bulk_resolution(self, mock_get_conn):
        from rhinoclaw.tools.get_objects_info import get_objects_info
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "count": 2, "missing_count": 0,
            "results": [
                {"id": "g1", "name": "BoxA", "type": "Brep"},
                {"id": "g2", "name": "BoxB", "type": "Brep"},
            ],
            "missing": [],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = get_objects_info(ctx, ids=["g1", "g2"])
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["count"] == 2
        assert "Resolved 2 of 2" in parsed["message"]
        mock_rhino.send_command.assert_called_once_with(
            "get_objects_info", {"ids": ["g1", "g2"]}
        )

    @patch("rhinoclaw.tools.get_objects_info.get_rhino_connection")
    def test_partial_missing(self, mock_get_conn):
        from rhinoclaw.tools.get_objects_info import get_objects_info
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "count": 1, "missing_count": 1,
            "results": [{"id": "g1", "name": "BoxA"}],
            "missing": [{"id": "bogus", "reason": "invalid_guid"}],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = get_objects_info(ctx, ids=["g1", "bogus"])
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "1 missing" in parsed["message"]
        assert parsed["data"]["missing"][0]["reason"] == "invalid_guid"

    def test_empty_list_rejected(self):
        from rhinoclaw.tools.get_objects_info import get_objects_info
        ctx = MagicMock()
        result = get_objects_info(ctx, ids=[])
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"
