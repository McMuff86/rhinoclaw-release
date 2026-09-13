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


def test_failed_script_uses_shared_owned_transaction() -> None:
    handler = HANDLER.read_text(encoding="utf-8")
    # Behavior is exercised by the C# UndoRecordTests, including a failed
    # empty script after prior work. This checks both engines use that path.
    assert "OwnedUndoRecord.ExecuteScript(" in handler
    assert "doc.BeginUndoRecord(" not in handler


def test_failed_script_has_no_unconditional_undo() -> None:
    handler = HANDLER.read_text(encoding="utf-8")

    assert "\n            doc.Undo();" not in handler
    assert "doc.Undo()" not in handler
