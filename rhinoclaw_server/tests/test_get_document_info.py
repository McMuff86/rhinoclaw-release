"""
Tests for the get_document_info tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestGetDocumentInfoSuccess:
    """Tests for successful document info retrieval."""

    @patch("rhinoclaw.tools.get_document_info.get_rhino_connection")
    def test_get_basic_info(self, mock_get_conn):
        from rhinoclaw.tools.get_document_info import get_document_info
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "meta_data": {
                "name": "TestDoc.3dm",
                "units": "Millimeters",
                "tolerance": 0.001
            },
            "object_count": 5,
            "layer_count": 3
        }
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = get_document_info(ctx)
        parsed = json.loads(result)
        
        assert "meta_data" in parsed or "TestDoc" in str(parsed)

    @patch("rhinoclaw.tools.get_document_info.get_rhino_connection")
    def test_get_empty_document(self, mock_get_conn):
        from rhinoclaw.tools.get_document_info import get_document_info
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "meta_data": {
                "name": None,
                "units": "Millimeters",
                "tolerance": 0.001
            },
            "object_count": 0,
            "objects": [],
            "layer_count": 1,
            "layers": [{"name": "Default"}]
        }
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = get_document_info(ctx)
        
        # Should not raise error for empty document
        assert result is not None


class TestGetDocumentInfoErrors:
    """Tests for error handling."""

    @patch("rhinoclaw.tools.get_document_info.get_rhino_connection")
    def test_connection_error(self, mock_get_conn):
        from rhinoclaw.tools.get_document_info import get_document_info
        
        mock_get_conn.side_effect = Exception("Connection refused")
        
        ctx = MagicMock()
        result = get_document_info(ctx)
        parsed = json.loads(result)
        
        assert parsed["success"] is False
        assert "refused" in parsed["message"].lower()

    @patch("rhinoclaw.tools.get_document_info.get_rhino_connection")
    def test_rhino_error(self, mock_get_conn):
        from rhinoclaw.tools.get_document_info import get_document_info
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("No active document")
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = get_document_info(ctx)
        parsed = json.loads(result)
        
        assert parsed["success"] is False
