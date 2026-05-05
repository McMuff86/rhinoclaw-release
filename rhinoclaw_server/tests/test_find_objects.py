"""Tests for the find_objects MCP tool."""
import json
from unittest.mock import MagicMock, patch


class TestFindObjects:
    @patch("rhinoclaw.tools.find_objects.get_rhino_connection")
    def test_layer_and_type_filter(self, mock_get_conn):
        from rhinoclaw.tools.find_objects import find_objects
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "count": 2, "scanned": 47, "limit": 500, "truncated": False,
            "results": [
                {"id": "g1", "name": "Wall_A", "layer": "Walls",
                 "type": "Brep", "center": [1, 2, 1.25], "volume": 12.5},
                {"id": "g2", "name": "Wall_B", "layer": "Walls",
                 "type": "Brep", "center": [4, 2, 1.25], "volume": 12.5},
            ],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = find_objects(ctx, layer="Walls", type="Brep", min_volume=1.0)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Matched 2 of 47" in parsed["message"]
        sent = mock_rhino.send_command.call_args[0][1]
        assert sent["layer"] == "Walls"
        assert sent["type"] == "Brep"
        assert sent["min_volume"] == 1.0
        assert sent["limit"] == 500

    @patch("rhinoclaw.tools.find_objects.get_rhino_connection")
    def test_omits_unset_filters(self, mock_get_conn):
        """No-args call must NOT send any filter keys, only `limit`."""
        from rhinoclaw.tools.find_objects import find_objects
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "count": 0, "scanned": 0, "limit": 500, "truncated": False, "results": [],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        find_objects(ctx)

        sent = mock_rhino.send_command.call_args[0][1]
        assert sent == {"limit": 500}

    @patch("rhinoclaw.tools.find_objects.get_rhino_connection")
    def test_aabb_filter(self, mock_get_conn):
        from rhinoclaw.tools.find_objects import find_objects
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "count": 0, "scanned": 0, "limit": 500, "truncated": False, "results": [],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        find_objects(ctx, min_x=0, max_x=10, min_z=0, max_z=2.5)

        sent = mock_rhino.send_command.call_args[0][1]
        assert sent["min_x"] == 0
        assert sent["max_x"] == 10
        assert sent["min_z"] == 0
        assert sent["max_z"] == 2.5
        assert "min_y" not in sent
        assert "max_y" not in sent

    @patch("rhinoclaw.tools.find_objects.get_rhino_connection")
    def test_truncation_flag_surfaced(self, mock_get_conn):
        from rhinoclaw.tools.find_objects import find_objects
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "count": 50, "scanned": 200, "limit": 50, "truncated": True,
            "results": [{"id": f"g{i}"} for i in range(50)],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = find_objects(ctx, limit=50)
        parsed = json.loads(result)
        assert parsed["data"]["truncated"] is True
        assert parsed["data"]["count"] == 50

    @patch("rhinoclaw.tools.find_objects.get_rhino_connection")
    def test_error_propagates(self, mock_get_conn):
        from rhinoclaw.tools.find_objects import find_objects
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Invalid name_regex: ...")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = find_objects(ctx, name_regex="[")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "regex" in parsed["message"]
