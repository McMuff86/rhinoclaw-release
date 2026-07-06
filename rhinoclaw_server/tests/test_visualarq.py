"""Tests for the VisualARQ BIM tools (4.1) — incl. graceful degradation."""
import json
from unittest.mock import MagicMock, patch

PATCH = "rhinoclaw.tools.visualarq.get_rhino_connection"
PRINT = "Script successfully executed! Print output: "


def _rhino(va_result):
    rhino = MagicMock()
    rhino.send_command.return_value = PRINT + "RESULT:" + json.dumps(va_result)
    return rhino


UNAVAILABLE = {"available": False, "status": "unavailable",
               "message": "VisualARQ not available: not found"}


def test_status_available_reports_inventory():
    from rhinoclaw.tools.visualarq import va_status

    rhino = _rhino({"available": True, "wall_styles": 4, "door_styles": 6,
                    "window_styles": 5, "levels": 2})
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_status(MagicMock()))

    assert data["success"] is True
    assert data["data"]["available"] is True
    assert data["data"]["door_styles"] == 6


def test_status_degrades_gracefully_without_va():
    from rhinoclaw.tools.visualarq import va_status

    with patch(PATCH, return_value=_rhino(UNAVAILABLE)):
        data = json.loads(va_status(MagicMock()))

    # A query: not-installed is an ANSWER, not an error.
    assert data["success"] is True
    assert data["data"]["available"] is False
    assert "hint" in data["data"]


def test_action_tools_fail_cleanly_without_va():
    from rhinoclaw.tools.visualarq import va_create_wall

    with patch(PATCH, return_value=_rhino(UNAVAILABLE)):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 0, 0], [4000, 0, 0], 2400))

    assert data["success"] is False
    assert data["data"]["available"] is False
    assert "visualarq.com" in data["message"]


def test_create_wall_injects_params_and_returns_id():
    from rhinoclaw.tools.visualarq import va_create_wall

    rhino = _rhino({"status": "success", "wall_id": "guid-w1",
                    "style": "Generic", "height": 2400})
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 3000, 0], [4000, 3000, 0], 2400))

    assert data["success"] is True
    assert data["data"]["wall_id"] == "guid-w1"
    code = rhino.send_command.call_args[0][1]["code"]
    # Params travel as JSON, not string interpolation.
    sent = json.loads(code.split("json.loads(", 1)[1].split(")", 1)[0].strip("'\""))
    assert sent["style"] == "Generic"
    assert sent["start"] == [0, 3000, 0]
    assert sent["height"] == 2400


def test_create_door_by_point():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({"status": "success", "door_id": "guid-d1",
                    "style": "T80", "point": [2500, 3000, 0]})
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80", point=[2500, 3000, 0], width=900))

    assert data["success"] is True
    assert data["data"]["door_id"] == "guid-d1"


def test_create_door_requires_point_or_wall_position():
    from rhinoclaw.tools.visualarq import va_create_door

    data = json.loads(va_create_door(MagicMock(), "T80"))
    assert data["success"] is False
    assert "point" in data["message"]


def test_style_error_passes_message_through():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({"status": "error", "message": "Door style not found: X"})
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(MagicMock(), "X", point=[0, 0, 0]))

    assert data["success"] is False
    assert "not found" in data["message"]


def test_list_styles_validates_kind():
    from rhinoclaw.tools.visualarq import va_list_styles

    data = json.loads(va_list_styles(MagicMock(), kind="roof"))
    assert data["success"] is False


def test_ifc_export_requires_ifc_extension():
    from rhinoclaw.tools.visualarq import va_ifc_export

    data = json.loads(va_ifc_export(MagicMock(), "C:/x/model.step"))
    assert data["success"] is False


def test_ifc_export_success():
    from rhinoclaw.tools.visualarq import va_ifc_export

    rhino = _rhino({"status": "success", "path": "C:/x/m.ifc",
                    "version": "IFC4"})
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_ifc_export(MagicMock(), "C:/x/m.ifc"))

    assert data["success"] is True
    assert data["data"]["version"] == "IFC4"


def test_build_va_script_is_ironpython2_safe():
    from rhinoclaw.utils.visualarq import build_va_script

    script = build_va_script("result = {'status': 'success'}", {"a": 1})
    assert "f\"" not in script and "f'" not in script  # no f-strings
    assert "VisualARQ.Script" in script
    assert '"a": 1' in script
