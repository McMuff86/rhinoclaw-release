"""
Tests for export_mesh tool.
"""
import json
import pytest
from unittest.mock import Mock, patch

from rhinoclaw.tools.export_mesh import export_mesh


class TestExportMesh:
    """Test export_mesh tool functionality."""

    def test_export_mesh_obj_all_objects(self, mock_rhino_response):
        """Test exporting all objects as OBJ."""
        with patch('rhinoclaw.tools.export_mesh.get_rhino_connection') as mock_conn:
            mock_rhino = Mock()
            mock_rhino.send_command.return_value = mock_rhino_response
            mock_conn.return_value = mock_rhino

            result = export_mesh(None, file_path="C:/export/model.obj", format="OBJ")

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is True
            assert "Exported mesh to OBJ format" in result_data["message"]

            # Verify command was called with correct parameters
            mock_rhino.send_command.assert_called_once_with("export_mesh", {
                "file_path": "C:/export/model.obj",
                "format": "OBJ",
                "object_ids": None,
                "mesh_options": None
            })

    def test_export_mesh_stl_specific_objects(self, mock_rhino_response):
        """Test exporting specific objects as STL."""
        with patch('rhinoclaw.tools.export_mesh.get_rhino_connection') as mock_conn:
            mock_rhino = Mock()
            mock_rhino.send_command.return_value = mock_rhino_response
            mock_conn.return_value = mock_rhino

            object_ids = ["obj1", "obj2"]
            result = export_mesh(None, file_path="C:/export/part.stl", format="STL", object_ids=object_ids)

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is True

            mock_rhino.send_command.assert_called_once_with("export_mesh", {
                "file_path": "C:/export/part.stl",
                "format": "STL",
                "object_ids": object_ids,
                "mesh_options": None
            })

    def test_export_mesh_with_options(self, mock_rhino_response):
        """Test exporting with mesh options."""
        with patch('rhinoclaw.tools.export_mesh.get_rhino_connection') as mock_conn:
            mock_rhino = Mock()
            mock_rhino.send_command.return_value = mock_rhino_response
            mock_conn.return_value = mock_rhino

            mesh_options = {"density": "fine", "quality": "accurate"}
            result = export_mesh(None, file_path="C:/export/model.3mf", format="3MF", mesh_options=mesh_options)

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is True

            mock_rhino.send_command.assert_called_once_with("export_mesh", {
                "file_path": "C:/export/model.3mf",
                "format": "3MF",
                "object_ids": None,
                "mesh_options": mesh_options
            })

    def test_export_mesh_unsupported_format(self):
        """Test error handling for unsupported format."""
        result = export_mesh(None, file_path="C:/export/model.xyz", format="XYZ")

        assert result is not None
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "Unsupported format" in result_data["message"]

    def test_export_mesh_missing_file_path(self):
        """Test error handling for missing file_path."""
        result = export_mesh(None, file_path="", format="OBJ")

        assert result is not None
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "file_path is required" in result_data["message"]

    def test_export_mesh_missing_format(self):
        """Test error handling for missing format."""
        result = export_mesh(None, file_path="C:/export/model.obj", format="")

        assert result is not None
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "format is required" in result_data["message"]

    def test_export_mesh_connection_error(self):
        """Test error handling for connection failure."""
        with patch('rhinoclaw.tools.export_mesh.get_rhino_connection') as mock_conn:
            mock_conn.side_effect = Exception("Connection failed")

            result = export_mesh(None, file_path="C:/export/model.obj", format="OBJ")

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is False
            assert result_data["code"] == "RHINO_ERROR"