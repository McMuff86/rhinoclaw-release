"""
subscribe_events — agent-friendly entry point for the WebSocket event stream.

The plugin pushes three families of events:

* "Prompt" / "History" / "Script*" — command-line monitoring (existing).
* "document_event" with sub-event "object_added" / "object_deleted" /
  "object_modified" / "object_replaced" — RhinoDoc mutations (W4.2).
* "document_event" with sub-event "selection_changed" — selection
  set changed (W4.3).

This tool:

* Connects to the WebSocket if not already connected (idempotent).
* Returns a manifest of available event types so the agent can
  discover what to listen for without scanning docs.
* Reports current buffer state (count, oldest/newest timestamps).

Filter is client-side for now: the agent calls `wait_for_object_event`
with a type/layer/object_type filter, which scans the WebSocket buffer.
Server-side per-subscriber filters are a future improvement once we
can identify individual subscribers.
"""

import json
from typing import Any, Dict

from mcp.server.fastmcp import Context

from rhinoclaw.server import logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.websocket_client import get_websocket_client


@mcp.tool()
async def subscribe_events(ctx: Context) -> str:
    """Connect to the WebSocket event stream and return the event manifest.

    Call this once at the start of a real-time session. Subsequent calls
    are idempotent — they confirm the connection is still alive and
    return the current buffer state.

    Returns:
        {"success": true, "data": {
          "connected": true,
          "endpoint": "ws://...:2000",
          "buffer_size": int,
          "event_types": {
            "command_line": ["Prompt", "History", "ScriptCompleted",
                             "ScriptError", "Heartbeat"],
            "document": ["document_event"]
          },
          "document_subevents": [
            "object_added", "object_deleted", "object_modified",
            "object_replaced", "selection_changed"
          ],
          "filter_keys_per_event": {
            "object_added":     ["object_id", "object_type", "name", "layer"],
            "object_deleted":   ["object_id", "object_type", "name", "layer"],
            "object_modified":  ["object_id", "object_type", "name", "layer", "changes"],
            "object_replaced":  ["object_id", "old_id", "object_type", "layer"],
            "selection_changed": ["count", "ids", "by_layer", "by_type"]
          },
          "follow_up_tools": [
            "wait_for_object_event(event=..., layer=..., object_type=..., timeout=...)",
            "get_stream_events(filter_type='document_event', limit=N)",
            "wait_for_prompt(pattern=..., timeout=...)  # command-line prompts"
          ]
        }}
    """
    try:
        client = get_websocket_client()
        if not client.is_connected:
            await client.start_listening()

        manifest: Dict[str, Any] = {
            "connected": client.is_connected,
            "endpoint": client.url,
            "buffer_size": client.event_count,
            "event_types": {
                "command_line": [
                    "Prompt", "History",
                    "ScriptCompleted", "ScriptError", "Heartbeat",
                ],
                "document": ["document_event"],
            },
            "document_subevents": [
                "object_added", "object_deleted", "object_modified",
                "object_replaced", "selection_changed",
            ],
            "filter_keys_per_event": {
                "object_added":      ["object_id", "object_type", "name", "layer"],
                "object_deleted":    ["object_id", "object_type", "name", "layer"],
                "object_modified":   ["object_id", "object_type", "name", "layer", "changes"],
                "object_replaced":   ["object_id", "old_id", "object_type", "layer"],
                "selection_changed": ["count", "ids", "by_layer", "by_type"],
            },
            "follow_up_tools": [
                "wait_for_object_event(event=..., layer=..., object_type=..., timeout=...)",
                "get_stream_events(filter_type='document_event', limit=N)",
                "wait_for_prompt(pattern=..., timeout=...)",
            ],
        }
        return json.dumps(ok(
            message=f"Subscribed — buffer holds {client.event_count} event(s).",
            data=manifest,
        ))
    except Exception as e:
        logger.error(f"subscribe_events failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
