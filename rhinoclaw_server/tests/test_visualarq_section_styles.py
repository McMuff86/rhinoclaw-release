import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


PATCH = "rhinoclaw.tools.visualarq_documentation.get_rhino_connection"
ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "rhinoclaw_plugin"
    / "Functions"
    / "VisualArqSectionStyleOperations.cs"
)
PLUGIN = ROOT / "rhinoclaw_plugin"


def _connection(result):
    connection = MagicMock()
    connection.send_command.return_value = result
    return connection


def _unsupported_gate(**overrides):
    result = {
        "status": "error",
        "code": "UNSUPPORTED_OPERATION",
        "message": "complete Section Style inventory is unavailable",
        "phase": "pre_proxy_pre_solve_pre_bake",
        "mutation_phase_started": False,
        "proxy_instantiation_attempted": False,
        "graph_constructed": False,
        "solve_attempted": False,
        "solve_count": 0,
        "bake_attempted": False,
        "bake_count": 0,
        "collision_guard": {
            "required_inventory_method": "GetAllSectionStyleIds",
            "inventory_complete": False,
            "name_absence_proven": False,
            "case_insensitive_exact_name_matches": [],
        },
        "runtime_contract": {
            "script_version_verified": True,
            "creator": {
                "guid": "1450aecb-482e-4691-bba5-00572baf2c35",
            },
        },
        "state_guard": {
            "covered_state_unchanged": True,
            "visualarq_style_state": {"unchanged": True},
        },
    }
    result.update(overrides)
    return result


@pytest.mark.parametrize("name", [None, "", "   "])
@patch(PATCH)
def test_create_section_style_rejects_empty_name_without_roundtrip(
    mock_connection,
    name,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_create_section_style,
    )

    result = json.loads(va_create_section_style(MagicMock(), name))

    assert result["success"] is False
    assert result["code"] == "INVALID_PARAMS"
    mock_connection.assert_not_called()


@patch(PATCH)
def test_create_section_style_normalizes_name_and_preserves_guarded_blocker(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_create_section_style,
    )

    rhino = _connection(_unsupported_gate())
    mock_connection.return_value = rhino

    result = json.loads(va_create_section_style(
        MagicMock(), "  RC Section 01  "))

    assert result["success"] is False
    assert result["code"] == "UNSUPPORTED_OPERATION"
    assert result["data"]["mutation_phase_started"] is False
    assert result["data"]["collision_guard"]["inventory_complete"] is False
    rhino.send_command.assert_called_once_with(
        "va_create_section_style", {"name": "RC Section 01"})


@patch(PATCH)
def test_create_section_style_rejects_unsupported_without_complete_evidence(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_create_section_style,
    )

    mock_connection.return_value = _connection(_unsupported_gate(
        proxy_instantiation_attempted=True,
    ))

    result = json.loads(va_create_section_style(MagicMock(), "RC Section 01"))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_create_section_style_never_accepts_unproven_success(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import (
        va_create_section_style,
    )

    mock_connection.return_value = _connection({
        "status": "success",
        "style": {"id": "11111111-1111-1111-1111-111111111111"},
    })

    result = json.loads(va_create_section_style(MagicMock(), "RC Section 01"))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


def test_section_style_handler_is_pre_proxy_pre_solve_pre_bake_fail_closed():
    source = SOURCE.read_text()
    create = source.split(
        "public JObject CreateVisualArqSectionStyle", 1)[1].split(
            "private static JArray SectionStyleNameCollisions", 1)[0]

    baseline = create.index("CaptureDocumentBaseline(doc)")
    inventory = create.index("CaptureVisualArqStyleInventory()")
    script_contract = create.index('"GetStyleName", typeof(string)')
    assert baseline < inventory < script_contract
    assert '"UNSUPPORTED_OPERATION"' in create
    assert '"pre_proxy_pre_solve_pre_bake"' in create
    assert '["mutation_phase_started"] = false' in create
    assert '["proxy_instantiation_attempted"] = false' in create
    assert '["graph_constructed"] = false' in create
    assert '["solve_attempted"] = false' in create
    assert '["solve_count"] = 0' in create
    assert '["bake_attempted"] = false' in create
    assert '["bake_count"] = 0' in create
    assert "CreateValidatedVaComponent(" not in create
    assert "CreateVaProxyInstance(" not in create
    assert "NewSolution(" not in create
    assert "BakeGeometry(" not in create
    assert "BakeSingleNativeItem(" not in create


def test_section_style_handler_has_truthful_inventory_and_collision_contract():
    source = SOURCE.read_text()

    assert '"GetAllSectionStyleIds"' in source
    assert "RequiredSectionStyleInventoryMethod" in source
    assert "hasCompleteSectionStyleInventory" in source
    assert "StringComparison.OrdinalIgnoreCase" in source
    assert '"name_absence_proven"' in source
    assert '"documentation_style_inventory_complete"' in source
    assert '"ALREADY_EXISTS"' in source
    assert '"INVALID_PARAMS"' not in source
    assert "CaptureVisualArqStyleInventory()" in source
    assert "StyleInventoriesEqual(styleBefore, styleAfter)" in source
    assert "ReadOnlyStateFailure(" in source
    assert "FindVisualArqScriptMethodAnyReturn(" not in source
    assert "GetAllSectionStyleIds()" not in source
    assert "an owned " in source and '"+1 style delta' in source


def test_section_style_handler_records_exact_version_pinned_gh_ground_truth():
    source = SOURCE.read_text()

    assert "1450aecb-482e-4691-bba5-00572baf2c35" in source
    assert "b8201cd5-cc23-47f8-81dc-871a4800a53a" in source
    for name, type_name in (
        ("Name", "Text"),
        ("Components", "Object"),
        ("Type", "Integer"),
        ("Size", "Number"),
        ("Offset", "Number"),
        ("Filled", "Boolean"),
        ("Mirrored", "Boolean"),
        ("Style", "Section Style"),
    ):
        assert f'SectionStylePort("{name}", "{type_name}"' in source
    assert 'SectionStylePort("Components", "Object", optional: true)' in source
    assert '["type"] = 1' in source
    assert '["size"] = 500.0' in source
    assert '["offset"] = 0.0' in source
    assert '["filled"] = false' in source
    assert '["mirrored"] = false' in source
    assert '"VisualARQ.Grasshopper.Types.GhVaSectionStyle"' in source
    assert '["implements_IGH_BakeAwareData"] = true' in source
    assert '["is_object_loaded"] = true' in source
    assert '["pre_bake_reference_handle"] = 0' in source
    assert '["pre_bake_reference_name"] = null' in source
    assert '["pre_bake_reference_id_available"] = false' in source
    assert '["script_variable_available"] = false' in source
    assert '["covered_rhino_object_delta"] = 0' in source
    assert '["transient_document_cleanup_verified"] = true' in source
    assert '"live_disposable_scratch_probe_not_this_call"' in source
    assert '["inline_section_bootstrap_probe"]' in source
    assert '["native_section_bake_returned"] = true' in source
    assert '["reported_id_matched_added_id"] = true' in source
    assert '["independent_readback_pass"] = false' in source
    assert '"Deconstruct Section returned an empty style name"' in source
    assert '["production_capability"] = false' in source
    assert '"whole_disposable_scratch_document_reset"' in source


def test_section_style_gate_is_registered_advertised_undo_free_and_reexported():
    server = (PLUGIN / "RhinoClawServer.cs").read_text()
    capabilities = (
        PLUGIN / "Functions" / "ListCapabilities.cs"
    ).read_text()

    assert (
        '["va_create_section_style"] = '
        "this.handler.CreateVisualArqSectionStyle"
    ) in " ".join(server.split())
    assert '"va_create_section_style"' in capabilities
    undo_free = server.split(
        "private static readonly HashSet<string> UndoFreeCommands", 1
    )[1].split("private JObject ExecuteCommandInternal", 1)[0]
    assert '"va_create_section_style"' in undo_free

    import rhinoclaw

    assert callable(rhinoclaw.va_create_section_style)
