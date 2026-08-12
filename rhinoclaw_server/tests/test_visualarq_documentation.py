import json
from pathlib import Path
from unittest.mock import MagicMock, patch


PATCH = (
    "rhinoclaw.tools.visualarq_documentation.get_rhino_connection"
)
ROOT = Path(__file__).resolve().parents[2]
PLUGIN_FUNCTIONS = ROOT / "rhinoclaw_plugin" / "Functions"


def _connection(result):
    rhino = MagicMock()
    rhino.send_command.return_value = result
    return rhino


def _passing_read_guard():
    return {
        "covered_state_unchanged": True,
        "visualarq_style_state": {"unchanged": True},
    }


@patch(PATCH)
def test_va_list_sections_wraps_complete_inventory(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_list_sections

    rhino = _connection({
        "status": "success",
        "count": 1,
        "sections": [{"id": "11111111-1111-1111-1111-111111111111"}],
        "read_complete": True,
        "state_guard": _passing_read_guard(),
    })
    mock_connection.return_value = rhino

    result = json.loads(va_list_sections(MagicMock()))

    assert result["success"] is True
    assert result["data"]["read_complete"] is True
    rhino.send_command.assert_called_once_with("va_list_sections", {})


@patch(PATCH)
def test_va_list_sections_preserves_partial_read_failure(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_list_sections

    mock_connection.return_value = _connection({
        "status": "error",
        "code": "VERIFICATION_FAILED",
        "message": "inventory incomplete",
        "sections": [],
        "read_complete": False,
        "readback_errors": [{"object_id": "x"}],
    })

    result = json.loads(va_list_sections(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"
    assert result["data"]["read_complete"] is False


@patch(PATCH)
def test_va_get_section_canonicalizes_guid(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_get_section

    rhino = _connection({
        "status": "success",
        "section": {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        "state_guard": _passing_read_guard(),
    })
    mock_connection.return_value = rhino

    result = json.loads(va_get_section(
        MagicMock(), "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"))

    assert result["success"] is True
    rhino.send_command.assert_called_once_with(
        "va_get_section",
        {"section_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
    )


@patch(PATCH)
def test_va_get_section_rejects_empty_guid_without_roundtrip(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_get_section

    result = json.loads(va_get_section(
        MagicMock(), "00000000-0000-0000-0000-000000000000"))

    assert result["success"] is False
    assert result["code"] == "INVALID_PARAMS"
    mock_connection.assert_not_called()


@patch(PATCH)
def test_va_create_section_sends_normalized_safe_contract(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_create_section

    style_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    rhino = _connection({
        "status": "success",
        "section": {"id": "cccccccc-cccc-cccc-cccc-cccccccccccc"},
        "bake": {"success": True},
        "verification": {"pass": True},
    })
    mock_connection.return_value = rhino

    result = json.loads(va_create_section(
        MagicMock(),
        [0, 0, 100],
        [1000, 0, 100],
        5000,
        "  A  ",
        style_id,
    ))

    assert result["success"] is True
    rhino.send_command.assert_called_once_with(
        "va_create_section",
        {
            "start": [0.0, 0.0, 100.0],
            "end": [1000.0, 0.0, 100.0],
            "depth": 5000.0,
            "reference": "A",
            "style_id": style_id,
        },
    )


@patch(PATCH)
def test_va_create_section_rejects_invalid_values_without_roundtrip(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_create_section

    style_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    cases = [
        ([0, 0], [1, 0, 0], 10, "A", style_id),
        ([0, 0, 0], [1, 0, 0], float("nan"), "A", style_id),
        ([0, 0, 0], [1, 0, 0], 10, " ", style_id),
        ([0, 0, 0], [1, 0, 0], 10, "A", "not-a-guid"),
    ]
    for start, end, depth, reference, candidate_style in cases:
        result = json.loads(va_create_section(
            MagicMock(), start, end, depth, reference, candidate_style))
        assert result["success"] is False
        assert result["code"] == "INVALID_PARAMS"

    mock_connection.assert_not_called()


@patch(PATCH)
def test_unknown_plugin_status_is_verification_failure(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_list_sections

    mock_connection.return_value = _connection({
        "count": 0,
        "sections": [],
    })

    result = json.loads(va_list_sections(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_read_success_requires_passing_covered_and_style_guards(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_get_section

    section_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    malformed = [
        {"status": "success", "section": {"id": section_id}},
        {
            "status": "success",
            "section": {"id": section_id},
            "state_guard": {
                "covered_state_unchanged": False,
                "visualarq_style_state": {"unchanged": True},
            },
        },
        {
            "status": "success",
            "section": {"id": section_id},
            "state_guard": {
                "covered_state_unchanged": True,
                "visualarq_style_state": {"unchanged": False},
            },
        },
    ]
    connection = _connection({})
    connection.send_command.side_effect = malformed
    mock_connection.return_value = connection

    for _ in malformed:
        result = json.loads(va_get_section(MagicMock(), section_id))
        assert result["success"] is False
        assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_read_preserves_partial_mutation_state_contract(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_get_section

    section_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    mock_connection.return_value = _connection({
        "status": "error",
        "code": "PARTIAL_MUTATION",
        "message": "typed read changed covered state",
        "covered_state_restored": True,
        "restoration_limit": "plugin-private state is unmeasured",
        "state_guard": {
            "covered_state_unchanged": False,
            "covered_rhino_state": {
                "cleanup": {"covered_state_restored": True},
            },
        },
    })

    result = json.loads(va_get_section(MagicMock(), section_id))

    assert result["success"] is False
    assert result["code"] == "PARTIAL_MUTATION"
    assert result["data"]["covered_state_restored"] is True
    assert "plugin-private" in result["data"]["restoration_limit"]


@patch(PATCH)
def test_create_rejects_malformed_success_evidence(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_create_section

    style_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    malformed = [
        {"status": "success"},
        {
            "status": "success",
            "section": {"id": "cccccccc-cccc-cccc-cccc-cccccccccccc"},
            "bake": {"success": False},
            "verification": {"pass": True},
        },
        {
            "status": "success",
            "section": {"id": "cccccccc-cccc-cccc-cccc-cccccccccccc"},
            "bake": {"success": True},
            "verification": {"pass": False},
        },
    ]
    connection = _connection({})
    connection.send_command.side_effect = malformed
    mock_connection.return_value = connection

    for _ in malformed:
        result = json.loads(va_create_section(
            MagicMock(), [0, 0, 0], [1, 0, 0], 10, "A", style_id))
        assert result["success"] is False
        assert result["code"] == "VERIFICATION_FAILED"


def test_grasshopper_bake_service_is_single_strategy_and_delta_owned():
    source = (PLUGIN_FUNCTIONS / "GrasshopperBakeService.cs").read_text()

    assert "BakeSingleNativeItem" in source
    assert "IGH_BakeAwareData" in source
    assert source.count("bakeAware.BakeGeometry(") == 1
    assert "GH_Convert" not in source
    assert "GH_BakeUtility" not in source
    assert "CaptureDocumentBaseline" in source
    assert "BeforeIds = new HashSet<Guid>(baseline.ObjectStates.Keys)" in source
    assert ".Except(evidence.BeforeIds)" in source
    assert "OwnershipProven" in source
    assert "CleanupOwnedAdditions" in source
    assert "missing_baseline_ids" in source
    assert "FinalizeCallEvidence" in source
    assert "RuntimeSerialNumber" in source
    assert "geometry?.DataCRC(0)" in source
    assert "layer.DataCRC(0)" in source
    assert "definition.DataCRC(0)" in source
    assert "definition.GetObjects()" in source
    assert "CleanupAddedDefinitions" in source
    assert "deleteReferences: false" in source
    assert "CurrentLayerReadable" in source
    assert "cleanup_evidence_failed" in source
    assert "VerifyReadOnlyCall" in source
    assert 'Strategy = "covered_read_only_state_guard"' in source
    assert '"verification_scope"] = "covered_state_only"' in source


def test_section_handler_freezes_runtime_component_and_readback_contracts():
    source = (
        PLUGIN_FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()

    expected_guids = {
        "07d3b1d2-b853-4a68-8f44-a6322df4a594",
        "0b2cf059-d26d-45a4-a9d1-9199484d2a98",
        "5e09e777-129b-4853-bd3d-db95fb16dd7c",
        "ccf0227c-0b79-4083-b90d-d3b88b9c7ba2",
        "c4963f2f-b88f-46c0-b10f-92e1038e4a51",
        "1d1eaded-3d33-46fb-a883-255aa91d7fb9",
    }
    assert expected_guids <= set(
        value.lower() for value in expected_guids if value in source.lower())
    assert "ValidatePorts" in source
    assert "EnsureVisualArqAssembly" in source
    assert 'name, "GhVa30", StringComparison.Ordinal' in source
    assert "isVersionPinnedGrasshopperBridge" in source
    assert 'FindVisualArqScriptMethod(\n                "IsSection"' in source
    assert 'FindUniqueRuntimeType("GhVaSection")' in source
    assert 'FindUniqueRuntimeType("GhVaSectionStyle")' in source
    assert "VisualArqReferenceHandle" in source
    assert "ReferenceName" in source
    assert "ReadSectionSnapshot" in source
    assert 'ApprovedVisualArqGhBridgeVersion = "3.7.2.20500"' in source
    assert "EnsureApprovedVisualArqBridgeVersion" in source
    assert "Script_ClearPersistentData" in source
    assert "Instances.DocumentServer" in source


def test_section_create_solves_once_bakes_once_and_cleans_owned_failure():
    source = (
        PLUGIN_FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()
    create = source.split(
        "public JObject CreateVisualArqSection", 1)[1].split(
            "private static JObject ReadSectionSnapshot", 1)[0]

    assert create.count("ghDoc.NewSolution(") == 1
    assert create.count("BakeSingleNativeItem(") == 1
    assert "outputItems.Count != 1" in create
    assert "outputItems[0].GetType() != expectedSectionGooType" in create
    assert "bake.AddedIds.Count != 1" in create
    assert create.count("CleanupOwnedAdditions(") >= 2
    assert "VerifyCreatedSection" in create
    assert create.index("CaptureDocumentBaseline(doc)") < create.index(
        "CreateValidatedVaParam(")
    assert create.index("CaptureVisualArqStyleInventory(styleId)") < (
        create.index("CreateValidatedVaParam("))
    assert create.index('phase: "immediately_before_section_first_solve"') < (
        create.index("ghDoc.NewSolution("))
    assert create.index("mutationPhaseStarted = true") < create.index(
        "ghDoc.NewSolution(")
    assert "GuardedPreSolveFailure(" in create
    assert "StyleInventoriesEqual(\n                        " in create
    assert create.index("ReadSectionSnapshot(doc, sectionId)") < create.index(
        'phase: "final_after_typed_readback"')
    assert create.index("doc.Views.Redraw()") < create.index(
        'MethodInfo isSectionMethod = FindVisualArqScriptMethod(')
    assert create.index("doc.Views.Redraw()") < create.index(
        "ReadSectionSnapshot(doc, sectionId)")
    assert '"IsSection", typeof(bool), typeof(Guid)' in create
    assert "VerifyAddedDefinitionOwnership" in create


def test_section_mutation_failures_never_claim_unmeasured_full_restoration():
    source = (
        PLUGIN_FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()

    assert "bool noObservedMutation = bake != null" in source
    assert "bake.ChangedBaselineIds.Count == 0" in source
    assert "bake.ChangedLayerIds.Count == 0" in source
    assert "bake.ChangedDefinitionIds.Count == 0" in source
    assert "bake.CurrentLayerUnchanged" in source
    assert "bool domainStateRestored" in source
    assert "bool coveredStateRestored" in source
    assert "bool rhinoStateRestored" in source
    assert (
        "bool coveredStateRestored = "
        "rhinoStateRestored && domainStateRestored"
    ) in source
    assert 'result["rhino_state_restored"] = rhinoStateRestored' in source
    assert 'result["domain_state_restored"] = domainStateRestored' in source
    assert 'data["code"] = "PARTIAL_MUTATION"' in source
    assert 'data["covered_state_restored"] = coveredStateRestored' in source
    assert "plugin-private" in source


def test_read_handlers_guard_transient_solves_and_validate_semantics():
    source = (
        PLUGIN_FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()
    reads = source.split("public JObject ListVisualArqSections", 1)[1].split(
        "public JObject CreateVisualArqSection", 1)[0]
    snapshot = source.split("private static JObject ReadSectionSnapshot", 1)[1]

    assert reads.count("CaptureDocumentBaseline(doc)") == 2
    assert reads.count("VerifyReadOnlyCall(") >= 4
    assert reads.count("CaptureVisualArqStyleInventory()") >= 4
    assert 'result["code"] = "PARTIAL_MUTATION"' in source
    assert 'FindUniqueRuntimeType("GhVaSectionStyle")' in source
    assert "path.IsValid" in snapshot
    assert "pathBounds.IsValid" in snapshot
    assert "RhinoMath.IsValidDouble(depth)" in snapshot
    assert "depth <= 0" in snapshot
    assert "string.IsNullOrWhiteSpace(reference)" in snapshot
    assert "string.IsNullOrWhiteSpace(styleName)" in snapshot


def test_section_readback_verifies_identity_and_transient_document_cleanup():
    source = (
        PLUGIN_FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()
    snapshot = source.split(
        "private static JObject ReadSectionSnapshot", 1
    )[1].split("private static JObject VerifyCreatedSection", 1)[0]
    identity = source.split(
        "private static JObject VerifyLoadedVisualArqDocumentationGoo", 1
    )[1].split("private static object CreateLoadedSectionGoo", 1)[0]
    section_loader = source.split(
        "private static object CreateLoadedSectionGoo", 1
    )[1].split("private static object CreateLoadedStyleGoo", 1)[0]

    assert "CreateValidatedSectionReadContract()" in snapshot
    assert "VerifyLoadedVisualArqDocumentationGoo(" in snapshot
    assert "!goo.IsValid" in identity
    assert 'ReadRequiredBooleanProperty(goo, "IsObjectLoaded")' in identity
    assert "referenceId.Value != requestedObjectId" in identity
    assert '["is_valid"] = true' in identity
    assert '["is_object_loaded"] = true' in identity
    assert '["reference_id"] = referenceId.Value.ToString()' in identity
    assert "TryCreateVerifiedLoadedVisualArqDocumentationGoo(" in section_loader
    assert '"GhVaSection"' in section_loader
    assert "using var ghDoc" not in snapshot
    assert "documentServer.Contains(ghDoc)" in snapshot
    assert '["transient_document_registered"] = true' in snapshot
    assert "CleanupGrasshopperBuildDocument(" in snapshot
    assert '["transient_document_cleanup"] = cleanup' in snapshot
    assert 'cleanup["complete"]?.Value<bool>() != true' in snapshot


def test_section_read_contract_is_solve_free_and_version_bound():
    source = (
        PLUGIN_FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()
    contract = source.split(
        "private static VaSectionReadContract "
        "CreateValidatedSectionReadContract", 1
    )[1].split("private static void ValidateSectionReadContract", 1)[0]
    validation = source.split(
        "private static void ValidateSectionReadContract", 1
    )[1].split("private static JObject ReadSectionSnapshot", 1)[0]

    assert "CreateValidatedVaParam(" in contract
    assert contract.count("CreateValidatedVaComponent(") == 2
    assert 'FindUniqueRuntimeType("GhVaSection")' in contract
    assert 'FindUniqueRuntimeType("GhVaSectionStyle")' in contract
    assert contract.count("EnsureApprovedVisualArqBridgeVersion(") == 5
    assert "NewSolution(" not in contract
    assert "CreateValidatedSectionReadContract()" in validation


def test_shared_style_guard_keeps_component_identity_when_names_are_unreadable():
    source = (
        PLUGIN_FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()
    reader = source.split(
        "private static JObject ReadStyleInventoryEntry", 1
    )[1].split("private static List<Guid> GuidSequence", 1)[0]

    assert '"GetStyleComponentName", typeof(string), typeof(Guid)' in source
    assert "getStyleComponentName.Invoke(" in reader
    assert "getStyleName.Invoke(" not in reader.split(
        "List<Guid> componentIds", 1
    )[1]
    assert '["name_readable"] = nameReadable' in reader
    assert '["name_source"] = "GetStyleComponentName"' in reader
    assert "JValue.CreateNull()" in reader
    assert "Style component" not in reader
    assert '["unnamed_component_ids"]' in source
    assert '["component_name_read_complete"]' in source


def test_shared_style_guard_includes_strict_guid_array_inventory_aliases():
    source = (
        PLUGIN_FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()
    discovery = source.split(
        "private static JObject CaptureVisualArqStyleInventory", 1
    )[1].split("private static JObject ReadStyleInventoryEntry", 1)[0]
    predicate = discovery.split(
        "private static bool IsVisualArqStyleInventoryMethod", 1
    )[1]

    assert ".Where(\n                    IsVisualArqStyleInventoryMethod)" in discovery
    assert "method.IsPublic" in predicate
    assert "method.IsStatic" in predicate
    assert "method.IsGenericMethod" in predicate
    assert "method.ContainsGenericParameters" in predicate
    assert "method.GetParameters().Length != 0" in predicate
    assert "method.ReturnType != typeof(Guid[])" in predicate
    assert 'method.Name.StartsWith("GetAll"' in predicate
    assert 'method.Name.EndsWith("StyleIds"' in predicate
    assert 'method.Name.EndsWith("Style"' in predicate
    assert "GetAllBeamStyle()" in predicate
    assert (
        "reflected_zero_arg_Guid_array_style_inventories_plus_tracked"
        in discovery
    )


def test_raw_tcp_validation_rejects_json_type_coercion():
    source = (
        PLUGIN_FUNCTIONS / "VisualArqDocumentationOperations.cs"
    ).read_text()

    assert "referenceToken?.Type != JTokenType.String" in source
    assert "value.Type != JTokenType.Integer" in source
    assert "value.Type != JTokenType.Float" in source
    assert "token.Type != JTokenType.Integer" in source
    assert "token.Type != JTokenType.Float" in source
    assert "token?.Type != JTokenType.String" in source


def test_section_commands_are_dispatched_advertised_and_reexported():
    server = (ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs").read_text()
    capabilities = (
        PLUGIN_FUNCTIONS / "ListCapabilities.cs"
    ).read_text()
    for command, handler in {
        "va_list_sections": "ListVisualArqSections",
        "va_get_section": "GetVisualArqSection",
        "va_create_section": "CreateVisualArqSection",
    }.items():
        assert f'["{command}"] = this.handler.{handler}' in server
        assert f'"{command}"' in capabilities

    import rhinoclaw

    assert callable(rhinoclaw.va_list_sections)
    assert callable(rhinoclaw.va_get_section)
    assert callable(rhinoclaw.va_create_section)


def test_documentation_reads_are_explicitly_undo_free():
    server = (ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs").read_text()
    undo_free = server.split(
        "private static readonly HashSet<string> UndoFreeCommands", 1
    )[1].split("};", 1)[0]

    for command in (
        "va_list_sections",
        "va_get_section",
        "va_list_section_views",
        "va_get_section_view",
        "va_list_plan_views",
        "va_get_plan_view",
    ):
        assert f'"{command}"' in undo_free
