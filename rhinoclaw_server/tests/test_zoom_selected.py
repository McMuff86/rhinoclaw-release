"""
Tests for the zoom_selected tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestZoomSelectedValidation:
    """Tests for zoom_selected parameter validation."""

    @patch("rhinoclaw.tools.zoom_selected.get_rhino_connection")
    def test_empty_object_ids_list(self, mock_get_conn):
        from rhinoclaw.tools.zoom_selected import zoom_selected

        ctx = MagicMock()
        result = zoom_selected(ctx, object_ids=[])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]


class TestZoomSelectedSuccess:
    """Tests for successful zoom_selected operations."""

    @patch("rhinoclaw.tools.zoom_selected.get_rhino_connection")
    def test_zoom_selected_objects(self, mock_get_conn):
        from rhinoclaw.tools.zoom_selected import zoom_selected

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        object_ids = ["id1", "id2"]
        result = zoom_selected(ctx, object_ids=object_ids)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "selected" in parsed["message"]
        mock_conn.send_command.assert_called_once_with("zoom_selected", {
            "object_ids": object_ids,
            "viewport_name": "Perspective"
        })

    @patch("rhinoclaw.tools.zoom_selected.get_rhino_connection")
    def test_zoom_selected_no_objects(self, mock_get_conn):
        from rhinoclaw.tools.zoom_selected import zoom_selected

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = zoom_selected(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_conn.send_command.assert_called_once_with("zoom_selected", {
            "object_ids": None,
            "viewport_name": "Perspective"
        })

    @patch("rhinoclaw.tools.zoom_selected.get_rhino_connection")
    def test_zoom_selected_custom_viewport(self, mock_get_conn):
        from rhinoclaw.tools.zoom_selected import zoom_selected

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = zoom_selected(ctx, object_ids=["id1"], viewport_name="Top")
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_conn.send_command.assert_called_once_with("zoom_selected", {
            "object_ids": ["id1"],
            "viewport_name": "Top"
        })


class TestZoomSelectedError:
    """Tests for zoom_selected error handling."""

    @patch("rhinoclaw.tools.zoom_selected.get_rhino_connection")
    def test_rhino_connection_error(self, mock_get_conn):
        from rhinoclaw.tools.zoom_selected import zoom_selected

        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = Exception("Connection failed")
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = zoom_selected(ctx, object_ids=["id1"])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]