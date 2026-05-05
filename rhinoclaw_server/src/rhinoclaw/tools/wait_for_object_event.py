"""
wait_for_object_event — block until a matching document_event arrives.

Typed convenience wrapper around the WebSocket buffer. Filters
client-side by sub-event ("object_added" / "object_deleted" / …),
optional layer and object_type. Returns the event payload or a
timeout marker.
"""

import asyncio
import json
from typing import Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.websocket_client import WebSocketEvent, get_websocket_client

DocumentSubEvent = Literal[
    "object_added",
    "object_deleted",
    "object_modified",
    "object_replaced",
    "selection_changed",
    "any",
]


@mcp.tool()
async def wait_for_object_event(
    ctx: Context,
    event: DocumentSubEvent = "any",
    layer: Optional[str] = None,
    object_type: Optional[str] = None,
    timeout: float = 30.0,
) -> str:
    """Wait for a document-level event that matches the filter.

    Filters are AND-combined and applied client-side against the
    WebSocket buffer. The first matching event after `subscribe_events`
    has been called wins.

    Parameters:
    - event: which sub-event to wait for. "any" matches all five
      document sub-events. Default "any".
    - layer: only match events on this layer (case-sensitive name).
      Ignored for `selection_changed` — selection events span layers,
      inspect `by_layer` in the response instead.
    - object_type: only match events for this Rhino ObjectType
      (e.g. "Brep", "Curve", "Mesh"). Same caveat for selection.
    - timeout: max wait in seconds. Default 30.

    Returns:
        On match:
          {"success": true, "data": {
            "matched": true,
            "event": "object_added",
            "object_id": "...", "layer": "...", "object_type": "Brep",
            "timestamp": "2026-...",
            "raw": { full event payload }
          }}
        On timeout:
          {"success": true, "data": {"matched": false, "timeout": 30.0}}
    """
    try:
        client = get_websocket_client()
        if not client.is_connected:
            await client.start_listening()

        match_event = asyncio.Event()
        matched: List[WebSocketEvent] = []

        def predicate(evt: WebSocketEvent) -> None:
            if evt.event_type != "document_event":
                return
            raw = evt.raw or {}
            sub = raw.get("event", "")
            if event != "any" and sub != event:
                return
            if layer is not None and raw.get("layer") != layer:
                return
            if object_type is not None and raw.get("object_type") != object_type:
                return
            matched.append(evt)
            match_event.set()

        client.add_callback(predicate)
        try:
            await asyncio.wait_for(match_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return json.dumps(ok(
                message=f"No matching event within {timeout}s.",
                data={"matched": False, "timeout": timeout},
            ))
        finally:
            client.remove_callback(predicate)

        if not matched:
            return json.dumps(ok(
                message="Predicate signalled but matched list is empty.",
                data={"matched": False, "timeout": timeout},
            ))

        evt = matched[0]
        raw = evt.raw or {}
        data: Dict[str, Any] = {
            "matched": True,
            "event": raw.get("event", ""),
            "timestamp": evt.timestamp,
            "raw": raw,
        }
        for k in ("object_id", "old_id", "layer", "object_type", "name", "count", "ids"):
            if k in raw:
                data[k] = raw[k]

        return json.dumps(ok(
            message=f"Matched '{data['event']}'",
            data=data,
        ))

    except Exception as e:
        logger.error(f"wait_for_object_event failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
