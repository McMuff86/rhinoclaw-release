"""
Tests for mesh_from_brep tool.
"""
import json
import pytest
from unittest.mock import Mock, patch

from rhinoclaw.tools.mesh_from_brep import mesh_from_brep


class TestMeshFromBrep:
    """Test mesh_from_brep tool functionality."""

    def test_mesh_from_brep_basic(self, mock_rhino_response):
        """Test basic Brep to mesh conversion."""
        with patch('rhinoclaw.tools.mesh_from_brep.get_rhino_connection') as mock_conn:
            mock_rhino = Mock()
            mock_rhino.send_command.return_value = mock_rhino_response
            mock_conn.return_value = mock_rhino

            object_ids = ["brep1", "brep2"]
            result = mesh_from_brep(None, object_ids=object_ids)

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is True
            assert "Converted 2 Brep objects to mesh" in result_data["message"]

            # Verify command was called with correct parameters
            mock_rhino.send_command.assert_called_once_with("mesh_from_brep", {
                "object_ids": object_ids,
                "density": "normal",
                "quality": "normal",
                "max_edge_length": None,
                "min_edge_length": None
            })

    def test_mesh_from_brep_custom_density_quality(self, mock_rhino_response):
        """Test Brep to mesh conversion with custom density and quality."""
        with patch('rhinoclaw.tools.mesh_from_brep.get_rhino_connection') as mock_conn:
            mock_rhino = Mock()
            mock_rhino.send_command.return_value = mock_rhino_response
            mock_conn.return_value = mock_rhino

            object_ids = ["brep1"]
            result = mesh_from_brep(None, object_ids=object_ids, density="fine", quality="accurate")

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is True

            mock_rhino.send_command.assert_called_once_with("mesh_from_brep", {
                "object_ids": object_ids,
                "density": "fine",
                "quality": "accurate",
                "max_edge_length": None,
                "min_edge_length": None
            })

    def test_mesh_from_brep_custom_edge_lengths(self, mock_rhino_response):
        """Test Brep to mesh conversion with custom edge length constraints."""
        with patch('rhinoclaw.tools.mesh_from_brep.get_rhino_connection') as mock_conn:
            mock_rhino = Mock()
            mock_rhino.send_command.return_value = mock_rhino_response
            mock_conn.return_value = mock_rhino

            object_ids = ["brep1", "brep2", "brep3"]
            result = mesh_from_brep(None, object_ids=object_ids, max_edge_length=0.1, min_edge_length=0.01)

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is True

            mock_rhino.send_command.assert_called_once_with("mesh_from_brep", {
                "object_ids": object_ids,
                "density": "normal",
                "quality": "normal",
                "max_edge_length": 0.1,
                "min_edge_length": 0.01
            })

    def test_mesh_from_brep_empty_object_ids(self):
        """Test error handling for empty object_ids."""
        result = mesh_from_brep(None, object_ids=[])

        assert result is not None
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "At least one object_id is required" in result_data["message"]

    def test_mesh_from_brep_none_object_ids(self):
        """Test error handling for None object_ids."""
        result = mesh_from_brep(None, object_ids=None)

        assert result is not None
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "At least one object_id is required" in result_data["message"]

    def test_mesh_from_brep_connection_error(self):
        """Test error handling for connection failure."""
        with patch('rhinoclaw.tools.mesh_from_brep.get_rhino_connection') as mock_conn:
            mock_conn.side_effect = Exception("Connection failed")

            object_ids = ["brep1"]
            result = mesh_from_brep(None, object_ids=object_ids)

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is False
            assert result_data["code"] == "RHINO_ERROR"