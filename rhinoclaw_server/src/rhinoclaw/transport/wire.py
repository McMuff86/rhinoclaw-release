"""wire.py — the RhinoClaw wire protocol framing, in ONE place.

RhinoClaw has exactly one client-side contract: a JSON command
``{type, params, request_id?, idempotency_key?, auth?}`` written to a TCP
socket, answered by a single JSON frame ``{status, result, request_id?}``.
Two independent transports speak it:

  * ``rhinoclaw.server.RhinoConnection`` — the MCP server's connection (adds
    request-id integrity, an idempotency key reused across a reconnect-retry,
    an I/O lock, and reconnect/retry).
  * the rhinoclaw_client CLI's ``RhinoClient`` (``scripts/rhinoclaw_client/rhino_client.py``) —
    raw TCP, no locks, no retry.

Before A3 each rolled its own command-building + chunked-read loop and they
drifted. This module owns the FRAMING so neither does: build a command dict,
encode it, read one complete JSON frame off an already-connected socket,
mint/verify the ids. It deliberately owns **no socket lifecycle** — it never
opens, closes, locks, reconnects, or sets timeouts on a socket. Those concerns
stay in each client class (which is why the two classes are NOT merged).

IMPORTANT: stdlib-only by design. ``scripts/sync-skill.sh`` copies this file
verbatim into the deployed OpenClaw skill (next to ``rhino_client.py``), where
the ``rhinoclaw`` package is not installed — exactly like ``door_batch.py``.
"""
import json
import socket
import uuid
from typing import Any, Dict, Optional

__all__ = [
    "new_request_id",
    "new_idempotency_key",
    "build_command",
    "encode_command",
    "read_json_frame",
    "is_request_id_mismatch",
    "IncompleteFrameError",
]


class IncompleteFrameError(Exception):
    """The socket closed or timed out before a complete JSON frame arrived.

    Deliberately a plain ``Exception`` (not ``socket.timeout``/``ConnectionError``)
    so the server's reconnect-``except`` does NOT treat a silent no-reply as a
    retryable drop — a command that ran server-side must not be blindly
    re-sent. Each client maps this to its own error type/message.
    """


def new_request_id() -> str:
    """A short per-frame id the plugin echoes back, so the client can detect a
    stale/interleaved response (see :func:`is_request_id_mismatch`)."""
    return uuid.uuid4().hex[:8]


def new_idempotency_key() -> str:
    """A key stable across a reconnect-retry, so a dedup-aware plugin does not
    re-run a command whose socket dropped AFTER it already executed."""
    return uuid.uuid4().hex


def build_command(
    command_type: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    request_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble a RhinoClaw command frame.

    ``{type, params}`` always; ``request_id``/``idempotency_key`` are attached
    only when provided (the CLI omits them); ``auth`` only when a non-empty
    token is passed. The plugin enforces ``auth`` only when it has a token of
    its own configured.
    """
    command: Dict[str, Any] = {
        "type": command_type,
        "params": params or {},
    }
    if request_id is not None:
        command["request_id"] = request_id
    if idempotency_key is not None:
        command["idempotency_key"] = idempotency_key
    if auth_token:
        command["auth"] = auth_token
    return command


def encode_command(command: Dict[str, Any]) -> bytes:
    """Serialise a command dict to the exact UTF-8 bytes put on the wire."""
    return json.dumps(command).encode("utf-8")


def read_json_frame(sock: socket.socket, *, buffer_size: int = 8192) -> bytes:
    """Read one complete JSON frame off an ALREADY-CONNECTED socket.

    The framing is "one JSON value": accumulate ``recv`` chunks and return the
    raw bytes as soon as they parse as JSON. This owns no socket lifecycle — it
    does not set timeouts, close, or reconnect; the caller configures the
    socket's timeout first.

    * ``socket.timeout`` while waiting is treated as end-of-stream: if what was
      already received parses, it is returned; otherwise raises
      :class:`IncompleteFrameError`.
    * A clean close (empty ``recv``) is handled the same way.
    * ``ConnectionError``/``OSError`` (e.g. an RST) is **not** swallowed — it
      propagates so the caller's reconnect-retry can act on a genuine drop.

    Raises:
        IncompleteFrameError: the stream ended before a full frame arrived.
    """
    chunks = []
    while True:
        try:
            chunk = sock.recv(buffer_size)
        except socket.timeout:
            break  # no more data within the socket's timeout — use what we have
        if not chunk:
            break  # peer closed the stream
        chunks.append(chunk)
        data = b"".join(chunks)
        try:
            json.loads(data.decode("utf-8"))
            return data  # complete frame
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Partial frame — a chunk boundary may even split a multi-byte
            # UTF-8 character (umlauts in layer/object names), which raises
            # UnicodeDecodeError rather than JSONDecodeError. Keep reading.
            continue

    if chunks:
        data = b"".join(chunks)
        try:
            json.loads(data.decode("utf-8"))
            return data
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise IncompleteFrameError(
                "incomplete JSON response received before the stream ended"
            ) from e
    raise IncompleteFrameError("no data received before the socket closed")


def is_request_id_mismatch(sent_request_id: str, response: Dict[str, Any]) -> bool:
    """True if ``response`` echoes a ``request_id`` that is NOT the one we sent.

    A mismatch means we just consumed a frame that belongs to a DIFFERENT call
    (a stale frame after a timeout, or an interleaved client) — the caller
    should drop the poisoned socket. A response with no ``request_id`` (older
    plugin) is not a mismatch.
    """
    echoed = response.get("request_id")
    return echoed is not None and echoed != sent_request_id
