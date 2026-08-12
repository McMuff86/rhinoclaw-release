import json
from pathlib import Path
from unittest.mock import MagicMock, patch


PATCH = "rhinoclaw.tools.visualarq_documentation.get_rhino_connection"
ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_SOURCE = (
    ROOT
    / "rhinoclaw_plugin"
    / "Functions"
    / "VisualArqDocumentationCapabilityOperations.cs"
)


def _operation(mode="supported", blockers=None):
    return {
        "mode": mode,
        "requirements": ["active Rhino document"],
        "blockers": blockers or [],
    }


def _script_method(name):
    signature = f"{name}(...) -> verified"
    return {
        "available": True,
        "expected_signature": signature,
        "exact_match_count": 1,
        "exact_matches": [{"signature": signature}],
    }


def _capability_response():
    return {
        "status": "success",
        "schema_version": "1.0",
        "read_only": True,
        "approved_visualarq_version": "3.7.2.20500",
        "runtime_versions": {
            "approved": "3.7.2.20500",
            "script_version_verified": True,
            "gh_version_verified": True,
            "all_gh_contracts_verified": True,
            "version_pair_verified": True,
        },
        "script_contracts": {
            "assembly": [],
            "exact_methods": {
                name: _script_method(name)
                for name in (
                    "get_style_name",
                    "is_section",
                    "get_all_building_ids",
                    "get_building_level_ids",
                    "get_level_name",
                    "get_level_elevation",
                    "get_level_cut_elevation",
                    "is_level",
                )
            },
            "method_families": {},
        },
        "gh_contracts": {
            name: {"verified": True}
            for name in (
                "section_read",
                "section_create",
                "section_style_creator",
                "section_view_read",
                "section_view_create",
                "plan_view_read",
            )
        },
        "documentation_objects": {
            "sections": {
                "list": _operation(),
                "read": _operation(),
                "create": _operation("conditional"),
                "style_create": _operation(
                    "unsupported", ["public inventory unavailable"]),
            },
            "section_views": {
                "list": _operation(),
                "read": _operation(),
                "create": _operation("conditional"),
                "style_create": _operation(
                    "unsupported", ["no approved creator"]),
            },
            "plan_views": {
                "list": _operation(
                    "conditional", ["Level GUID unresolved"]),
                "read": _operation(
                    "conditional", ["Level GUID unresolved"]),
                "create": _operation(
                    "unsupported", ["Level identity bridge unavailable"]),
                "style_create": _operation(
                    "unsupported", ["no approved creator"]),
            },
        },
        "execution": {
            "document_mutation_attempted": False,
            "gh_document_constructed": False,
            "gh_solve_attempted": False,
            "gh_solve_count": 0,
            "bake_attempted": False,
            "bake_count": 0,
        },
        "state_guard": {
            "covered_state_unchanged": True,
            "visualarq_style_state": {"unchanged": True},
            "visualarq_hierarchy_state": {"unchanged": True},
        },
    }


@patch(PATCH)
def test_va_documentation_capabilities_wraps_complete_semantic_report(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    connection = MagicMock()
    connection.send_command.return_value = _capability_response()
    mock_connection.return_value = connection

    result = json.loads(va_documentation_capabilities(MagicMock()))

    assert result["success"] is True
    objects = result["data"]["documentation_objects"]
    assert objects["sections"]["create"]["mode"] == "conditional"
    assert objects["plan_views"]["create"]["mode"] == "unsupported"
    connection.send_command.assert_called_once_with(
        "va_documentation_capabilities", {})


@patch(PATCH)
def test_va_documentation_capabilities_rejects_malformed_success_schema(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    response = _capability_response()
    response["documentation_objects"]["sections"]["read"]["mode"] = "maybe"
    connection = MagicMock()
    connection.send_command.return_value = response
    mock_connection.return_value = connection

    result = json.loads(va_documentation_capabilities(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_va_documentation_capabilities_requires_hierarchy_state_guard(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    response = _capability_response()
    response["state_guard"]["visualarq_hierarchy_state"]["unchanged"] = False
    connection = MagicMock()
    connection.send_command.return_value = response
    mock_connection.return_value = connection

    result = json.loads(va_documentation_capabilities(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_va_documentation_capabilities_rejects_missing_root_contract(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    for missing in (
        "approved_visualarq_version",
        "runtime_versions",
        "script_contracts",
        "gh_contracts",
    ):
        response = _capability_response()
        response.pop(missing)
        connection = MagicMock()
        connection.send_command.return_value = response
        mock_connection.return_value = connection

        result = json.loads(va_documentation_capabilities(MagicMock()))

        assert result["success"] is False
        assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_va_documentation_capabilities_fails_closed_on_version_drift(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    response = _capability_response()
    response["runtime_versions"]["gh_version_verified"] = False
    response["runtime_versions"]["version_pair_verified"] = False
    connection = MagicMock()
    connection.send_command.return_value = response
    mock_connection.return_value = connection

    result = json.loads(va_documentation_capabilities(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_positive_modes_require_nonempty_exact_script_ground_truth(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    response = _capability_response()
    response["script_contracts"]["exact_methods"] = {}
    connection = MagicMock()
    connection.send_command.return_value = response
    mock_connection.return_value = connection

    result = json.loads(va_documentation_capabilities(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_positive_section_modes_reject_contradictory_gh_ground_truth(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    response = _capability_response()
    response["gh_contracts"]["section_read"]["verified"] = False
    response["runtime_versions"]["all_gh_contracts_verified"] = False
    connection = MagicMock()
    connection.send_command.return_value = response
    mock_connection.return_value = connection

    result = json.loads(va_documentation_capabilities(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_positive_section_modes_reject_unavailable_script_method(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    response = _capability_response()
    response["script_contracts"]["exact_methods"]["is_section"] = {
        "available": False,
        "expected_signature": "IsSection(System.Guid) -> System.Boolean",
        "exact_match_count": 0,
        "exact_matches": [],
    }
    connection = MagicMock()
    connection.send_command.return_value = response
    mock_connection.return_value = connection

    result = json.loads(va_documentation_capabilities(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_unapproved_positive_mode_is_rejected(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    response = _capability_response()
    response["documentation_objects"]["plan_views"]["create"] = _operation(
        "conditional")
    connection = MagicMock()
    connection.send_command.return_value = response
    mock_connection.return_value = connection

    result = json.loads(va_documentation_capabilities(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


def test_capability_handler_is_reflection_exact_and_side_effect_free():
    source = CAPABILITY_SOURCE.read_text()

    assert "public JObject VisualArqDocumentationCapabilities" in source
    assert '"GetStyleName",\n                    typeof(string)' in source
    assert '"IsSection",\n                    typeof(bool)' in source
    for method in (
        "GetAllSectionStyleIds",
        "GetAllSectionViewStyleIds",
        "GetAllPlanViewStyleIds",
        "GetAllLevelIds",
    ):
        assert f'"{method}"' in source
    for absent_family in (
        "AddSection",
        "AddSectionView",
        "AddPlanView",
        "IsSectionView",
        "IsPlanView",
        "AddSectionStyle",
        "AddSectionViewStyle",
        "AddPlanViewStyle",
    ):
        assert f'"{absent_family}"' in source

    assert "ValidateSectionReadContract" in source
    assert "ValidateSectionViewReadContract" in source
    assert "ValidatePlanViewReadContract" in source
    assert "CaptureVisualArqStyleInventory" in source
    assert "CaptureVisualArqHierarchy" in source
    assert "PlanViewReadOnlyStateGuard" in source
    assert "EnsureApprovedVisualArqBridgeVersion" in source
    assert "CreateValidatedVaComponent" in source
    assert "CreateValidatedVaParam" in source
    assert "NewSolution(" not in source
    assert "BakeGeometry(" not in source
    assert "BakeSingleNativeItem(" not in source


def test_solve_free_runtime_probes_dispose_every_proxy_instance():
    capability = CAPABILITY_SOURCE.read_text()
    documentation = (
        ROOT
        / "rhinoclaw_plugin"
        / "Functions"
        / "VisualArqDocumentationOperations.cs"
    ).read_text()
    section_views = (
        ROOT
        / "rhinoclaw_plugin"
        / "Functions"
        / "VisualArqSectionViewOperations.cs"
    ).read_text()
    plan_views = (
        ROOT
        / "rhinoclaw_plugin"
        / "Functions"
        / "VisualArqPlanViewOperations.cs"
    ).read_text()

    assert "VaSectionReadContract : IDisposable" in documentation
    assert "using VaSectionReadContract contract" in documentation
    assert "ValidateDisposableVisualArqGhObjects" in documentation
    strict_disposal = documentation.split(
        "private static void ValidateDisposableVisualArqGhObjects", 1
    )[1].split("private static void EnsureVisualArqAssembly", 1)[0]
    assert "DisposeVisualArqProbeObjectsOrThrow(" in strict_disposal
    assert "ExceptionDispatchInfo.Capture(disposalFailure).Throw()" in (
        strict_disposal
    )
    assert "for (int index = objects.Count - 1; index >= 0; index--)" in (
        strict_disposal
    )
    assert "disposable.Dispose()" in strict_disposal
    assert "failures.Add(new InvalidOperationException(" in strict_disposal
    assert "throw new AggregateException(" in strict_disposal

    probe_wrapper = capability.split(
        "private static JObject ProbeDocumentationGhContract", 1
    )[1].split(
        "private static void ValidateSectionCreateCapabilityContract", 1
    )[0]
    assert "probe();" in probe_wrapper
    assert '["verified"] = true' in probe_wrapper
    assert "catch (Exception error)" in probe_wrapper
    assert '["verified"] = false' in probe_wrapper

    component_factory = documentation.split(
        "private static IGH_Component CreateValidatedVaComponent", 1
    )[1].split("private static IGH_Param CreateValidatedVaParam", 1)[0]
    param_factory = documentation.split(
        "private static IGH_Param CreateValidatedVaParam", 1
    )[1].split("private static IGH_DocumentObject CreateVaProxyInstance", 1)[0]
    assert "catch" in component_factory
    assert "(instance as IDisposable)?.Dispose()" in component_factory
    assert "catch" in param_factory
    assert "(instance as IDisposable)?.Dispose()" in param_factory

    section_view_probe = section_views.split(
        "private static void ValidateSectionViewReadContract", 1
    )[1].split("private static bool TryCreateLoadedSectionViewGoo", 1)[0]
    assert "ValidateDisposableVisualArqGhObjects" in section_view_probe
    assert 'ValidateVisualArqRuntimeType(\n            "GhVaSectionView"' in (
        section_view_probe
    )
    assert 'ValidateVisualArqRuntimeType("GhVaSection"' in section_view_probe
    assert 'ValidateVisualArqRuntimeType("GhVaSectionViewStyle"' in (
        section_view_probe
    )

    plan_view_probe = plan_views.split(
        "private static void ValidatePlanViewReadContract", 1
    )[1].split("private static bool TryCreateLoadedPlanViewGoo", 1)[0]
    assert "ValidateDisposableVisualArqGhObjects" in plan_view_probe
    assert 'ValidateVisualArqRuntimeType("GhVaPlanView"' in plan_view_probe
    assert 'ValidateVisualArqRuntimeType("GhVaLevel"' in plan_view_probe
    assert 'ValidateVisualArqRuntimeType("GhVaPlanViewStyle"' in plan_view_probe

    assert capability.count("ValidateDisposableVisualArqGhObjects") == 3


def test_create_capability_probes_validate_real_style_goo_bridge():
    capability = CAPABILITY_SOURCE.read_text()
    documentation = (
        ROOT
        / "rhinoclaw_plugin"
        / "Functions"
        / "VisualArqDocumentationOperations.cs"
    ).read_text()

    section_create = capability.split(
        "private static void ValidateSectionCreateCapabilityContract", 1
    )[1].split(
        "private static void ValidateSectionStyleCreatorCapabilityContract", 1
    )[0]
    style_create = capability.split(
        "private static void ValidateSectionStyleCreatorCapabilityContract", 1
    )[1].split(
        "private static void ValidateSectionViewCreateCapabilityContract", 1
    )[0]
    section_view_create = capability.split(
        "private static void ValidateSectionViewCreateCapabilityContract", 1
    )[1].split(
        "private static JObject CaptureDocumentationRuntimeVersions", 1
    )[0]
    assert (
        'ValidateVisualArqStyleGooBridgeContract("GhVaSectionStyle")'
        in section_create
    )
    assert (
        'ValidateVisualArqStyleGooBridgeContract("GhVaSectionStyle")'
        in style_create
    )
    assert (
        'ValidateVisualArqStyleGooBridgeContract("GhVaSectionViewStyle")'
        in section_view_create
    )

    bridge_resolver = documentation.split(
        "ResolveVisualArqStyleGooBridgeContract(string runtimeTypeName)", 1
    )[1].split(
        "private static void ValidateVisualArqStyleGooBridgeContract", 1
    )[0]
    assert "type.GetConstructor(Type.EmptyTypes)" in bridge_resolver
    assert 'type.GetProperty(\n            "ReferenceHandle"' in bridge_resolver
    assert "!referenceHandle.CanRead" in bridge_resolver
    assert "!referenceHandle.CanWrite" in bridge_resolver
    assert "Convert.ChangeType(\n                0UL" in bridge_resolver
    assert "ResolveVisualArqLoadObjectMethod(type)" in bridge_resolver

    bridge_probe = documentation.split(
        "private static void ValidateVisualArqStyleGooBridgeContract", 1
    )[1].split("private static Type FindUniqueRuntimeType", 1)[0]
    assert "contract.Constructor.Invoke(null)" in bridge_probe
    assert "contract.ReferenceHandle.GetValue(goo)" in bridge_probe
    assert "contract.ReferenceHandle.SetValue(goo, defaultHandle)" in (
        bridge_probe
    )
    assert "DisposeVisualArqProbeObjectsOrThrow(" in bridge_probe
    assert "InvokeVisualArqLoadObject" not in bridge_probe
    assert "RhinoDoc.ActiveDoc" not in bridge_probe
    assert "GH_Document" not in bridge_probe
    assert "NewSolution(" not in bridge_probe
    assert "BakeGeometry(" not in bridge_probe

    load_object_resolver = documentation.split(
        "private static MethodInfo ResolveVisualArqLoadObjectMethod", 1
    )[1].split(
        "private static bool InvokeVisualArqLoadObject", 1
    )[0]
    assert 'method.Name == "LoadObject"' in load_object_resolver
    assert "method.GetParameters().Length == 1" in load_object_resolver
    assert "typeof(RhinoDoc)" in load_object_resolver

    execution_bridge = documentation.split(
        "private static object CreateLoadedStyleGoo", 1
    )[1].split(
        "ResolveVisualArqStyleGooBridgeContract(string runtimeTypeName)", 1
    )[0]
    assert "ResolveVisualArqStyleGooBridgeContract(runtimeTypeName)" in (
        execution_bridge
    )
    assert "contract.Constructor.Invoke(null)" in execution_bridge
    assert "contract.ReferenceHandle.SetValue" in execution_bridge
    assert "InvokeVisualArqLoadObject(contract.LoadObject" in execution_bridge


def test_plan_view_read_capability_excludes_create_only_proxies():
    capability = CAPABILITY_SOURCE.read_text()
    plan_views = (
        ROOT
        / "rhinoclaw_plugin"
        / "Functions"
        / "VisualArqPlanViewOperations.cs"
    ).read_text()
    read_probe = plan_views.split(
        "private static void ValidatePlanViewReadContract", 1
    )[1].split("private static bool TryCreateLoadedPlanViewGoo", 1)[0]

    assert (
        '["plan_view_read"] = ProbeDocumentationGhContract(\n'
        '                "plan_view_read", ValidatePlanViewReadContract)'
    ) in capability
    assert "ValidatePlanViewRuntimeContract" not in capability
    assert "VaPlanViewParamGuid" in read_probe
    assert "VaDeconstructPlanViewGuid" in read_probe
    assert "VaDeconstructPlanViewOptionsGuid" in read_probe
    assert "VaDeconstructLevelGuid" in read_probe
    for create_only_proxy in (
        "VaLevelParamGuid",
        "VaPlanViewStyleParamGuid",
        "VaPlanViewOptionsParamGuid",
        "VaPlanTypeParamGuid",
        "VaPlanViewOptionsGuid",
        "VaPlanViewGuid",
    ):
        assert create_only_proxy not in read_probe
    assert read_probe.count("CreateValidatedVaParam(") == 1
    assert read_probe.count("CreateValidatedVaComponent(") == 3


@patch(PATCH)
def test_plan_view_read_contract_failure_stays_scoped(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import (
        va_documentation_capabilities,
    )

    response = _capability_response()
    response["gh_contracts"]["plan_view_read"]["verified"] = False
    response["runtime_versions"]["all_gh_contracts_verified"] = False
    response["documentation_objects"]["plan_views"]["list"] = _operation(
        "unsupported", ["Plan View read proxies unavailable"])
    response["documentation_objects"]["plan_views"]["read"] = _operation(
        "unsupported", ["Plan View read proxies unavailable"])
    connection = MagicMock()
    connection.send_command.return_value = response
    mock_connection.return_value = connection

    result = json.loads(va_documentation_capabilities(MagicMock()))

    assert result["success"] is True
    objects = result["data"]["documentation_objects"]
    assert objects["plan_views"]["read"]["mode"] == "unsupported"
    assert objects["sections"]["read"]["mode"] == "supported"
    assert objects["section_views"]["read"]["mode"] == "supported"


def test_capability_modes_cover_all_documentation_object_operations():
    source = CAPABILITY_SOURCE.read_text()

    for object_kind in ("sections", "section_views", "plan_views"):
        assert f'["{object_kind}"] = new JObject' in source
    assert source.count('["list"] = OperationCapability(') == 3
    assert source.count('["read"] = OperationCapability(') == 3
    assert source.count('["create"] = OperationCapability(') == 3
    assert source.count('["style_create"] = OperationCapability(') == 3
    assert 'planRead ? "conditional" : "unsupported"' in source
    assert "exact Level " in source
    assert "GUID identity is unresolved" in source
    assert "Transient inline Section Style bootstrap is" in source


def test_capability_command_is_dispatched_advertised_undo_free_and_exported():
    server = (ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs").read_text()
    capabilities = (
        ROOT / "rhinoclaw_plugin" / "Functions" / "ListCapabilities.cs"
    ).read_text()

    assert (
        '["va_documentation_capabilities"] =\n'
        "                    this.handler.VisualArqDocumentationCapabilities"
    ) in server
    assert '"va_documentation_capabilities"' in capabilities
    assert '"va_documentation_capabilities"' in server.split(
        "public List<string> GetAvailableTools", 1)[1]
    undo_free = server.split(
        "private static readonly HashSet<string> UndoFreeCommands", 1
    )[1].split("};", 1)[0]
    assert '"va_documentation_capabilities"' in undo_free

    import rhinoclaw

    assert callable(rhinoclaw.va_documentation_capabilities)
