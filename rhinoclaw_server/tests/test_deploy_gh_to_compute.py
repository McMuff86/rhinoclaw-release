import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def no_rhino():
    """Keep tests hermetic: no real TCP connection attempts from validation."""
    with patch(
        "rhinoclaw.tools.deploy_gh_to_compute.get_rhino_connection",
        side_effect=ConnectionError("no Rhino in unit tests"),
    ) as mock_conn:
        yield mock_conn


def _mock_inspection(inspection):
    """Patch get_rhino_connection with a connection returning `inspection`."""
    rhino = MagicMock()
    rhino.send_command.return_value = inspection
    return patch(
        "rhinoclaw.tools.deploy_gh_to_compute.get_rhino_connection",
        return_value=rhino,
    )


def test_deploys_definition_into_compute_definitions(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    compute_root = tmp_path / "compute"
    definitions = compute_root / "definitions"
    definitions.mkdir(parents=True)
    source = tmp_path / "door.gh"
    source.write_bytes(b"grasshopper")

    result = deploy_gh_to_compute(None, str(source), str(compute_root))
    data = json.loads(result)

    assert data["success"] is True
    assert data["data"]["definition"] == "door.gh"
    assert (definitions / "door.gh").read_bytes() == b"grasshopper"
    assert data["data"]["metadata_source"] == "none"


def test_accepts_definitions_dir_directly(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = tmp_path / "box.ghx"
    source.write_bytes(b"xml")

    result = deploy_gh_to_compute(None, str(source), str(definitions), "renamed.ghx")
    data = json.loads(result)

    assert data["success"] is True
    assert (definitions / "renamed.ghx").exists()


def test_copies_adjacent_metadata_sidecar(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = tmp_path / "door.gh"
    source.write_bytes(b"grasshopper")
    source.with_suffix(".meta.json").write_text(
        '{"name": "Door", "params": {"Width": {"type": "number"}}}\n',
        encoding="utf-8",
    )

    result = deploy_gh_to_compute(None, str(source), str(definitions))
    data = json.loads(result)

    assert data["success"] is True
    assert data["data"]["metadata_source"] == "sidecar"
    assert (definitions / "door.meta.json").exists()


def test_writes_inline_metadata(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = tmp_path / "door.gh"
    source.write_bytes(b"grasshopper")

    result = deploy_gh_to_compute(
        None,
        str(source),
        str(definitions),
        metadata={
            "schemaVersion": "1.0",
            "name": "Door",
            "params": {"Width": {"type": "number", "default": 900}},
        },
    )
    data = json.loads(result)

    assert data["success"] is True
    assert data["data"]["metadata_source"] == "inline"
    meta = json.loads((definitions / "door.meta.json").read_text(encoding="utf-8"))
    assert meta["params"]["Width"]["default"] == 900


def test_rejects_path_traversal_target_name(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = tmp_path / "door.gh"
    source.write_bytes(b"grasshopper")

    result = deploy_gh_to_compute(None, str(source), str(definitions), "../door.gh")
    data = json.loads(result)

    assert data["success"] is False
    assert "filename" in data["message"]


def test_respects_overwrite_false(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = tmp_path / "door.gh"
    source.write_bytes(b"new")
    (definitions / "door.gh").write_bytes(b"old")

    result = deploy_gh_to_compute(None, str(source), str(definitions), overwrite=False)
    data = json.loads(result)

    assert data["success"] is False
    assert (definitions / "door.gh").read_bytes() == b"old"


def test_does_not_copy_definition_when_metadata_overwrite_is_blocked(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = tmp_path / "door.gh"
    source.write_bytes(b"new")
    source.with_suffix(".meta.json").write_text('{"params": {}}\n', encoding="utf-8")
    (definitions / "door.meta.json").write_text('{"old": true}\n', encoding="utf-8")

    result = deploy_gh_to_compute(None, str(source), str(definitions), overwrite=False)
    data = json.loads(result)

    assert data["success"] is False
    assert not (definitions / "door.gh").exists()
    assert json.loads((definitions / "door.meta.json").read_text(encoding="utf-8")) == {"old": True}


# --- Compute-contract validation (the RH_OUT learning as a guardrail) ---

def _setup(tmp_path):
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = tmp_path / "door.gh"
    source.write_bytes(b"grasshopper")
    return definitions, source


def test_validation_skipped_without_rhino_still_deploys(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions, source = _setup(tmp_path)
    result = deploy_gh_to_compute(None, str(source), str(definitions))
    data = json.loads(result)

    assert data["success"] is True
    assert data["data"]["validation"]["status"] == "skipped"
    assert (definitions / "door.gh").exists()


def test_validate_false_never_touches_rhino(tmp_path, no_rhino):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions, source = _setup(tmp_path)
    result = deploy_gh_to_compute(None, str(source), str(definitions), validate=False)
    data = json.loads(result)

    assert data["success"] is True
    assert data["data"]["validation"]["status"] == "skipped"
    no_rhino.assert_not_called()


def test_rh_out_script_output_blocks_deploy(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions, source = _setup(tmp_path)
    inspection = {
        "script_components": [{
            "nickname": "Fenster",
            "outputs": [{"name": "RH_OUT:Frame", "nickname": "RH_OUT:Frame"}],
        }],
        "groups": [],
        "script_component_count": 1,
        "headless_solvable": False,
    }
    with _mock_inspection(inspection):
        result = deploy_gh_to_compute(None, str(source), str(definitions))
    data = json.loads(result)

    assert data["success"] is False
    assert not (definitions / "door.gh").exists()
    [err] = data["data"]["validation"]["errors"]
    assert "RH_OUT:Frame" in err
    assert "group" in err  # the fix hint points at the group pattern


def test_force_deploys_despite_validation_errors(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions, source = _setup(tmp_path)
    inspection = {
        "script_components": [{
            "nickname": "Fenster",
            "outputs": [{"nickname": "RH_OUT:Frame"}],
        }],
        "groups": [],
    }
    with _mock_inspection(inspection):
        result = deploy_gh_to_compute(None, str(source), str(definitions), force=True)
    data = json.loads(result)

    assert data["success"] is True
    assert data["data"]["validation"]["status"] == "failed"
    assert (definitions / "door.gh").exists()


def test_missing_rh_out_group_warns_but_deploys(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions, source = _setup(tmp_path)
    inspection = {
        "script_components": [{"nickname": "S", "outputs": [{"nickname": "a"}]}],
        "groups": [{"nickname": "just_a_label", "member_count": 1}],
    }
    with _mock_inspection(inspection):
        result = deploy_gh_to_compute(None, str(source), str(definitions))
    data = json.loads(result)

    assert data["success"] is True
    validation = data["data"]["validation"]
    assert validation["status"] == "passed"
    assert any("RH_OUT" in w for w in validation["warnings"])


def test_clean_definition_passes_without_warnings(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions, source = _setup(tmp_path)
    inspection = {
        "script_components": [{"nickname": "S", "outputs": [{"nickname": "Fenster"}]}],
        "groups": [{"nickname": "RH_OUT:Fenster", "member_count": 1}],
        "script_component_count": 1,
        "headless_solvable": False,
    }
    with _mock_inspection(inspection):
        result = deploy_gh_to_compute(None, str(source), str(definitions))
    data = json.loads(result)

    assert data["success"] is True
    validation = data["data"]["validation"]
    assert validation["status"] == "passed"
    assert validation["errors"] == []
    assert validation["warnings"] == []


def test_meta_output_without_matching_group_warns(tmp_path):
    from rhinoclaw.tools.deploy_gh_to_compute import deploy_gh_to_compute

    definitions, source = _setup(tmp_path)
    inspection = {
        "script_components": [],
        "groups": [{"nickname": "RH_OUT:Fenster", "member_count": 1}],
    }
    metadata = {"name": "Door", "outputs": [{"name": "RH_OUT:Tor"}]}
    with _mock_inspection(inspection):
        result = deploy_gh_to_compute(
            None, str(source), str(definitions), metadata=metadata
        )
    data = json.loads(result)

    assert data["success"] is True
    assert any("RH_OUT:Tor" in w for w in data["data"]["validation"]["warnings"])


def test_wsl_path_translates_to_windows_drive():
    from pathlib import Path

    from rhinoclaw.tools.deploy_gh_to_compute import _to_rhino_path

    assert _to_rhino_path(Path("/mnt/c/Users/adi/door.gh")) == "C:/Users/adi/door.gh"
    assert _to_rhino_path(Path("C:/Users/adi/door.gh")) == "C:/Users/adi/door.gh"
