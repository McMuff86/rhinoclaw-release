"""Static regressions for execute_python3_code's transaction + engine choice.

Mirrors ``test_execute_rhinoscript_undo_safety.py``: the same destructive
nested-undo bug existed here (the dispatcher wrapped the command in its own
record, the handler's nested ``BeginUndoRecord`` returned 0, and the
unconditional ``doc.Undo()`` on a failed script could pop the PREVIOUS
successful operation).

Also pins the engine choice: the plugin must talk to the official
``Rhino.Runtime.Code`` API and never to
``RhinoCodePlatform.Rhino3D.Languages.Python3Script`` — per McNeel that
type's ``Create()`` always builds an IronPython script, i.e. it silently ran
Python 2 while claiming Python 3 (discourse topic 190803).
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HANDLER = ROOT / "rhinoclaw_plugin" / "Functions" / "ExecutePython3.cs"
SERVER = ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs"


def test_execute_python3_owns_non_nested_undo_record() -> None:
    server = SERVER.read_text(encoding="utf-8")

    undo_free_block = server.split(
        "private static readonly HashSet<string> UndoFreeCommands", 1
    )[1].split("};", 1)[0]
    assert '"execute_python3_code"' in undo_free_block


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


def test_uses_official_rhinocode_api_not_python3script() -> None:
    handler = HANDLER.read_text(encoding="utf-8")

    # The official API surface must be the primary path...
    assert 'Assembly.Load("Rhino.Runtime.Code")' in handler
    # ...and the IronPython-in-disguise reflection must never come back:
    # no loading of the undocumented RhinoCodePlatform assemblies, no
    # resolving of the Python3Script type (a comment MAY mention it).
    assert 'Assembly.Load("RhinoCodePlatform' not in handler
    assert '"RhinoCodePlatform.Rhino3D.Languages.Python3Script"' not in handler


def test_server_warms_python3_engine_on_start() -> None:
    server = SERVER.read_text(encoding="utf-8")
    handler = HANDLER.read_text(encoding="utf-8")

    assert "OnIdleWarmUpPython3" in server
    assert "WarmUpPython3" in handler
    assert "RHINOCLAW_SKIP_PY3_WARMUP" in handler
