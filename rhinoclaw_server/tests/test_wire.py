"""Unit tests for the shared wire framing (``rhinoclaw.transport.wire``).

``wire`` is the ONE definition of the RhinoClaw wire protocol, imported by both
the MCP server's ``RhinoConnection`` and the rhinoclaw_client ``RhinoClient`` (A3). The
end-to-end reconnect/dedup behaviour is pinned in ``test_transport_loopback.py``;
this file locks the pure framing pieces in isolation.
"""
import json
import socket

import pytest

from rhinoclaw.transport import wire


# --- id minting ---------------------------------------------------------------

def test_request_id_is_short_hex_and_unique():
    a, b = wire.new_request_id(), wire.new_request_id()
    assert a != b
    assert len(a) == 8
    int(a, 16)  # raises if not hex


def test_idempotency_key_is_hex_and_unique():
    a, b = wire.new_idempotency_key(), wire.new_idempotency_key()
    assert a != b
    int(a, 16)  # raises if not hex


# --- command assembly ---------------------------------------------------------

def test_build_command_minimal_has_only_type_and_params():
    cmd = wire.build_command("ping")
    assert cmd == {"type": "ping", "params": {}}


def test_build_command_defaults_none_params_to_empty_dict():
    assert wire.build_command("ping", None)["params"] == {}


def test_build_command_attaches_optional_fields_when_present():
    cmd = wire.build_command(
        "bake", {"x": 1},
        request_id="abc", idempotency_key="key123", auth_token="tok",
    )
    assert cmd == {
        "type": "bake",
        "params": {"x": 1},
        "request_id": "abc",
        "idempotency_key": "key123",
        "auth": "tok",
    }


@pytest.mark.parametrize("token", [None, ""])
def test_build_command_omits_auth_when_token_falsy(token):
    assert "auth" not in wire.build_command("ping", auth_token=token)


def test_build_command_omits_ids_when_not_given():
    cmd = wire.build_command("ping", {"a": 1}, auth_token="tok")
    assert "request_id" not in cmd
    assert "idempotency_key" not in cmd


def test_encode_command_roundtrips_json():
    cmd = wire.build_command("ping", {"n": 1}, request_id="r")
    assert json.loads(wire.encode_command(cmd).decode("utf-8")) == cmd


# --- request-id integrity -----------------------------------------------------

def test_request_id_mismatch_true_on_wrong_echo():
    assert wire.is_request_id_mismatch("sent", {"request_id": "other"}) is True


def test_request_id_mismatch_false_on_correct_echo():
    assert wire.is_request_id_mismatch("sent", {"request_id": "sent"}) is False


def test_request_id_mismatch_false_when_response_has_no_id():
    # An older plugin that never echoes the id is NOT a mismatch.
    assert wire.is_request_id_mismatch("sent", {"status": "success"}) is False


# --- frame reading ------------------------------------------------------------

class FakeSock:
    """Scripted socket: yields ``chunks`` from ``recv``, then closes cleanly
    (empty bytes) or raises ``raise_at_end``."""

    def __init__(self, chunks, raise_at_end=None):
        self._chunks = list(chunks)
        self._raise_at_end = raise_at_end
        self.timeout = None

    def settimeout(self, t):
        self.timeout = t

    def recv(self, _n):
        if self._chunks:
            return self._chunks.pop(0)
        if self._raise_at_end is not None:
            raise self._raise_at_end
        return b""


def test_read_json_frame_returns_complete_single_frame():
    payload = json.dumps({"status": "success", "result": {"ok": True}}).encode()
    assert wire.read_json_frame(FakeSock([payload])) == payload


def test_read_json_frame_reassembles_chunks():
    payload = json.dumps({"result": {"n": 42}}).encode()
    mid = len(payload) // 2
    sock = FakeSock([payload[:mid], payload[mid:]])
    assert wire.read_json_frame(sock) == payload


def test_read_json_frame_reassembles_chunks_split_inside_multibyte_char():
    # Umlauts in layer/object names are routine; a recv chunk boundary that
    # lands INSIDE the 2-byte UTF-8 sequence raises UnicodeDecodeError (not
    # JSONDecodeError) — the loop must keep reading, not crash.
    payload = json.dumps({"result": {"layer": "Türen"}}, ensure_ascii=False).encode("utf-8")
    split = payload.index("ü".encode("utf-8")) + 1  # between the ü's two bytes
    sock = FakeSock([payload[:split], payload[split:]])
    assert wire.read_json_frame(sock) == payload


def test_read_json_frame_multibyte_truncation_at_eof_is_incomplete():
    payload = json.dumps({"layer": "Türen"}, ensure_ascii=False).encode("utf-8")
    split = payload.index("ü".encode("utf-8")) + 1
    with pytest.raises(wire.IncompleteFrameError):
        wire.read_json_frame(FakeSock([payload[:split]]))  # stream ends mid-char


def test_read_json_frame_raises_on_no_data_close():
    with pytest.raises(wire.IncompleteFrameError):
        wire.read_json_frame(FakeSock([]))


def test_read_json_frame_raises_on_partial_then_close():
    with pytest.raises(wire.IncompleteFrameError):
        wire.read_json_frame(FakeSock([b'{"a":']))  # never completes, then EOF


def test_read_json_frame_treats_timeout_with_no_data_as_incomplete():
    with pytest.raises(wire.IncompleteFrameError):
        wire.read_json_frame(FakeSock([], raise_at_end=socket.timeout()))


def test_read_json_frame_returns_data_buffered_before_timeout():
    payload = json.dumps({"ok": 1}).encode()
    # full frame arrives, THEN the socket would time out — the frame wins.
    sock = FakeSock([payload], raise_at_end=socket.timeout())
    assert wire.read_json_frame(sock) == payload


def test_read_json_frame_propagates_connection_error():
    # A genuine drop (RST) must NOT be swallowed — the server's retry path
    # depends on seeing a ConnectionError.
    sock = FakeSock([b'{"a":'], raise_at_end=ConnectionResetError("reset"))
    with pytest.raises(ConnectionResetError):
        wire.read_json_frame(sock)
