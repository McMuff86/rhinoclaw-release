"""Dedicated Rahmentuer MCP tool: preflight, invocation and readback verdict."""

import json
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.utils.kits import RESULT_PREFIX


INSTANCE_ID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def assets(tmp_path):
    for name in (
        "rahmentuer.py",
        "block_hardware.py",
        "SFS_HE18EI30-M10X1X30-FIX V3.3dm",
        "Sudmetall_TopSpeed_32.51.6600_RZ.3dm",
        "Glutz Treplane 1834 mit Schliessblech V2.3dm",
    ):
        (tmp_path / name).write_bytes(b"fixture")
    return tmp_path


def _engine(payload=None, *, success=True):
    if not success:
        return {
            "success": False,
            "message": "builder failed",
            "rollback_performed": True,
        }
    value = payload if payload is not None else {
        "block_name": "RT.TEST.01",
        "instance_id": INSTANCE_ID,
        "insert_point": [1000.0, 200.0, 0.0],
        "parts": 11,
        "config": {"outer_width": 1120.0, "outer_height": 2180.0},
    }
    return {
        "success": True,
        "result": "builder output\n" + RESULT_PREFIX + json.dumps(value),
        "engine": "python3",
        "duration_ms": 42,
    }


def _object_readback(*, name="RT.TEST.01", bbox=None):
    return {
        "count": 1,
        "missing_count": 0,
        "results": [{
            "id": INSTANCE_ID,
            "name": name,
            "type": "InstanceReference",
            "bounding_box": bbox or [[1000.0, 87.0, 0.0], [2120.0, 295.0, 2180.0]],
            "attributes": {
                "TEILNR_PREFIX": name,
                "TEILNR_PREFIX_SOURCE": name,
            },
        }],
        "missing": [],
    }


def _definition_readback(*, name="RT.TEST.01", object_count=11):
    return {
        "definitions": [{
            "name": name,
            "id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "object_count": object_count,
            "instance_count": 1,
            "bbox": {"min": [0.0, -113.0, 0.0],
                     "max": [1120.0, 95.0, 2180.0]},
        }],
        "count": 1,
        "total_count": 1,
        "truncated": False,
    }


def _call(assets, rhino, **kwargs):
    from rhinoclaw.tools.insert_rahmentuer import insert_rahmentuer

    params = {
        "block_name": "RT.TEST.01",
        "point": [1000, 200, 0],
        "lichtbreite": 900,
        "asset_root": str(assets),
    }
    params.update(kwargs)
    with patch(
        "rhinoclaw.tools.insert_rahmentuer.get_rhino_connection",
        return_value=rhino,
    ):
        return json.loads(insert_rahmentuer(MagicMock(), **params))


def _source_payload(source):
    line = next(
        item for item in source.splitlines()
        if item.startswith("_payload = json.loads(")
    )
    literal = line[len("_payload = json.loads("):-1]
    return json.loads(json.loads(literal))


def test_success_invokes_python3_then_independently_verifies(assets):
    rhino = MagicMock()
    rhino.send_command.side_effect = [
        _engine(),
        _object_readback(),
        _definition_readback(),
    ]

    parsed = _call(assets, rhino)

    assert parsed["success"] is True
    data = parsed["data"]
    assert data["status"] == "success"
    assert data["parts"] == 11
    assert data["verification"]["pass"] is True
    assert data["verification"]["failed_checks"] == []
    assert [call.args[0] for call in rhino.send_command.call_args_list] == [
        "execute_python3_code",
        "get_objects_info",
        "list_block_definitions",
    ]
    source = rhino.send_command.call_args_list[0].args[1]["code"]
    assert "build_rahmentuer_block" in source
    assert "entry_dir = os.path.dirname(entry)" in source
    assert "sys.path.insert(0, entry_dir)" in source
    payload = _source_payload(source)
    assert payload["args"]["overrides"]["lichtbreite"] == 900.0
    assert payload["args"]["block_name"] == "RT.TEST.01"
    assert rhino.send_command.call_args_list[0].kwargs["timeout"] == 180.0
    assert rhino.send_command.call_args_list[1].args[1] == {"ids": [INSTANCE_ID]}


def test_explicit_dimensions_win_over_advanced_overrides(assets):
    rhino = MagicMock()
    rhino.send_command.side_effect = [
        _engine(), _object_readback(), _definition_readback(),
    ]

    parsed = _call(
        assets,
        rhino,
        lichtbreite=900,
        overrides={"lichtbreite": 123, "rahmenbreite_l": 120,
                   "rahmenbreite_r": 100},
    )

    assert parsed["success"] is True
    source = rhino.send_command.call_args_list[0].args[1]["code"]
    payload = _source_payload(source)
    assert payload["args"]["overrides"]["lichtbreite"] == 900.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"block_name": " "}, "block_name"),
        ({"point": [1, 2]}, "point"),
        ({"lichtbreite": 0}, "lichtbreite"),
        ({"lichthoehe": float("nan")}, "lichthoehe"),
        ({"bandseite": "oben"}, "bandseite"),
        ({"timeout": 301}, "timeout"),
        ({"overrides": []}, "overrides"),
        ({"sfs_enabled": "false"}, "sfs_enabled"),
        ({"overrides": {"bad": float("inf")}}, "overrides"),
    ],
)
def test_invalid_request_never_connects(assets, kwargs, message):
    rhino = MagicMock()

    parsed = _call(assets, rhino, **kwargs)

    assert parsed["success"] is False
    assert parsed["code"] == "INVALID_PARAMS"
    assert message in parsed["message"]
    rhino.send_command.assert_not_called()


def test_incomplete_asset_root_fails_before_rhino(tmp_path):
    (tmp_path / "rahmentuer.py").write_text("", encoding="utf-8")
    rhino = MagicMock()

    parsed = _call(tmp_path, rhino)

    assert parsed["success"] is False
    assert parsed["code"] == "PRECONDITION_FAILED"
    assert "block_hardware.py" in parsed["message"]
    rhino.send_command.assert_not_called()


def test_disabled_hardware_does_not_require_vendor_files(tmp_path):
    (tmp_path / "rahmentuer.py").write_text("", encoding="utf-8")
    (tmp_path / "block_hardware.py").write_text("", encoding="utf-8")
    rhino = MagicMock()
    rhino.send_command.side_effect = [
        _engine({
            "block_name": "RT.TEST.01",
            "instance_id": INSTANCE_ID,
            "parts": 6,
        }),
        _object_readback(),
        _definition_readback(object_count=6),
    ]

    parsed = _call(
        tmp_path, rhino, sfs_enabled=False, glutz_enabled=False,
    )

    assert parsed["success"] is True


def test_script_failure_reports_rollback_and_skips_readback(assets):
    rhino = MagicMock()
    rhino.send_command.return_value = _engine(success=False)

    parsed = _call(assets, rhino)

    assert parsed["success"] is False
    assert parsed["code"] == "SCRIPT_ERROR"
    assert parsed["data"]["engine"]["rollback_performed"] is True
    assert rhino.send_command.call_count == 1


def test_script_failure_without_proven_rollback_is_partial_mutation(assets):
    rhino = MagicMock()
    rhino.send_command.return_value = {
        "success": False,
        "message": "builder failed",
        "rollback_performed": False,
    }

    parsed = _call(assets, rhino)

    assert parsed["success"] is False
    assert parsed["code"] == "PARTIAL_MUTATION"


def test_no_instance_is_resource_in_use_not_success(assets):
    rhino = MagicMock()
    rhino.send_command.return_value = _engine({"ok": True, "result": None})

    parsed = _call(assets, rhino)

    assert parsed["success"] is False
    assert parsed["code"] == "RESOURCE_IN_USE"
    assert rhino.send_command.call_count == 1


def test_readback_mismatch_is_truthful_partial_mutation(assets):
    rhino = MagicMock()
    rhino.send_command.side_effect = [
        _engine(),
        _object_readback(name="WRONG"),
        _definition_readback(),
    ]

    parsed = _call(assets, rhino)

    assert parsed["success"] is False
    assert parsed["code"] == "PARTIAL_MUTATION"
    assert parsed["data"]["verification"]["pass"] is False
    assert "instance_name" in parsed["data"]["verification"]["failed_checks"]


def test_unsupported_hardware_key_fails_closed(assets):
    rhino = MagicMock()

    parsed = _call(
        assets,
        rhino,
        overrides={"sfs_hardware_key": "invented"},
    )

    assert parsed["success"] is False
    assert parsed["code"] == "PRECONDITION_FAILED"
    assert "invented" in parsed["message"]
    rhino.send_command.assert_not_called()
