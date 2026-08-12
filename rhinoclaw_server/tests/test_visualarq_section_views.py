import json
from pathlib import Path
from unittest.mock import MagicMock, patch


PATCH = "rhinoclaw.tools.visualarq_documentation.get_rhino_connection"
ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "rhinoclaw_plugin"
FUNCTIONS = PLUGIN / "Functions"
SOURCE_PATH = FUNCTIONS / "VisualArqSectionViewOperations.cs"
DOCUMENTATION_SOURCE_PATH = FUNCTIONS / "VisualArqDocumentationOperations.cs"


def _connection(result):
    connection = MagicMock()
    connection.send_command.return_value = result
    return connection


def _read_guard():
    return {
        "covered_state_unchanged": True,
        "visualarq_style_state": {"unchanged": True},
    }


@patch(PATCH)
def test_list_section_views_requires_complete_guarded_inventory(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_list_section_views

    rhino = _connection({
        "status": "success",
        "count": 1,
        "section_views": [{
            "id": "11111111-1111-1111-1111-111111111111",
            "source_section": {
                "id": "22222222-2222-2222-2222-222222222222",
            },
        }],
        "read_complete": True,
        "state_guard": _read_guard(),
    })
    mock_connection.return_value = rhino

    result = json.loads(va_list_section_views(MagicMock()))

    assert result["success"] is True
    assert result["data"]["read_complete"] is True
    rhino.send_command.assert_called_once_with("va_list_section_views", {})


@patch(PATCH)
def test_get_section_view_canonicalizes_exact_object_guid(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_get_section_view

    rhino = _connection({
        "status": "success",
        "section_view": {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        },
        "read_complete": True,
        "state_guard": _read_guard(),
    })
    mock_connection.return_value = rhino

    result = json.loads(va_get_section_view(
        MagicMock(), "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"))

    assert result["success"] is True
    rhino.send_command.assert_called_once_with(
        "va_get_section_view",
        {"section_view_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
    )


@patch(PATCH)
def test_get_section_view_rejects_bad_guid_before_roundtrip(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_get_section_view

    result = json.loads(va_get_section_view(MagicMock(), "not-a-guid"))

    assert result["success"] is False
    assert result["code"] == "INVALID_PARAMS"
    mock_connection.assert_not_called()


@patch(PATCH)
def test_create_section_view_sends_strict_normalized_contract(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_create_section_view

    section_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    style_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    rhino = _connection({
        "status": "success",
        "section_view": {
            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        },
        "bake": {"success": True},
        "verification": {"pass": True},
    })
    mock_connection.return_value = rhino

    result = json.loads(va_create_section_view(
        MagicMock(),
        section_id,
        [100, 200.5, 0],
        "  A-A  ",
        style_id,
        projection=False,
        auto_update=True,
    ))

    assert result["success"] is True
    rhino.send_command.assert_called_once_with(
        "va_create_section_view",
        {
            "section_id": section_id,
            "insertion_point": [100.0, 200.5, 0.0],
            "title": "A-A",
            "style_id": style_id,
            "projection": False,
            "auto_update": True,
        },
    )


@patch(PATCH)
def test_create_section_view_rejects_coercible_or_invalid_values(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_create_section_view

    section_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    style_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    cases = [
        ("bad", [0, 0, 0], "A-A", style_id, True, True),
        (section_id, [0, 0], "A-A", style_id, True, True),
        (section_id, [0, 0, float("inf")], "A-A", style_id, True, True),
        (section_id, [0, 0, 0], " ", style_id, True, True),
        (section_id, [0, 0, 0], "A-A", "bad", True, True),
        (section_id, [0, 0, 0], "A-A", style_id, 1, True),
        (section_id, [0, 0, 0], "A-A", style_id, True, "true"),
    ]

    for args in cases:
        result = json.loads(va_create_section_view(MagicMock(), *args))
        assert result["success"] is False
        assert result["code"] == "INVALID_PARAMS"

    mock_connection.assert_not_called()


@patch(PATCH)
def test_section_view_success_evidence_is_entity_specific(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_create_section_view

    section_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    style_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    malformed = [
        {
            "status": "success",
            "section": {"id": "cccccccc-cccc-cccc-cccc-cccccccccccc"},
            "bake": {"success": True},
            "verification": {"pass": True},
        },
        {
            "status": "success",
            "section_view": {
                "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            },
            "bake": {"success": False},
            "verification": {"pass": True},
        },
        {
            "status": "success",
            "section_view": {
                "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            },
            "bake": {"success": True},
            "verification": {"pass": False},
        },
    ]
    rhino = _connection({})
    rhino.send_command.side_effect = malformed
    mock_connection.return_value = rhino

    for _ in malformed:
        result = json.loads(va_create_section_view(
            MagicMock(), section_id, [0, 0, 0], "A-A", style_id))
        assert result["success"] is False
        assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_section_view_partial_mutation_preserves_safe_recovery_evidence(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_create_section_view

    section_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    style_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    view_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    mock_connection.return_value = _connection({
        "status": "error",
        "code": "PARTIAL_MUTATION",
        "message": "typed readback failed",
        "source_section_id": section_id,
        "created_section_view_ids": [view_id],
        "cleanup_refused_reason": "delete can cascade to source",
        "recovery": "Use outer Rhino Undo",
    })

    result = json.loads(va_create_section_view(
        MagicMock(), section_id, [0, 0, 0], "A-A", style_id))

    assert result["success"] is False
    assert result["code"] == "PARTIAL_MUTATION"
    assert result["data"]["source_section_id"] == section_id
    assert result["data"]["created_section_view_ids"] == [view_id]
    assert "cascade" in result["data"]["cleanup_refused_reason"]
    assert "Undo" in result["data"]["recovery"]


def test_installed_catalog_freezes_section_view_component_contracts():
    catalog_path = (
        ROOT / "rhinoclaw_server" / "src" / "rhinoclaw" / "static" /
        "gh_components.json"
    )
    catalog = json.loads(catalog_path.read_text())
    by_guid = {item["guid"]: item for item in catalog["components"]}

    options = by_guid["56d3f889-2a72-4c7f-ad5b-8d68ef70fb88"]
    assert options["name"] == "Section View Options"
    assert [(port["n"], port["t"]) for port in options["in"]] == [
        ("Style", "Section View Style"),
        ("Title", "Text"),
        ("Projection", "Boolean"),
        ("Autoupdate", "Boolean"),
    ]
    assert [(port["n"], port["t"]) for port in options["out"]] == [
        ("Options", "Section View Options"),
    ]

    creator = by_guid["0e35b09a-d2c3-4f2f-8b17-fb2e9c71ad2b"]
    assert creator["name"] == "Section View"
    assert [(port["n"], port["t"]) for port in creator["in"]] == [
        ("Point", "Point"),
        ("Section", "section"),
        ("Options", "Section View Options"),
    ]
    assert [(port["n"], port["t"]) for port in creator["out"]] == [
        ("SectionView", "section view"),
    ]


def test_section_view_handler_freezes_typed_readback_and_source_identity():
    source = SOURCE_PATH.read_text()
    shared_source = DOCUMENTATION_SOURCE_PATH.read_text()
    expected_guids = {
        "aa4245dd-ea57-424a-86e0-37acba641944",
        "93c4de63-3cb0-403c-aa16-809a6c2445ce",
        "56d3f889-2a72-4c7f-ad5b-8d68ef70fb88",
        "0e35b09a-d2c3-4f2f-8b17-fb2e9c71ad2b",
        "95008c3f-7b3e-419f-9192-9831e6a37bd6",
        "d5c9c2dd-7dd9-4d00-8d79-16bd8bc296b4",
    }
    assert all(guid in source.lower() for guid in expected_guids)
    assert 'FindUniqueRuntimeType("GhVaSectionView")' in source
    assert 'FindUniqueRuntimeType("GhVaSection")' in source
    assert 'FindUniqueRuntimeType("GhVaSectionViewStyle")' in source
    assert '"ReferenceID", "ReferenceId"' in source
    assert "sourceSectionId.Value" in source
    assert '"insertion_point"' in source
    assert '"projection"' in source
    assert '"auto_update"' in source
    assert '"title"' in source
    assert '"non_empty"' in source
    assert "TryCreateVerifiedLoadedVisualArqDocumentationGoo(" in source
    assert "TryInvokeLoadObject" in shared_source
    assert "IsSectionView" not in source


def test_section_view_readback_verifies_identity_before_deconstruct():
    source = SOURCE_PATH.read_text()
    shared_source = DOCUMENTATION_SOURCE_PATH.read_text()
    loader = source.split(
        "private static bool TryCreateLoadedSectionViewGoo", 1
    )[1].split("private static JObject ReadSectionViewSnapshot", 1)[0]
    snapshot = source.split(
        "private static JObject ReadSectionViewSnapshot", 1
    )[1].split("private static JObject VerifyCreatedSectionView", 1)[0]
    identity = shared_source.split(
        "private static JObject VerifyLoadedVisualArqDocumentationGoo", 1
    )[1].split("private static object CreateLoadedSectionGoo", 1)[0]

    assert "TryCreateVerifiedLoadedVisualArqDocumentationGoo(" in loader
    assert '"GhVaSectionView"' in loader
    assert snapshot.index(
        "VerifyLoadedVisualArqDocumentationGoo("
    ) < snapshot.index("CreateValidatedVaParam(")
    assert "!goo.IsValid" in identity
    assert 'ReadRequiredBooleanProperty(goo, "IsObjectLoaded")' in identity
    assert "referenceId.Value != requestedObjectId" in identity
    assert '["is_valid"] = true' in identity
    assert '["is_object_loaded"] = true' in identity
    assert '["reference_id"] = referenceId.Value.ToString()' in identity


def test_section_view_readback_verifies_transient_document_lifecycle():
    source = SOURCE_PATH.read_text()
    snapshot = source.split(
        "private static JObject ReadSectionViewSnapshot", 1
    )[1].split("private static JObject VerifyCreatedSectionView", 1)[0]

    assert "using var ghDoc" not in snapshot
    assert "documentServer.Contains(ghDoc)" in snapshot
    assert '["transient_document_registered"] = true' in snapshot
    assert "CleanupGrasshopperBuildDocument(" in snapshot
    assert '["transient_document_cleanup"] = cleanup' in snapshot
    assert 'cleanup["complete"]?.Value<bool>() != true' in snapshot


def test_section_view_create_solves_and_bakes_one_exact_native_item():
    source = SOURCE_PATH.read_text()
    create = source.split(
        "public JObject CreateVisualArqSectionView", 1)[1].split(
            "private static void ValidateSectionViewReadContract", 1)[0]

    assert create.count("ghDoc.NewSolution(") == 1
    assert create.count("BakeSingleNativeItem(") == 1
    assert "atomic: true" not in source
    assert "CleanupOwnedAdditions" not in source
    assert "doc.Objects.Delete" not in source
    assert "outputItems.Count != 1" in create
    assert "outputItems[0].GetType() != expectedViewGooType" in create
    assert "outputItems[0] is not IGH_BakeAwareData" in create
    assert "bake.AddedIds.Count != 1" in create
    assert "CreateLoadedSectionGoo(doc, sectionId)" in create
    assert "sourceReferenceId.Value != sectionId" in create
    assert "VerifyCreatedSectionView" in create
    assert "VerifyAddedDefinitionOwnership" in create
    assert create.count("CaptureDocumentBaseline(doc)") == 1
    assert create.index("CaptureDocumentBaseline(doc)") < create.index(
        "CreateValidatedVaParam(")
    assert create.index("CaptureDocumentBaseline(doc)") < create.index(
        "CreateLoadedSectionGoo(doc, sectionId)")
    assert create.index(
        "styleInventoryBefore = CaptureVisualArqStyleInventory(styleId)"
    ) < create.index("CreateValidatedVaParam(")
    assert create.index("CreateLoadedStyleGoo(") < create.index(
        'phase: "immediately_before_section_view_first_solve"')
    assert create.index(
        'phase: "immediately_before_section_view_first_solve"'
    ) < create.index("ghDoc.NewSolution(")
    pre_solve_guard = create[
        create.index("JObject styleInventoryPreSolve"):
        create.index("ghDoc.NewSolution(")
    ]
    assert "VerifyReadOnlyCall(" in pre_solve_guard
    assert "StyleInventoriesEqual(" in pre_solve_guard
    assert "section_view_pre_solve_failure_guard" in create
    assert "pre_solve_state_guard" in create
    assert create.index("doc.Views.Redraw()") < create.index(
        "ReadSectionViewSnapshot(")
    assert create.index("ReadSectionViewSnapshot(") < create.index(
        'phase: "final_after_section_view_typed_and_domain_readback"')
    assert create.index("VerifyAddedDefinitionOwnership(") < create.index(
        'phase: "final_after_section_view_typed_and_domain_readback"')
    assert "live_gates_pending" in source
    assert "created_section_view_ids" in source
    assert "source_section_id" in source
    assert "source_section_was_preexisting" in source
    assert "cleanup_refused_reason" in source
    assert "linked_section_view_delete_cascade_not_ownership_safe" in source
    assert "Use the outer Rhino command Undo" in source


def test_section_view_reads_have_rhino_and_global_style_guards():
    source = SOURCE_PATH.read_text()
    reads = source.split(
        "public JObject ListVisualArqSectionViews", 1)[1].split(
            "public JObject CreateVisualArqSectionView", 1)[0]

    assert reads.count("CaptureDocumentBaseline(doc)") == 2
    assert reads.count("CaptureVisualArqStyleInventory()") >= 4
    assert reads.count("VerifyReadOnlyCall(") >= 4
    assert reads.count("ReadOnlyStateFailure(") >= 4
    assert 'result["code"] = "PARTIAL_MUTATION"' in (
        FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()


def test_shared_definition_ownership_is_low_level_and_cleanup_is_owned():
    service = (FUNCTIONS / "GrasshopperBakeService.cs").read_text()
    section = (
        FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()
    view = SOURCE_PATH.read_text()

    assert "internal static JObject VerifyAddedDefinitionOwnership" in service
    assert "reachable_instance_definition_ids" in service
    assert "unexpected_added_instance_definition_ids" in service
    assert "created_{kind}_is_not_an_instance_object" in service
    assert "GrasshopperBakeService.VerifyAddedDefinitionOwnership" in section
    assert "GrasshopperBakeService.VerifyAddedDefinitionOwnership" in view
    assert "CleanupOwnedAdditions" in service
    assert "plugin-private" in section


def test_section_view_commands_are_dispatched_advertised_and_reexported():
    server = (PLUGIN / "RhinoClawServer.cs").read_text()
    capabilities = (FUNCTIONS / "ListCapabilities.cs").read_text()
    for command, handler in {
        "va_list_section_views": "ListVisualArqSectionViews",
        "va_get_section_view": "GetVisualArqSectionView",
        "va_create_section_view": "CreateVisualArqSectionView",
    }.items():
        assert f'["{command}"]' in server
        assert f"this.handler.{handler}" in server
        assert f'"{command}"' in capabilities

    import rhinoclaw

    assert callable(rhinoclaw.va_list_section_views)
    assert callable(rhinoclaw.va_get_section_view)
    assert callable(rhinoclaw.va_create_section_view)
