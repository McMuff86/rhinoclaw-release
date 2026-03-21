"""
Tests for import_mesh tool.
"""
import json
import pytest
from unittest.mock import Mock, patch

from rhinoclaw.tools.import_mesh import import_mesh


class TestImportMesh:
    """Test import_mesh tool functionality."""

    def test_import_mesh_obj_auto_detect(self, mock_rhino_response):
        """Test importing OBJ file with auto-detected format."""
        with patch('rhinoclaw.tools.import_mesh.get_rhino_connection') as mock_conn:
            mock_rhino = Mock()
            mock_rhino.send_command.return_value = mock_rhino_response
            mock_conn.return_value = mock_rhino

            result = import_mesh(None, file_path="C:/models/cube.obj")

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is True
            assert "Imported OBJ mesh file" in result_data["message"]

            # Verify command was called with correct parameters
            mock_rhino.send_command.assert_called_once_with("import_mesh", {
                "file_path": "C:/models/cube.obj",
                "format": "OBJ",
                "import_mode": "merge"
            })

    def test_import_mesh_stl_explicit_format(self, mock_rhino_response):
        """Test importing STL file with explicit format."""
        with patch('rhinoclaw.tools.import_mesh.get_rhino_connection') as mock_conn:
            mock_rhino = Mock()
            mock_rhino.send_command.return_value = mock_rhino_response
            mock_conn.return_value = mock_rhino

            result = import_mesh(None, file_path="C:/models/part.stl", format="STL")

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is True

            mock_rhino.send_command.assert_called_once_with("import_mesh", {
                "file_path": "C:/models/part.stl",
                "format": "STL",
                "import_mode": "merge"
            })

    def test_import_mesh_replace_mode(self, mock_rhino_response):
        """Test importing with replace mode."""
        with patch('rhinoclaw.tools.import_mesh.get_rhino_connection') as mock_conn:
            mock_rhino = Mock()
            mock_rhino.send_command.return_value = mock_rhino_response
            mock_conn.return_value = mock_rhino

            result = import_mesh(None, file_path="C:/models/model.3mf", import_mode="replace")

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is True

            mock_rhino.send_command.assert_called_once_with("import_mesh", {
                "file_path": "C:/models/model.3mf",
                "format": "3MF",
                "import_mode": "replace"
            })

    def test_import_mesh_unsupported_extension(self):
        """Test error handling for unsupported file extension."""
        result = import_mesh(None, file_path="C:/models/model.xyz")

        assert result is not None
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "Unsupported file extension" in result_data["message"]

    def test_import_mesh_missing_file_path(self):
        """Test error handling for missing file_path."""
        result = import_mesh(None, file_path="")

        assert result is not None
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "file_path is required" in result_data["message"]

    def test_import_mesh_connection_error(self):
        """Test error handling for connection failure."""
        with patch('rhinoclaw.tools.import_mesh.get_rhino_connection') as mock_conn:
            mock_conn.side_effect = Exception("Connection failed")

            result = import_mesh(None, file_path="C:/models/cube.obj")

            assert result is not None
            result_data = json.loads(result)
            assert result_data["success"] is False
            assert result_data["code"] == "RHINO_ERROR"