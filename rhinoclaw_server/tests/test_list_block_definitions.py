"""Tests for the list_block_definitions tool."""
import json
from unittest.mock import MagicMock, patch


class TestListBlockDefinitionsSuccess:
    @patch("rhinoclaw.tools.list_block_definitions.get_rhino_connection")
    def test_defaults(self, mock_get_conn):
        from rhinoclaw.tools.list_block_definitions import list_block_definitions

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definitions": [
                {"name": "GLUTZ Topaz 5632C", "id": "guid-1",
                 "object_count": 12, "instance_count": 3},
            ],
            "count": 1,
            "total_count": 1,
            "truncated": False,
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = list_block_definitions(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["count"] == 1
        assert parsed["data"]["definitions"][0]["instance_count"] == 3
        # include_bbox defaults to False and name_filter is omitted entirely.
        mock_rhino.send_command.assert_called_once_with(
            "list_block_definitions", {"include_bbox": False})

    @patch("rhinoclaw.tools.list_block_definitions.get_rhino_connection")
    def test_name_filter_and_bbox_forwarded(self, mock_get_conn):
        from rhinoclaw.tools.list_block_definitions import list_block_definitions

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definitions": [], "count": 0, "total_count": 0, "truncated": False}
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        list_block_definitions(ctx, name_filter="glutz", include_bbox=True)

        mock_rhino.send_command.assert_called_once_with(
            "list_block_definitions",
            {"include_bbox": True, "name_filter": "glutz"})

    @patch("rhinoclaw.tools.list_block_definitions.get_rhino_connection")
    def test_truncated_hint_in_message(self, mock_get_conn):
        from rhinoclaw.tools.list_block_definitions import list_block_definitions

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "definitions": [{"name": f"B{i}"} for i in range(100)],
            "count": 100,
            "total_count": 250,
            "truncated": True,
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        parsed = json.loads(list_block_definitions(ctx))

        assert parsed["success"] is True
        assert "truncated" in parsed["message"]
        assert "name_filter" in parsed["message"]
        assert parsed["data"]["truncated"] is True


class TestListBlockDefinitionsErrors:
    @patch("rhinoclaw.tools.list_block_definitions.get_rhino_connection")
    def test_rhino_error(self, mock_get_conn):
        from rhinoclaw.tools.list_block_definitions import list_block_definitions

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("No active document")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        parsed = json.loads(list_block_definitions(ctx))

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]

    @patch("rhinoclaw.tools.list_block_definitions.get_rhino_connection")
    def test_connection_error(self, mock_get_conn):
        from rhinoclaw.tools.list_block_definitions import list_block_definitions

        mock_get_conn.side_effect = Exception("Connection refused")

        ctx = MagicMock()
        parsed = json.loads(list_block_definitions(ctx))

        assert parsed["success"] is False
        assert "refused" in parsed["message"].lower()
