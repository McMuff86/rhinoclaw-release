"""Static regressions for the Rhino-9-safe GrasshopperPlayer mechanics.

Live findings 2026-08-17 (Rhino 9.0.26223): SendKeystrokes drops characters
in long strings ('_-GrasshopperPlayer' arrived as '_-GrasshoppePlayer') and
partial command-line input wedges the UI thread via the autocomplete popup —
typing the player command crashed Rhino. Feeding keystrokes through
``execute_rhinoscript_python_code`` additionally opens that handler's undo
record while the keys pump the message queue, which left a record dangling
open and silently broke every later ``BeginUndoRecord`` (rollback stopped
working until ``EndUndoRecord`` was called manually).

These tests pin the safe mechanics: player start via ``start_script_async``
(no typing), prompt feeding via the undo-free ``send_keystrokes`` command.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GH_PLAYER = ROOT / "rhinoclaw_server" / "src" / "rhinoclaw" / "utils" / "gh_player.py"
SERVER = ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs"
GH_OPS = ROOT / "rhinoclaw_plugin" / "Functions" / "GrasshopperOperations.cs"


def test_player_start_does_not_type_the_command() -> None:
    source = GH_PLAYER.read_text(encoding="utf-8")

    assert "start_script_async" in source
    # The old mechanic — typing '_-GrasshopperPlayer "<path>"' via
    # SendKeystrokes — must not come back.
    assert 'cmd = \'_-GrasshopperPlayer' not in source


def test_prompt_feeding_prefers_undo_free_send_keystrokes() -> None:
    source = GH_PLAYER.read_text(encoding="utf-8")

    assert "'send_keystrokes'" in source
    # Legacy fallback for pre-0.7.7 plugins stays available.
    assert "execute_rhinoscript_python_code" in source


def test_plugin_registers_send_keystrokes_undo_free() -> None:
    server = SERVER.read_text(encoding="utf-8")

    assert '["send_keystrokes"]' in server

    undo_free_block = server.split(
        "private static readonly HashSet<string> UndoFreeCommands", 1
    )[1].split("};", 1)[0]
    assert '"send_keystrokes"' in undo_free_block


def test_plugin_handler_appends_enter_by_default() -> None:
    ops = GH_OPS.read_text(encoding="utf-8")

    assert "SendKeystrokesToCommandLine" in ops
    assert 'parameters["enter"]' in ops
