"""
Tests for RhinoConnection class in rhinoclaw.server module.
"""
import pytest
from unittest.mock import patch, MagicMock
import socket
import json

from rhinoclaw.server import RhinoConnection


class TestRhinoConnectionInit:
    """Tests for RhinoConnection initialization."""

    def test_default_values(self):
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        assert conn.host == "127.0.0.1"
        assert conn.port == 1999
        assert conn.sock is None
        assert conn.max_retries == 3
        assert conn.retry_delay == 1.0


class TestIsConnected:
    """Tests for is_connected() method."""

    def test_not_connected_when_socket_none(self):
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        assert conn.is_connected() is False

    def test_connected_with_active_socket(self):
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recv.side_effect = BlockingIOError()
        conn.sock = mock_sock
        
        assert conn.is_connected() is True
        mock_sock.setblocking.assert_called()

    def test_not_connected_when_socket_closed(self):
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recv.return_value = b''
        conn.sock = mock_sock
        
        assert conn.is_connected() is False


class TestConnect:
    """Tests for connect() method."""

    def test_connect_already_connected(self):
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        conn.sock = MagicMock(spec=socket.socket)
        
        result = conn.connect()
        assert result is True

    @patch('socket.socket')
    def test_connect_success(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        result = conn.connect()
        
        assert result is True
        assert conn.sock is mock_sock
        mock_sock.connect.assert_called_once_with(("127.0.0.1", 1999))

    @patch('socket.socket')
    def test_connect_failure(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError("Connection refused")
        mock_socket_class.return_value = mock_sock
        
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        result = conn.connect()
        
        assert result is False
        assert conn.sock is None


class TestDisconnect:
    """Tests for disconnect() method."""

    def test_disconnect_when_connected(self):
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        mock_sock = MagicMock(spec=socket.socket)
        conn.sock = mock_sock
        
        conn.disconnect()
        
        mock_sock.close.assert_called_once()
        assert conn.sock is None

    def test_disconnect_when_not_connected(self):
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        conn.disconnect()
        assert conn.sock is None


class TestReconnect:
    """Tests for reconnect() method."""

    @patch('socket.socket')
    @patch('time.sleep')
    def test_reconnect_success_first_attempt(self, mock_sleep, mock_socket_class):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        result = conn.reconnect()
        
        assert result is True
        mock_sleep.assert_not_called()

    @patch('socket.socket')
    @patch('time.sleep')
    def test_reconnect_success_second_attempt(self, mock_sleep, mock_socket_class):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = [ConnectionRefusedError(), None]
        mock_socket_class.return_value = mock_sock
        
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        result = conn.reconnect()
        
        assert result is True
        mock_sleep.assert_called_once_with(1.0)

    @patch('socket.socket')
    @patch('time.sleep')
    def test_reconnect_all_attempts_fail(self, mock_sleep, mock_socket_class):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError("refused")
        mock_socket_class.return_value = mock_sock
        
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        result = conn.reconnect(max_retries=2)
        
        assert result is False
        assert mock_sleep.call_count == 1

    @patch('socket.socket')
    @patch('time.sleep')
    def test_reconnect_custom_params(self, mock_sleep, mock_socket_class):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = [ConnectionRefusedError(), None]
        mock_socket_class.return_value = mock_sock
        
        conn = RhinoConnection(host="127.0.0.1", port=1999)
        result = conn.reconnect(max_retries=5, retry_delay=2.0)
        
        assert result is True
        mock_sleep.assert_called_once_with(2.0)
