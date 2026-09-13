"""Tests for WebSocket client."""

import asyncio
import json

import pytest

from rhinoclaw.config import reload_settings
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

    @pytest.mark.asyncio
    async def test_connect_starts_receiver_before_correlated_state_request(
        self,
        ws_client,
        monkeypatch,
    ):
        """connect() alone must make request/response APIs operational."""
        import websockets

        class QueueWebSocket:
            def __init__(self):
                self.messages = asyncio.Queue()
                self.messages.put_nowait(json.dumps({
                    "type": "Connected",
                    "current_prompt": "",
                }))

            async def recv(self):
                return await self.messages.get()

            async def send(self, message):
                request = json.loads(message)
                if request.get("command") == "get_state":
                    self.messages.put_nowait(json.dumps({
                        "type": "State",
                        "request_id": request["request_id"],
                        "current_prompt": "",
                        "in_command": 0,
                        "command_idle": True,
                        "command_stack": [],
                    }))

            async def close(self):
                return None

        websocket = QueueWebSocket()

        async def connect(*args, **kwargs):
            return websocket

        monkeypatch.setattr(websockets, "connect", connect)

        assert await ws_client.connect() is True
        assert ws_client._running is True
        assert ws_client._listen_task is not None
        try:
            assert await ws_client.get_state(timeout=0.2) == {
                "current_prompt": "",
                "in_command": 0,
                "command_idle": True,
                "command_stack": [],
            }
        finally:
            await ws_client.disconnect()

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

    async def test_get_state_captures_first_state_emitted_during_send(
        self,
        ws_client,
    ):
        """An immediate State response is captured exactly once."""

        class ImmediateStateWebSocket:
            callback_count_during_send = None
            payload = None

            async def send(self, message):
                self.payload = json.loads(message)
                self.callback_count_during_send = len(ws_client._callbacks)
                for raw in (
                    {
                        "type": "State",
                        "request_id": "mismatched-request",
                        "current_prompt": "Stale",
                        "in_command": 9,
                        "command_idle": False,
                        "command_stack": ["Stale"],
                    },
                    {
                        "type": "State",
                        "request_id": self.payload["request_id"],
                        "current_prompt": "Command:",
                        "in_command": 0,
                        "command_idle": True,
                        "command_stack": [],
                    },
                    {
                        "type": "State",
                        "request_id": self.payload["request_id"],
                        "current_prompt": "Later state must be ignored",
                        "in_command": 1,
                        "command_idle": False,
                        "command_stack": ["Later"],
                    },
                ):
                    ws_client._handle_event(WebSocketEvent(
                        event_type="State",
                        text="",
                        timestamp="2026-08-16T00:00:00",
                        raw=raw,
                    ))

        websocket = ImmediateStateWebSocket()
        ws_client._websocket = websocket
        ws_client._connected = True

        result = await asyncio.wait_for(
            ws_client.get_state(timeout=10.0),
            timeout=0.2,
        )

        assert result == {
            "current_prompt": "Command:",
            "in_command": 0,
            "command_idle": True,
            "command_stack": [],
        }
        assert websocket.payload["command"] == "get_state"
        assert isinstance(websocket.payload["request_id"], str)
        assert websocket.callback_count_during_send == 1
        assert ws_client._callbacks == []

    async def test_get_state_rejects_malformed_typed_state(self, ws_client):
        """A matching but malformed state response fails closed."""

        class MalformedStateWebSocket:
            async def send(self, message):
                payload = json.loads(message)
                ws_client._handle_event(WebSocketEvent(
                    event_type="State",
                    text="",
                    timestamp="2026-08-16T00:00:00",
                    raw={
                        "type": "State",
                        "request_id": payload["request_id"],
                        "current_prompt": None,
                        "in_command": "0",
                        "command_idle": True,
                        "command_stack": [],
                    },
                ))

        ws_client._websocket = MalformedStateWebSocket()
        ws_client._connected = True

        assert await ws_client.get_state(timeout=0.2) is None
        assert ws_client._callbacks == []

    async def test_get_state_cleans_callback_when_send_fails(self, ws_client):
        """A get_state send exception must remove its response callback."""

        class FailingWebSocket:
            async def send(self, message):
                raise RuntimeError("send failed")

        ws_client._websocket = FailingWebSocket()
        ws_client._connected = True

        result = await ws_client.get_state()

        assert result is None
        assert ws_client._callbacks == []

    async def test_get_state_cleans_callback_after_timeout(self, ws_client):
        """A missing State response must time out without leaking a callback."""

        class SilentWebSocket:
            async def send(self, message):
                return None

        ws_client._websocket = SilentWebSocket()
        ws_client._connected = True

        result = await ws_client.get_state(timeout=0.001)

        assert result is None
        assert ws_client._callbacks == []

    async def test_wait_for_command_idle_observes_active_then_idle(
        self,
        ws_client,
    ):
        """Delayed start cannot be mistaken for command completion."""
        states = iter([
            {"current_prompt": "", "in_command": 0,
             "command_idle": True, "command_stack": []},
            {"current_prompt": "Startpunkt", "in_command": 1,
             "command_idle": False, "command_stack": ["vaWall"]},
            {"current_prompt": "", "in_command": 1,
             "command_idle": False, "command_stack": ["vaWall"]},
            {"current_prompt": "Command", "in_command": 0,
             "command_idle": True, "command_stack": []},
        ])

        async def next_state(timeout):
            del timeout
            return next(states)

        ws_client.get_state = next_state
        result = await ws_client.wait_for_command_idle(
            timeout=0.2,
            poll_interval=0.001,
            require_observed_active=True,
        )

        assert result is not None
        assert result["in_command"] == 0

    async def test_wait_for_command_idle_times_out_while_active(
        self,
        ws_client,
    ):
        """A blank prompt with positive command depth never passes."""

        async def active_state(timeout):
            del timeout
            return {
                "current_prompt": "",
                "in_command": 1,
                "command_idle": False,
                "command_stack": ["vaWall"],
            }

        ws_client.get_state = active_state
        result = await ws_client.wait_for_command_idle(
            timeout=0.01,
            poll_interval=0.001,
        )

        assert result is None

    async def test_run_script_captures_completion_emitted_during_send(
        self,
        ws_client,
    ):
        """A completion delivered by send itself must not be lost."""

        class ImmediateCompletionWebSocket:
            callback_count_during_send = None

            async def send(self, message):
                payload = json.loads(message)
                self.callback_count_during_send = len(ws_client._callbacks)
                ws_client._handle_event(WebSocketEvent(
                    event_type="ScriptCompleted",
                    text="",
                    timestamp="2026-08-16T00:00:00",
                    raw={
                        "type": "ScriptCompleted",
                        "request_id": payload["request_id"],
                        "success": True,
                    },
                ))

        websocket = ImmediateCompletionWebSocket()
        ws_client._websocket = websocket
        ws_client._connected = True

        result = await asyncio.wait_for(
            ws_client.run_script(
                "_-Echo test",
                wait_for_completion=True,
                timeout=10.0,
            ),
            timeout=0.2,
        )

        assert result is True
        assert websocket.callback_count_during_send == 1
        assert ws_client._callbacks == []

    async def test_run_script_without_completion_waits_for_started_ack(
        self,
        ws_client,
    ):
        """Non-blocking mode proves server acceptance, not just frame send."""

        class ImmediateStartedWebSocket:
            callback_count_during_send = None

            async def send(self, message):
                payload = json.loads(message)
                self.callback_count_during_send = len(ws_client._callbacks)
                ws_client._handle_event(WebSocketEvent(
                    event_type="ScriptStarted",
                    text="",
                    timestamp="2026-08-16T00:00:00",
                    raw={
                        "type": "ScriptStarted",
                        "request_id": payload["request_id"],
                    },
                ))

        websocket = ImmediateStartedWebSocket()
        ws_client._websocket = websocket
        ws_client._connected = True

        result = await ws_client.run_script(
            "_-Echo test",
            wait_for_completion=False,
            timeout=0.2,
        )

        assert result is True
        assert websocket.callback_count_during_send == 1
        assert ws_client._callbacks == []

    async def test_run_script_without_completion_rejects_silent_server(
        self,
        ws_client,
    ):
        """A sent frame without ScriptStarted is not a started command."""

        class SilentWebSocket:
            async def send(self, message):
                del message

        ws_client._websocket = SilentWebSocket()
        ws_client._connected = True

        result = await ws_client.run_script(
            "_-Echo test",
            wait_for_completion=False,
            timeout=0.001,
        )

        assert result is False
        assert ws_client._callbacks == []

    async def test_run_script_cleans_callback_after_immediate_script_error(
        self,
        ws_client,
    ):
        """A matching ScriptError completes promptly and removes its callback."""

        class ImmediateErrorWebSocket:
            async def send(self, message):
                payload = json.loads(message)
                ws_client._handle_event(WebSocketEvent(
                    event_type="ScriptError",
                    text="script failed",
                    timestamp="2026-08-16T00:00:00",
                    raw={
                        "type": "ScriptError",
                        "request_id": payload["request_id"],
                        "success": False,
                    },
                ))

        ws_client._websocket = ImmediateErrorWebSocket()
        ws_client._connected = True

        result = await asyncio.wait_for(
            ws_client.run_script(
                "_-FailForTest",
                wait_for_completion=True,
                timeout=10.0,
            ),
            timeout=0.2,
        )

        assert result is False
        assert ws_client._callbacks == []

    async def test_run_script_cleans_callback_when_send_fails(self, ws_client):
        """A send exception must not leave a completion callback registered."""

        class FailingWebSocket:
            async def send(self, message):
                raise RuntimeError("send failed")

        ws_client._websocket = FailingWebSocket()
        ws_client._connected = True

        result = await ws_client.run_script(
            "_-Echo test",
            wait_for_completion=True,
        )

        assert result is False
        assert ws_client._callbacks == []

    async def test_run_script_cleans_callback_after_timeout(self, ws_client):
        """A missing completion must time out without leaking its callback."""

        class SilentWebSocket:
            async def send(self, message):
                return None

        ws_client._websocket = SilentWebSocket()
        ws_client._connected = True

        result = await ws_client.run_script(
            "_-Echo test",
            wait_for_completion=True,
            timeout=0.001,
        )

        assert result is False
        assert ws_client._callbacks == []

    async def test_cancel_waits_for_correlated_ack(self, ws_client):
        """Cancel success means the server accepted the literal cancel key."""

        class ImmediateCancelWebSocket:
            payload = None

            async def send(self, message):
                self.payload = json.loads(message)
                ws_client._handle_event(WebSocketEvent(
                    event_type="CancelResult",
                    text="",
                    timestamp="2026-08-16T00:00:00",
                    raw={
                        "type": "CancelResult",
                        "request_id": self.payload["request_id"],
                        "success": True,
                    },
                ))

        websocket = ImmediateCancelWebSocket()
        ws_client._websocket = websocket
        ws_client._connected = True

        assert await ws_client.cancel(timeout=0.2) is True
        assert websocket.payload["command"] == "cancel"
        assert ws_client._pending_requests == {}
        assert ws_client._pending_responses == {}


class TestSingletonClient:
    """Tests for singleton WebSocket client."""

    def test_get_websocket_client_creates_new(self):
        """Test get_websocket_client creates new instance."""
        client = get_websocket_client()
        
        assert client is not None
        assert isinstance(client, RhinoWebSocketClient)

    def test_get_websocket_client_uses_shared_transport_settings(
        self,
        monkeypatch,
    ):
        """WS follows the configured WSL/remote host instead of localhost."""
        try:
            with monkeypatch.context() as scoped:
                scoped.setenv("RHINOCLAW_HOST", "127.0.0.1")
                scoped.setenv("RHINOCLAW_WS_PORT", "2456")
                reload_settings()
                reset_websocket_client()

                client = get_websocket_client()

                assert client.host == "127.0.0.1"
                assert client.port == 2456
                assert client.url == "ws://127.0.0.1:2456"
        finally:
            reload_settings()
            reset_websocket_client()

    def test_inactive_singleton_is_rebuilt_for_an_explicit_endpoint(self):
        first = get_websocket_client(host="127.0.0.1", port=2000)

        second = get_websocket_client(host="192.0.2.10", port=2200)

        assert second is not first
        assert second.url == "ws://192.0.2.10:2200"

    def test_default_singleton_stays_recoverable_after_settings_reload(
        self,
        monkeypatch,
    ):
        first = get_websocket_client()
        first._running = True
        try:
            with monkeypatch.context() as scoped:
                scoped.setenv("RHINOCLAW_HOST", "192.0.2.20")
                scoped.setenv("RHINOCLAW_WS_PORT", "2201")
                reload_settings()

                assert get_websocket_client() is first
        finally:
            first._running = False
            reload_settings()

    def test_active_singleton_rejects_explicit_endpoint_change(self):
        client = get_websocket_client(host="127.0.0.1", port=2000)
        client._running = True
        try:
            with pytest.raises(RuntimeError, match="endpoint changed"):
                get_websocket_client(host="192.0.2.30", port=2202)
        finally:
            client._running = False

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
