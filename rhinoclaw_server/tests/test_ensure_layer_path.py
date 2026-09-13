import ast
import json
from unittest.mock import MagicMock, patch

from rhinoclaw.tools.ensure_layer_path import ensure_layer_path

PATCH = "rhinoclaw.tools.ensure_layer_path.get_rhino_connection"
PRINT = "Script successfully executed! Print output: "


def _rhino(payload):
    rhino = MagicMock()
    rhino.send_command.return_value = PRINT + "RESULT:" + json.dumps(payload)
    return rhino


def _embedded_params(code):
    first_line = code.splitlines()[0]
    literal = first_line.split("PARAMS_JSON = ", 1)[1]
    return json.loads(ast.literal_eval(literal))


def test_creates_missing_levels_and_reports_leaf():
    rhino = _rhino({
        "status": "success",
        "layer_path": "Plot9::VA::Walls",
        "created": ["Plot9", "Plot9::VA", "Plot9::VA::Walls"],
        "layer_id": "11111111-1111-1111-1111-111111111111",
        "created_count": 3,
        "already_existed": False,
    })
    with patch(PATCH, return_value=rhino):
        result = json.loads(
            ensure_layer_path(MagicMock(), "Plot9::VA::Walls"))

    assert result["success"] is True
    assert result["data"]["created_count"] == 3
    assert result["data"]["already_existed"] is False
    assert result["data"]["layer_id"] == (
        "11111111-1111-1111-1111-111111111111")

    command, params = rhino.send_command.call_args[0]
    assert command == "execute_rhinoscript_python_code"
    code = params["code"]
    compile(code, "<ensure_layer_path>", "exec")
    assert "FindByFullPath" in code
    assert "ParentLayerId" in code
    assert _embedded_params(code) == {
        "path": "Plot9::VA::Walls", "color": None,
    }


def test_segments_are_trimmed_and_color_passed_through():
    rhino = _rhino({
        "status": "success", "layer_path": "A::B", "created": [],
        "layer_id": "22222222-2222-2222-2222-222222222222",
        "created_count": 0, "already_existed": True,
    })
    with patch(PATCH, return_value=rhino):
        result = json.loads(
            ensure_layer_path(MagicMock(), " A :: B ", color=[255, 0, 0]))

    assert result["success"] is True
    assert result["data"]["already_existed"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    assert _embedded_params(code) == {"path": "A::B", "color": [255, 0, 0]}


def test_umlaut_layer_names_stay_ascii_in_embedded_source():
    rhino = _rhino({
        "status": "success", "layer_path": "Gebäude::Wände",
        "created": [], "layer_id": "33333333-3333-3333-3333-333333333333",
        "created_count": 0, "already_existed": True,
    })
    with patch(PATCH, return_value=rhino):
        result = json.loads(
            ensure_layer_path(MagicMock(), "Gebäude::Wände"))

    assert result["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    assert all(ord(char) < 128 for char in code.splitlines()[0])
    assert _embedded_params(code)["path"] == "Gebäude::Wände"


def test_rejects_empty_segments_and_bad_color():
    for bad_path in ["", "   ", "A::::B", "::A", "A::", None]:
        result = json.loads(ensure_layer_path(MagicMock(), bad_path))
        assert result["success"] is False, bad_path
        assert result["code"] == "INVALID_PARAMS"
    for bad_color in [[1, 2], [0, 0, 999], [0, 0, True], "red", [0, 0, 1.5]]:
        result = json.loads(
            ensure_layer_path(MagicMock(), "A::B", color=bad_color))
        assert result["success"] is False, bad_color
        assert result["code"] == "INVALID_PARAMS"


def test_script_error_and_missing_marker_fail_closed():
    rhino = MagicMock()
    rhino.send_command.return_value = {"success": False, "message": "boom"}
    with patch(PATCH, return_value=rhino):
        result = json.loads(ensure_layer_path(MagicMock(), "A::B"))
    assert result["success"] is False
    assert "boom" in result["message"]

    rhino = MagicMock()
    rhino.send_command.return_value = "no marker here"
    with patch(PATCH, return_value=rhino):
        result = json.loads(ensure_layer_path(MagicMock(), "A::B"))
    assert result["success"] is False
    assert "RESULT" in result["message"]


def test_in_script_add_failure_is_surfaced():
    rhino = _rhino({
        "status": "error", "code": "RHINO_ERROR",
        "message": "Layers.Add failed for: A::B",
    })
    with patch(PATCH, return_value=rhino):
        result = json.loads(ensure_layer_path(MagicMock(), "A::B"))
    assert result["success"] is False
    assert "Layers.Add failed" in result["message"]


def test_tool_is_reexported():
    import rhinoclaw

    assert callable(rhinoclaw.ensure_layer_path)
