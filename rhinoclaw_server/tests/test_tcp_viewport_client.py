"""Contract tests for the deployable raw-TCP viewport helper."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLIENT_DIR = ROOT / "scripts" / "rhinoclaw_client"
VIEWPORT_CLIENT_PATH = CLIENT_DIR / "viewport.py"


def _load_viewport_client():
    sys.path.insert(0, str(CLIENT_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "rhinoclaw_tcp_viewport_client",
            VIEWPORT_CLIENT_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(CLIENT_DIR))


VIEWPORT_CLIENT = _load_viewport_client()


def test_tcp_orbit_uses_native_direction_angle_contract():
    client = MagicMock()
    client.send_command.return_value = {"status": "success"}

    with patch.object(VIEWPORT_CLIENT, "RhinoClient") as client_type:
        client_type.return_value.__enter__.return_value = client
        result = VIEWPORT_CLIENT.orbit_camera(
            " Left ",
            22.5,
            " Page 1::Detail 01 ",
        )

    assert result == {"status": "success"}
    client.send_command.assert_called_once_with(
        "orbit_camera",
        {
            "direction": "left",
            "angle_degrees": 22.5,
            "viewport_name": "Page 1::Detail 01",
        },
    )


def test_tcp_orbit_omits_unspecified_viewport():
    client = MagicMock()

    with patch.object(VIEWPORT_CLIENT, "RhinoClient") as client_type:
        client_type.return_value.__enter__.return_value = client
        VIEWPORT_CLIENT.orbit_camera("up")

    client.send_command.assert_called_once_with(
        "orbit_camera",
        {"direction": "up", "angle_degrees": 15.0},
    )


@pytest.mark.parametrize(
    ("direction", "angle"),
    [
        ("clockwise", 15),
        ("right", 0),
        ("right", float("nan")),
        ("right", True),
    ],
)
def test_tcp_orbit_rejects_invalid_input_before_connecting(direction, angle):
    with (
        patch.object(VIEWPORT_CLIENT, "RhinoClient") as client_type,
        pytest.raises(ValueError),
    ):
        VIEWPORT_CLIENT.orbit_camera(direction, angle)

    client_type.assert_not_called()


def test_tcp_orbit_source_does_not_send_legacy_yaw_pitch_fields():
    source = VIEWPORT_CLIENT_PATH.read_text(encoding="utf-8")

    orbit_block = source[source.index("def orbit_camera("):source.index("def set_camera(")]
    assert '"yaw"' not in orbit_block
    assert '"pitch"' not in orbit_block
    assert '"direction"' in orbit_block
    assert '"angle_degrees"' in orbit_block


def test_tcp_set_camera_uses_plugin_parameter_contract():
    client = MagicMock()
    client.send_command.return_value = {"status": "success"}

    with patch.object(VIEWPORT_CLIENT, "RhinoClient") as client_type:
        client_type.return_value.__enter__.return_value = client
        result = VIEWPORT_CLIENT.set_camera(
            [10, 20, 30],
            [0, 0, 0],
            35.0,
            "Perspektive",
        )

    assert result == {"status": "success"}
    client.send_command.assert_called_once_with(
        "set_camera",
        {
            "camera_location": [10, 20, 30],
            "target_location": [0, 0, 0],
            "lens_length": 35.0,
            "viewport_name": "Perspektive",
        },
    )


def test_tcp_capture_uses_configured_windows_path_and_reports_mapping(tmp_path):
    client = MagicMock()
    client.send_command.return_value = {
        "status": "success",
        "result": {"saved_to_file": "capture.png"},
    }
    windows_dir = r"\\path\to\your\directory"

    with (
        patch.dict(
            VIEWPORT_CLIENT.CONFIG,
            {
                "screenshots": {
                    "linux_dir": str(tmp_path),
                    "windows_dir": windows_dir,
                }
            },
            clear=True,
        ),
        patch.object(VIEWPORT_CLIENT, "RhinoClient") as client_type,
    ):
        client_type.return_value.__enter__.return_value = client
        result = VIEWPORT_CLIENT.capture_viewport(filename="capture.png")

    expected_windows_path = windows_dir + r"\capture.png"
    client.send_command.assert_called_once_with(
        "capture_viewport",
        {
            "viewport_name": "Perspective",
            "width": 1920,
            "height": 1080,
            "filename": expected_windows_path,
        },
    )
    assert result["result"]["linux_path"] == str(tmp_path / "capture.png")
    assert result["result"]["windows_path"] == expected_windows_path


@pytest.mark.parametrize("windows_dir", [None, "", "/tmp/captures", "relative"])
def test_tcp_capture_without_absolute_windows_path_fails_before_connecting(
    windows_dir,
):
    with (
        patch.dict(
            VIEWPORT_CLIENT.CONFIG,
            {
                "screenshots": {
                    "linux_dir": "/tmp/captures",
                    "windows_dir": windows_dir,
                }
            },
            clear=True,
        ),
        patch.object(VIEWPORT_CLIENT, "RhinoClient") as client_type,
        pytest.raises(ValueError, match="absolute Windows or UNC path"),
    ):
        VIEWPORT_CLIENT.capture_viewport(filename="capture.png")

    client_type.assert_not_called()
