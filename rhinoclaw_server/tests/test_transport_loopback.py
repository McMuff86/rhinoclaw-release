"""Loopback-TCP transport tests — real sockets, no mocks.

Why this file exists
--------------------
The rest of the suite is 100% socket-mocked (``conftest.py`` hands back fixed
bytes), so it cannot exercise the reconnect/retry behaviour in
``RhinoConnection.send_command`` (``rhinoclaw/server.py``) — which is exactly
where a *mutating* command (``bake_grasshopper`` / ``build_and_bake_gh`` /
``run_grasshopper`` / ``place_doors``) could be executed twice and double-place
geometry.

These tests stand up a real localhost "fake Rhino" and drive the real
``RhinoConnection`` against it to pin the double-execution behaviour.

What they lock in (verified 2026-06-04)
---------------------------------------
1. A SILENT overrun — the server receives the command but sends no frame
   within the client timeout (the real ``completionEvent.Wait``-with-no-frame
   case in ``RhinoClawServer.cs``) — does NOT trigger the in-``send_command``
   auto-retry. ``receive_full_response`` swallows ``socket.timeout`` into a
   generic ``Exception`` which the retry-``except`` does not catch, so it
   raises without re-sending. => exactly ONE server-side execution.

2. A connection RESET *after* the server received the command DOES trip the
   auto-retry. The client now stamps a stable ``idempotency_key`` on the call
   and REUSES it on the retry (``server.py`` generates it once in
   ``send_command``), so a dedup-aware plugin recognises the retried frame as a
   duplicate and does NOT re-execute it. => the retry frame crosses the wire
   (``received == 2``) but the command runs only ONCE (``executed == 1``).

``FakeRhino`` below models that plugin-side dedup contract; the C# side
implements it in ``RhinoClawServer.cs``. The piece these tests *directly*
verify is the client's half of the contract: a stable idempotency key across
the reconnect-retry, without which server-side dedup is impossible.
"""

import dataclasses
import json
import socket
import struct
import threading
import time

import pytest

from rhinoclaw.config import Settings
from rhinoclaw.server import RhinoConnection
from rhinoclaw.utils.interaction_logger import interaction_logger

MUTATING_CMD = "bake_grasshopper"
MUTATING_PARAMS = {"definition_id": "abc-123", "layer": "Doors"}


def _read_one_command(conn: socket.socket, timeout: float = 5.0):
    """Read bytes off ``conn`` until they parse as one JSON command."""
    conn.settimeout(timeout)
    buf = b""
    while True:
        try:
            chunk = conn.recv(8192)
        except OSError:
            return None
        if not chunk:
            return None  # peer closed before a full command arrived
        buf += chunk
        try:
            return json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            continue  # partial frame, keep reading


class FakeRhino:
    """Minimal localhost stand-in for the Rhino plugin's TCP server.

    Models the plugin's idempotency contract: a command whose
    ``idempotency_key`` was already processed is NOT executed again — the
    cached response is returned instead.

    ``behaviors`` is consumed one entry per accepted connection (extras default
    to ``"ok"``):

    * ``"ok"``     – read one command, (de-dup-aware) execute, reply, hold open
    * ``"silent"`` – read one command, execute, never reply, hold open
    * ``"reset"``  – read one command, execute, then RST (no reply)

    ``received`` = every command frame read off any connection.
    ``executed`` = commands actually run (i.e. NOT de-duplicated by key).
    """

    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.received = []
        self.executed = []
        self._seen = {}  # idempotency_key -> cached response
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(8)
        self.port = self._srv.getsockname()[1]

        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        idx = 0
        while not self._stop.is_set():
            self._srv.settimeout(0.2)
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            behavior = self._behaviors[idx] if idx < len(self._behaviors) else "ok"
            idx += 1
            threading.Thread(
                target=self._handle, args=(conn, behavior), daemon=True
            ).start()

    def _process(self, cmd):
        """Record + (dedup-aware) 'execute', returning the response to send."""
        with self._lock:
            self.received.append(cmd)
            key = cmd.get("idempotency_key")
            if key is not None and key in self._seen:
                return self._seen[key]  # duplicate retry → do NOT execute again
            resp = {"status": "success", "result": {"ok": True}}
            self.executed.append(cmd)
            if key is not None:
                self._seen[key] = resp
            return resp

    def _handle(self, conn: socket.socket, behavior: str):
        try:
            cmd = _read_one_command(conn)
            resp = self._process(cmd) if cmd is not None else None

            if behavior == "reset":
                # Force an RST so the client's pending recv raises
                # ConnectionResetError (the path that DOES trigger auto-retry),
                # AFTER the command has 'executed' server-side.
                conn.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                conn.close()
                return

            if behavior == "ok" and resp is not None:
                try:
                    conn.sendall(json.dumps(resp).encode("utf-8"))
                except OSError:
                    pass

            # "ok" / "silent": hold the socket open like the real server's
            # while-loop so the client controls connection lifetime.
            while not self._stop.is_set():
                time.sleep(0.02)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @property
    def receipts(self):
        with self._lock:
            return list(self.received)

    @property
    def executions(self):
        with self._lock:
            return list(self.executed)

    def stop(self):
        self._stop.set()
        try:
            self._srv.close()
        except OSError:
            pass


@pytest.fixture
def fast_settings(monkeypatch):
    """Shrink the client timeout and silence disk-writing side effects.

    Patches ``get_settings`` *inside* ``rhinoclaw.server`` (what
    ``receive_full_response`` / ``send_command`` call) rather than the
    process-wide cache, so nothing leaks into other tests.
    """
    base = Settings.from_env()
    fast = dataclasses.replace(base, timeout_seconds=0.5, max_timeout_seconds=2.0)
    monkeypatch.setattr("rhinoclaw.server.get_settings", lambda: fast)

    prev_logging = interaction_logger.enabled
    interaction_logger.enabled = False
    yield fast
    interaction_logger.enabled = prev_logging


def _connect(port: int) -> RhinoConnection:
    conn = RhinoConnection(host="127.0.0.1", port=port)
    conn.retry_delay = 0.0  # no sleep between reconnect attempts — keep tests fast
    assert conn.connect(), "client failed to connect to FakeRhino"
    return conn


def test_happy_path_single_execution(fast_settings):
    """Sanity: a normal reply executes the command exactly once."""
    server = FakeRhino(["ok"])
    try:
        conn = _connect(server.port)
        result = conn.send_command(MUTATING_CMD, dict(MUTATING_PARAMS))
        assert result == {"ok": True}
        assert len(server.executions) == 1
        assert server.receipts[0]["type"] == MUTATING_CMD
    finally:
        conn.disconnect()
        server.stop()


def test_command_carries_idempotency_key(fast_settings):
    """Every command now carries an idempotency_key (the dedup contract's key)."""
    server = FakeRhino(["ok"])
    try:
        conn = _connect(server.port)
        conn.send_command(MUTATING_CMD, dict(MUTATING_PARAMS))
        assert server.receipts[0].get("idempotency_key")  # present + non-empty
    finally:
        conn.disconnect()
        server.stop()


def test_silent_overrun_does_not_autoretry(fast_settings):
    """A server that receives the command but never replies must NOT be
    silently re-sent. ``receive_full_response`` converts the recv timeout into
    a generic Exception, which bypasses the retry-``except``.
    """
    server = FakeRhino(["silent"])
    try:
        conn = _connect(server.port)
        with pytest.raises(Exception) as excinfo:
            conn.send_command(MUTATING_CMD, dict(MUTATING_PARAMS))

        assert "communication error" in str(excinfo.value).lower()
        # The command crossed the wire exactly once — no blind re-execution.
        assert len(server.receipts) == 1
    finally:
        conn.disconnect()
        server.stop()


def test_reset_retry_is_deduped_by_idempotency_key(fast_settings):
    """REGRESSION GUARD (was the double-bake bug). A reset after the command
    ran server-side triggers the auto-retry, but the retry reuses the SAME
    idempotency_key, so a dedup-aware plugin runs the command only ONCE.

    Directly verified here: the client emits a *stable* key across the retry.
    Modelled here (and implemented in RhinoClawServer.cs): the server dedups on
    that key, so ``executed == 1`` even though the retry frame is ``received``.
    """
    server = FakeRhino(["reset", "ok"])  # 1st conn runs+resets, 2nd sees the dup
    try:
        conn = _connect(server.port)
        result = conn.send_command(MUTATING_CMD, dict(MUTATING_PARAMS))
        assert result == {"ok": True}

        receipts = server.receipts
        # The retry frame DID cross the wire…
        assert len(receipts) == 2, f"expected a retry frame, got {len(receipts)}"
        # …but the command was executed only once — no double bake.
        assert len(server.executions) == 1, "command double-executed under reset"
        # The client's half of the contract: a STABLE key across the retry.
        assert receipts[0].get("idempotency_key")
        assert receipts[0]["idempotency_key"] == receipts[1]["idempotency_key"]
        # request_id is still regenerated per attempt (so it alone cannot dedupe).
        assert receipts[0]["request_id"] != receipts[1]["request_id"]
    finally:
        conn.disconnect()
        server.stop()


class EchoServer:
    """Loop-serving fake: answers EVERY command on one connection, echoing
    the request_id (correctly or deliberately wrong)."""

    def __init__(self, echo="correct", delay=0.0):
        self.echo = echo
        self.delay = delay
        self.handled = 0
        self._stop = threading.Event()
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(4)
        self.port = self._srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self._stop.is_set():
            self._srv.settimeout(0.2)
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    def _handle(self, conn):
        try:
            while not self._stop.is_set():
                cmd = _read_one_command(conn)
                if cmd is None:
                    return
                if self.delay:
                    time.sleep(self.delay)
                rid = cmd.get("request_id")
                resp = {"status": "success",
                        "result": {"echo": cmd["params"].get("n")},
                        "request_id": "deadbeef" if self.echo == "wrong" else rid}
                conn.sendall(json.dumps(resp).encode("utf-8"))
                self.handled += 1
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        self._stop.set()
        try:
            self._srv.close()
        except OSError:
            pass


def test_correct_request_id_echo_passes(fast_settings):
    server = EchoServer(echo="correct")
    try:
        conn = _connect(server.port)
        result = conn.send_command("ping", {"n": 1})
        assert result == {"echo": 1}
    finally:
        conn.disconnect()
        server.stop()


def test_mismatched_request_id_fails_loud_and_drops_socket(fast_settings):
    """W5d: a stale/interleaved frame must never be silently accepted."""
    server = EchoServer(echo="wrong")
    try:
        conn = _connect(server.port)
        with pytest.raises(Exception, match="Transport integrity"):
            conn.send_command("ping", {"n": 1})
        assert conn.sock is None  # poisoned stream was dropped
    finally:
        conn.disconnect()
        server.stop()


def test_concurrent_sends_are_serialised_by_the_io_lock(fast_settings):
    """W5d: parallel send_command calls on ONE connection must not
    interleave — each caller gets ITS OWN response."""
    server = EchoServer(echo="correct", delay=0.01)
    try:
        conn = _connect(server.port)
        results = {}
        errors = []

        def worker(tag, values):
            try:
                for v in values:
                    out = conn.send_command("ping", {"n": f"{tag}-{v}"})
                    results[f"{tag}-{v}"] = out["echo"]
            except Exception as e:  # noqa: BLE001 - collect for assertion
                errors.append(e)

        threads = [threading.Thread(target=worker, args=("a", range(5))),
                   threading.Thread(target=worker, args=("b", range(5)))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, errors
        # every call got exactly its own echo back
        assert results == {k: k for k in results}
        assert len(results) == 10
        assert server.handled == 10
    finally:
        conn.disconnect()
        server.stop()


# --- per-call timeout ----------------------------------------------------------

class _TimeoutRecordingSock:
    """Minimal socket double: records settimeout, serves one JSON frame."""

    def __init__(self):
        self.timeout = None
        self._served = False

    def settimeout(self, t):
        self.timeout = t

    def recv(self, _n):
        if self._served:
            return b""
        self._served = True
        return b'{"status": "success"}'


def test_receive_honours_per_call_timeout(fast_settings):
    """A caller-supplied timeout (e.g. a long bake) must reach the socket —
    it must NOT be overridden by the configured default."""
    conn = RhinoConnection(host="127.0.0.1", port=0)
    sock = _TimeoutRecordingSock()
    conn.receive_full_response(sock, timeout=42.0)
    assert sock.timeout == 42.0


def test_receive_defaults_to_settings_timeout(fast_settings):
    conn = RhinoConnection(host="127.0.0.1", port=0)
    sock = _TimeoutRecordingSock()
    conn.receive_full_response(sock)
    assert sock.timeout == fast_settings.timeout_seconds
