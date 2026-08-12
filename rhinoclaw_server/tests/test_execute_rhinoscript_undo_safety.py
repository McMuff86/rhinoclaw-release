"""Static regressions for failed-script undo isolation.

The live bug was destructive: a read-only diagnostic raised after a successful
VisualARQ build, and ExecuteRhinoscript's unconditional ``doc.Undo()`` removed
the preceding build because the failed call's nested undo record was empty.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HANDLER = ROOT / "rhinoclaw_plugin" / "Functions" / "ExecuteRhinoscript.cs"
SERVER = ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs"


def test_execute_rhinoscript_owns_non_nested_undo_record() -> None:
    server = SERVER.read_text(encoding="utf-8")

    undo_free_block = server.split(
        "private static readonly HashSet<string> UndoFreeCommands", 1
    )[1].split("};", 1)[0]
    assert '"execute_rhinoscript_python_code"' in undo_free_block


def test_failed_script_adds_marker_before_undo() -> None:
    handler = HANDLER.read_text(encoding="utf-8")

    marker = handler.index("doc.AddCustomUndoEvent(")
    end_record = handler.index("doc.EndUndoRecord(undoRecordSerialNumber)")
    undo = handler.index("undoRecordSerialNumber > 0 && doc.Undo()")

    assert marker < end_record < undo
    assert "rollback_performed" in handler
    assert "if (undoRecordSerialNumber > 0)" in handler


def test_failed_script_has_no_unconditional_undo() -> None:
    handler = HANDLER.read_text(encoding="utf-8")

    assert "\n            doc.Undo();" not in handler
    assert "undoRecordSerialNumber > 0 && doc.Undo()" in handler
