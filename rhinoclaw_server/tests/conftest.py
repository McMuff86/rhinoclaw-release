"""
Pytest configuration and shared fixtures for RhinoClaw tests.
"""
import pytest
from unittest.mock import Mock, MagicMock
import socket


@pytest.fixture
def mock_socket():
    """Create a mock socket for testing connection logic."""
    mock = MagicMock(spec=socket.socket)
    mock.recv.return_value = b'{"status": "ok", "result": {"test": "data"}}'
    return mock


@pytest.fixture
def mock_rhino_response():
    """Standard successful Rhino response."""
    return {
        "status": "ok",
        "result": {
            "name": "TestObject",
            "id": "12345678-1234-1234-1234-123456789abc"
        }
    }


@pytest.fixture
def mock_rhino_error_response():
    """Standard error Rhino response."""
    return {
        "status": "error",
        "message": "Test error message"
    }
