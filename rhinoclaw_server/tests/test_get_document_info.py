"""
Tests for the get_document_info tool.
"""
import json
from pathlib import Path
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


def test_plugin_count_matches_the_serialized_non_phantom_scope():
    source = (
        Path(__file__).resolve().parents[2]
        / "rhinoclaw_plugin"
        / "Functions"
        / "GetDocumentInfo.cs"
    ).read_text()

    assert "int activeObjectCount = 0;" in source
    assert '["object_count"] = activeObjectCount' in source
    assert '["object_count_scope"] = "active_non_phantom_objects"' in source
    assert '["object_table_count"] = doc.Objects.Count' in source
    assert '["objects_truncated"] = activeObjectCount > LIMIT' in source
    assert '["object_count"] = doc.Objects.Count' not in source


def test_serializer_resolves_layers_from_the_current_document():
    """A _New/_Open must not leave object serialization on the old layer table."""
    root = Path(__file__).resolve().parents[2]
    serializer = (root / "rhinoclaw_plugin" / "Serializers" / "Serializer.cs").read_text()
    document_info = (
        root / "rhinoclaw_plugin" / "Functions" / "GetDocumentInfo.cs"
    ).read_text()

    assert "public static RhinoDoc doc" not in serializer
    assert "RhinoObject(RhinoObject obj, RhinoDoc doc)" in serializer
    assert "doc.Layers.FindIndex(obj.Attributes.LayerIndex)" in serializer
    assert 'string layerName = "(unassigned)";' in serializer
    assert "Serializer.RhinoObject(docObject, doc)" in document_info
