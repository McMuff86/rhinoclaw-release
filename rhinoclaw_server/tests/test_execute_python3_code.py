"""Tests for the Python 3 (CPython/ScriptEditor) execution wrapper."""
import json
from unittest.mock import MagicMock, patch

PATCH = "rhinoclaw.tools.execute_python3_code.get_rhino_connection"


def _rhino(result):
    rhino = MagicMock()
    rhino.send_command.return_value = result
    return rhino


def test_success_passes_output_through():
    from rhinoclaw.tools.execute_python3_code import execute_python3_code

    rhino = _rhino({"success": True, "method": "ScriptEditor",
                    "result": "Print output: PYTHON 3.9.10\n"})
    with patch(PATCH, return_value=rhino):
        data = json.loads(execute_python3_code(
            MagicMock(), 'print(f"PYTHON {3.9}")'))

    assert data["success"] is True
    assert data["data"]["method"] == "ScriptEditor"
    assert "PYTHON" in data["data"]["result"]
    cmd, params = rhino.send_command.call_args[0]
    assert cmd == "execute_python3_code"
    assert "print" in params["code"]


def test_script_error_surfaces_traceback_as_failure():
    from rhinoclaw.tools.execute_python3_code import execute_python3_code

    rhino = _rhino({"success": False, "method": "ScriptEditor",
                    "message": "ModuleNotFoundError: No module named 'x'"})
    with patch(PATCH, return_value=rhino):
        data = json.loads(execute_python3_code(MagicMock(), "import x"))

    assert data["success"] is False
    assert "ModuleNotFoundError" in data["message"]


def test_timeout_is_forwarded():
    from rhinoclaw.tools.execute_python3_code import execute_python3_code

    rhino = _rhino({"success": True, "result": "ok"})
    with patch(PATCH, return_value=rhino):
        execute_python3_code(MagicMock(), "print(1)", timeout=300)

    assert rhino.send_command.call_args.kwargs["timeout"] == 300


def test_empty_code_rejected_without_connection():
    from rhinoclaw.tools.execute_python3_code import execute_python3_code

    data = json.loads(execute_python3_code(MagicMock(), ""))
    assert data["success"] is False


def test_capabilities_wrapper():
    from rhinoclaw.tools.execute_python3_code import get_script_capabilities

    rhino = _rhino({"ironpython2": True, "python3": True,
                    "rhino_version": "8.31"})
    with patch(PATCH, return_value=rhino):
        data = json.loads(get_script_capabilities(MagicMock()))

    assert data["success"] is True
    assert data["data"]["python3"] is True
    assert "python3=True" in data["message"]
