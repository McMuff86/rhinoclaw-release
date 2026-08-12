"""Tests for localized, truthful camera orbiting."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

from rhinoclaw.tools.orbit_camera import orbit_camera


ROOT = Path(__file__).resolve().parents[2]


def test_orbit_camera_validates_direction_and_angle_before_connecting():
    invalid_direction = json.loads(
        orbit_camera(None, direction="clockwise", angle_degrees=15)
    )
    invalid_angle = json.loads(
        orbit_camera(None, direction="right", angle_degrees=float("nan"))
    )

    assert invalid_direction["code"] == "INVALID_PARAMS"
    assert invalid_angle["code"] == "INVALID_PARAMS"


def test_native_orbit_rejects_parallel_projection_before_any_mutation():
    source = (
        ROOT / "rhinoclaw_plugin" / "Functions" / "ViewportOperations.cs"
    ).read_text(encoding="utf-8")
    method_start = source.index("public JObject OrbitCamera")
    method_end = source.index("public JObject CaptureViewport", method_start)
    method = source[method_start:method_end]

    perspective_preflight = method.index("if (!viewport.IsPerspectiveProjection)")
    projection_push = method.index("viewport.PushViewProjection();")
    rotation = method.index("viewport.KeyboardRotate(leftRight, angleRadians)")

    assert perspective_preflight < projection_push < rotation
    assert "requires a perspective viewport" in method
    assert "CommitDetailViewportChanges" not in method[:perspective_preflight]


@patch("rhinoclaw.tools.orbit_camera.get_rhino_connection")
def test_orbit_camera_uses_single_native_call_for_active_view(mock_get_conn):
    connection = Mock()
    connection.send_command.return_value = {
        "status": "success",
        "viewport": "Perspektive",
        "direction": "right",
        "angle_degrees": 30,
    }
    mock_get_conn.return_value = connection

    result = json.loads(
        orbit_camera(None, direction="right", angle_degrees=30)
    )

    assert result["success"] is True
    assert "Perspektive" in result["message"]
    connection.send_command.assert_called_once_with(
        "orbit_camera",
        {"direction": "right", "angle_degrees": 30.0},
    )


@patch("rhinoclaw.tools.orbit_camera.get_rhino_connection")
def test_orbit_camera_preserves_explicit_qualified_detail(mock_get_conn):
    connection = Mock()
    connection.send_command.return_value = {
        "status": "success",
        "viewport": "A101::Detail 01",
        "viewport_kind": "detail",
    }
    mock_get_conn.return_value = connection

    result = json.loads(
        orbit_camera(
            None,
            direction="up",
            viewport_name="A101::Detail 01",
        )
    )

    assert result["success"] is True
    connection.send_command.assert_called_once_with(
        "orbit_camera",
        {
            "direction": "up",
            "angle_degrees": 15.0,
            "viewport_name": "A101::Detail 01",
        },
    )


@patch("rhinoclaw.tools.orbit_camera.get_rhino_connection")
def test_orbit_camera_reports_native_transport_failure(mock_get_conn):
    connection = Mock()
    connection.send_command.side_effect = RuntimeError("not a perspective view")
    mock_get_conn.return_value = connection

    result = json.loads(orbit_camera(None, direction="left"))

    assert result["success"] is False
    assert result["code"] == "RHINO_ERROR"
    assert "not a perspective view" in result["message"]
