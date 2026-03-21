"""Tests for WebSocket client."""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from rhinoclaw.websocket_client import (
    RhinoWebSocketClient,
    WebSocketEvent,
    get_websocket_client,
    reset_websocket_client,
)


@pytest.fixture
def ws_client():
    """Create a fresh WebSocket client for each test."""
    reset_websocket_client()
    return RhinoWebSocketClient(host="127.0.0.1", port=2000)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton client before and after each test."""
    reset_websocket_client()
    yield
    reset_websocket_client()


class TestWebSocketEvent:
    """Tests for WebSocketEvent dataclass."""

    def test_from_json_prompt(self):
        """Test creating event from Prompt JSON."""
        data = {
            "type": "Prompt",
            "text": "Pick a point",
            "timestamp": "2026-01-11 14:30:00.123"
        }
        event = WebSocketEvent.from_json(data)
        
        assert event.event_type == "Prompt"
        assert event.text == "Pick a point"
        assert event.timestamp == "2026-01-11 14:30:00.123"
        assert event.raw == data

    def test_from_json_history(self):
        """Test creating event from History JSON."""
        data = {
            "type": "History",
            "text": "Box created",
            "timestamp": "2026-01-11 14:30:01.456"
        }
        event = WebSocketEvent.from_json(data)
        
        assert event.event_type == "History"
        assert event.text == "Box created"

    def test_from_json_missing_fields(self):
        """Test creating event with missing fields uses defaults."""
        data = {"type": "Heartbeat"}
        event = WebSocketEvent.from_json(data)
        
        assert event.event_type == "Heartbeat"
        assert event.text == ""
        # Timestamp should have a value (generated if missing)
        assert event.timestamp is not None


class TestRhinoWebSocketClient:
    """Tests for RhinoWebSocketClient."""

    def test_init_defaults(self, ws_client):
        """Test client initializes with correct defaults."""
        assert ws_client.host == "127.0.0.1"
        assert ws_client.port == 2000
        assert ws_client.url == "ws://127.0.0.1:2000"
        assert ws_client.max_buffer_size == 500
        assert not ws_client.is_connected
        assert ws_client.event_count == 0

    def test_init_custom_values(self):
        """Test client with custom values."""
        client = RhinoWebSocketClient(
            host="192.168.1.1",
            port=3000,
            max_buffer_size=100
        )
        assert client.url == "ws://192.168.1.1:3000"
        assert client.max_buffer_size == 100

    def test_not_connected_initially(self, ws_client):
        """Test that client is not connected initially."""
        assert not ws_client.is_connected
        assert ws_client._websocket is None

    def test_handle_event_prompt(self, ws_client):
        """Test handling Prompt event."""
        event = WebSocketEvent(
            event_type="Prompt",
            text="Pick a point",
            timestamp="2026-01-11 14:30:00.123",
            raw={}
        )
        
        ws_client._handle_event(event)
        
        assert ws_client.current_prompt == "Pick a point"
        assert ws_client.event_count == 1

    def test_handle_event_history(self, ws_client):
        """Test handling History event."""
        event = WebSocketEvent(
            event_type="History",
            text="Command completed",
            timestamp="2026-01-11 14:30:00.123",
            raw={}
        )
        
        ws_client._handle_event(event)
        
        # History doesn't update prompt
        assert ws_client.current_prompt == ""
        # But it's added to buffer
        assert ws_client.event_count == 1

    def test_handle_event_heartbeat_not_buffered(self, ws_client):
        """Test that Heartbeat events are not buffered."""
        event = WebSocketEvent(
            event_type="Heartbeat",
            text="",
            timestamp="2026-01-11 14:30:00.123",
            raw={}
        )
        
        ws_client._handle_event(event)
        
        # Heartbeat should not be in buffer
        assert ws_client.event_count == 0

    def test_buffer_max_size(self, ws_client):
        """Test buffer respects max size."""
        # Set small buffer size
        ws_client._event_buffer = ws_client._event_buffer.__class__(maxlen=3)
        
        # Add 5 events
        for i in range(5):
            event = WebSocketEvent(
                event_type="History",
                text=f"Event {i}",
                timestamp=f"2026-01-11 14:30:0{i}.000",
                raw={}
            )
            ws_client._handle_event(event)
        
        # Should only have last 3 events
        assert ws_client.event_count == 3
        events = ws_client.get_buffered_events()
        assert events[0].text == "Event 2"
        assert events[2].text == "Event 4"

    def test_get_buffered_events_all(self, ws_client):
        """Test getting all buffered events."""
        for i in range(3):
            event = WebSocketEvent(
                event_type="History",
                text=f"Event {i}",
                timestamp=f"2026-01-11 14:30:0{i}.000",
                raw={}
            )
            ws_client._handle_event(event)
        
        events = ws_client.get_buffered_events()
        
        assert len(events) == 3
        assert ws_client.event_count == 3  # Not cleared

    def test_get_buffered_events_with_count(self, ws_client):
        """Test getting limited number of events."""
        for i in range(5):
            event = WebSocketEvent(
                event_type="History",
                text=f"Event {i}",
                timestamp=f"2026-01-11 14:30:0{i}.000",
                raw={}
            )
            ws_client._handle_event(event)
        
        events = ws_client.get_buffered_events(count=2)
        
        assert len(events) == 2
        # Should get the last 2
        assert events[0].text == "Event 3"
        assert events[1].text == "Event 4"

    def test_get_buffered_events_clear(self, ws_client):
        """Test clearing events when retrieving."""
        for i in range(3):
            event = WebSocketEvent(
                event_type="History",
                text=f"Event {i}",
                timestamp=f"2026-01-11 14:30:0{i}.000",
                raw={}
            )
            ws_client._handle_event(event)
        
        events = ws_client.get_buffered_events(clear=True)
        
        assert len(events) == 3
        assert ws_client.event_count == 0  # Buffer cleared

    def test_clear_buffer(self, ws_client):
        """Test clearing the event buffer."""
        for i in range(3):
            event = WebSocketEvent(
                event_type="History",
                text=f"Event {i}",
                timestamp=f"2026-01-11 14:30:0{i}.000",
                raw={}
            )
            ws_client._handle_event(event)
        
        assert ws_client.event_count == 3
        
        ws_client.clear_buffer()
        
        assert ws_client.event_count == 0

    def test_callback_add_remove(self, ws_client):
        """Test adding and removing callbacks."""
        received = []
        
        def callback(event):
            received.append(event)
        
        ws_client.add_callback(callback)
        
        event = WebSocketEvent(
            event_type="History",
            text="Test",
            timestamp="2026-01-11 14:30:00.000",
            raw={}
        )
        ws_client._handle_event(event)
        
        assert len(received) == 1
        
        ws_client.remove_callback(callback)
        ws_client._handle_event(event)
        
        # Should still be 1 (callback removed)
        assert len(received) == 1


class TestSingletonClient:
    """Tests for singleton WebSocket client."""

    def test_get_websocket_client_creates_new(self):
        """Test get_websocket_client creates new instance."""
        client = get_websocket_client()
        
        assert client is not None
        assert isinstance(client, RhinoWebSocketClient)

    def test_get_websocket_client_returns_same(self):
        """Test get_websocket_client returns same instance."""
        client1 = get_websocket_client()
        client2 = get_websocket_client()
        
        assert client1 is client2

    def test_reset_websocket_client(self):
        """Test reset_websocket_client clears singleton."""
        client1 = get_websocket_client()
        reset_websocket_client()
        client2 = get_websocket_client()
        
        assert client1 is not client2
