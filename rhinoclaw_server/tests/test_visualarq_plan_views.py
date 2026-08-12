import json
from pathlib import Path
from unittest.mock import MagicMock, patch


PATCH = "rhinoclaw.tools.visualarq_documentation.get_rhino_connection"
ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "rhinoclaw_plugin"
FUNCTIONS = PLUGIN / "Functions"
SOURCE_PATH = FUNCTIONS / "VisualArqPlanViewOperations.cs"


def _connection(result):
    connection = MagicMock()
    connection.send_command.return_value = result
    return connection


def _read_guard(*, hierarchy=True):
    return {
        "covered_state_unchanged": True,
        "visualarq_style_state": {"unchanged": True},
        "visualarq_hierarchy_state": {"unchanged": hierarchy},
    }


@patch(PATCH)
def test_list_plan_views_requires_complete_style_and_hierarchy_guard(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_list_plan_views

    rhino = _connection({
        "status": "success",
        "count": 1,
        "plan_views": [{
            "id": "11111111-1111-1111-1111-111111111111",
            "identity_verified": True,
            "readback_complete": True,
            "level": {
                "id": None,
                "identity_status": "unresolved",
                "identity_verified": False,
            },
        }],
        "read_complete": True,
        "identity_complete": False,
        "level_identity_verified": False,
        "state_guard": _read_guard(),
    })
    mock_connection.return_value = rhino

    result = json.loads(va_list_plan_views(MagicMock()))

    assert result["success"] is True
    assert result["data"]["identity_complete"] is False
    assert result["data"]["plan_views"][0]["level"]["id"] is None
    rhino.send_command.assert_called_once_with("va_list_plan_views", {})


@patch(PATCH)
def test_list_plan_views_rejects_success_without_hierarchy_guard(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_list_plan_views

    mock_connection.return_value = _connection({
        "status": "success",
        "count": 0,
        "plan_views": [],
        "read_complete": True,
        "identity_complete": False,
        "level_identity_verified": False,
        "state_guard": _read_guard(hierarchy=False),
    })

    result = json.loads(va_list_plan_views(MagicMock()))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_get_plan_view_canonicalizes_exact_object_guid(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_get_plan_view

    rhino = _connection({
        "status": "success",
        "plan_view": {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "identity_verified": True,
            "readback_complete": True,
            "level": {
                "id": None,
                "identity_status": "unresolved",
                "identity_verified": False,
            },
        },
        "read_complete": True,
        "identity_complete": False,
        "level_identity_verified": False,
        "state_guard": _read_guard(),
    })
    mock_connection.return_value = rhino

    result = json.loads(va_get_plan_view(
        MagicMock(), "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"))

    assert result["success"] is True
    rhino.send_command.assert_called_once_with(
        "va_get_plan_view",
        {"plan_view_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
    )


@patch(PATCH)
def test_get_plan_view_rejects_bad_guid_before_roundtrip(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_get_plan_view

    result = json.loads(va_get_plan_view(MagicMock(), "not-a-guid"))

    assert result["success"] is False
    assert result["code"] == "INVALID_PARAMS"
    mock_connection.assert_not_called()


@patch(PATCH)
def test_create_plan_view_sends_strict_normalized_future_contract(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_create_plan_view

    level_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    style_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    rhino = _connection({
        "status": "error",
        "code": "UNSUPPORTED_OPERATION",
        "message": "exact Level bridge unavailable",
        "phase": "pre_solve_pre_bake",
        "mutation_phase_started": False,
        "graph_constructed": False,
        "solve_attempted": False,
        "bake_attempted": False,
        "level_identity_verified": False,
        "state_guard": _read_guard(),
    })
    mock_connection.return_value = rhino

    result = json.loads(va_create_plan_view(
        MagicMock(),
        level_id,
        style_id,
        [100, 200.5, 0],
        {"points": [[0, 0, 0], [1000, 0, 0], [1000, 500, 0]]},
        title="  Level 00  ",
        depth={"custom": 2500},
        scale=2,
        auto_update=True,
        show_boundary=True,
        plan_type="reflected_ceiling",
    ))

    assert result["success"] is False
    assert result["code"] == "UNSUPPORTED_OPERATION"
    assert result["data"]["phase"] == "pre_solve_pre_bake"
    rhino.send_command.assert_called_once_with(
        "va_create_plan_view",
        {
            "level_id": level_id,
            "style_id": style_id,
            "insertion_point": [100.0, 200.5, 0.0],
            "boundary": {
                "points": [
                    [0.0, 0.0, 0.0],
                    [1000.0, 0.0, 0.0],
                    [1000.0, 500.0, 0.0],
                ],
            },
            "title": "Level 00",
            "depth": {"custom": 2500.0},
            "scale": 2.0,
            "auto_update": True,
            "show_boundary": True,
            "plan_type": "reflected_ceiling",
        },
    )


@patch(PATCH)
def test_create_plan_view_rejects_unverified_no_projection_locally(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_create_plan_view

    result = json.loads(va_create_plan_view(
        MagicMock(),
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        [0, 0, 0],
        {"curve_id": "cccccccc-cccc-cccc-cccc-cccccccccccc"},
        depth="no_projection",
    ))

    assert result["success"] is False
    assert result["code"] == "UNSUPPORTED_OPERATION"
    assert result["data"]["roundtrip_attempted"] is False
    mock_connection.assert_not_called()


@patch(PATCH)
def test_plan_view_read_rejects_a_semantically_guessed_level_id(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_get_plan_view

    mock_connection.return_value = _connection({
        "status": "success",
        "plan_view": {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "identity_verified": True,
            "readback_complete": True,
            "level": {
                "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "identity_status": "semantic_match",
                "identity_verified": False,
            },
        },
        "read_complete": True,
        "identity_complete": False,
        "level_identity_verified": False,
        "state_guard": _read_guard(),
    })

    result = json.loads(va_get_plan_view(
        MagicMock(), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_plan_view_create_gate_rejects_a_false_success(mock_connection):
    from rhinoclaw.tools.visualarq_documentation import va_create_plan_view

    mock_connection.return_value = _connection({
        "status": "success",
        "plan_view": {
            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        },
    })

    result = json.loads(va_create_plan_view(
        MagicMock(),
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        [0, 0, 0],
        {"points": [[0, 0, 0], [1000, 0, 0], [1000, 500, 0]]},
    ))

    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_create_plan_view_rejects_invalid_or_coercible_values(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_documentation import va_create_plan_view

    level_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    style_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    curve_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    valid = {
        "level_id": level_id,
        "style_id": style_id,
        "insertion_point": [0, 0, 0],
        "boundary": {"curve_id": curve_id},
    }
    cases = [
        {**valid, "level_id": "bad"},
        {**valid, "style_id": "bad"},
        {**valid, "insertion_point": [0, 0]},
        {**valid, "insertion_point": [0, 0, float("inf")]},
        {**valid, "boundary": {"curve_id": curve_id, "points": []}},
        {**valid, "boundary": {"points": [[0, 0, 0], [1, 0, 0]]}},
        {**valid, "title": " "},
        {**valid, "depth": {"custom": 0}},
        {**valid, "depth": "unknown"},
        {**valid, "scale": True},
        {**valid, "auto_update": 1},
        {**valid, "show_boundary": "false"},
        {**valid, "plan_type": "ceiling"},
    ]

    for values in cases:
        result = json.loads(va_create_plan_view(MagicMock(), **values))
        assert result["success"] is False
        assert result["code"] == "INVALID_PARAMS"

    mock_connection.assert_not_called()


def test_installed_catalog_freezes_all_plan_view_component_contracts():
    catalog_path = (
        ROOT / "rhinoclaw_server" / "src" / "rhinoclaw" / "static" /
        "gh_components.json"
    )
    catalog = json.loads(catalog_path.read_text())
    by_guid = {item["guid"]: item for item in catalog["components"]}

    expected_params = {
        "d1a0be43-97e5-4f0b-87c9-d2e862770f6a":
            ("PlanView", "plan view"),
        "95991b42-f12f-417d-aa5a-a31bbeb54eba": ("Level", "Level"),
        "d01ae38c-5350-4bb3-b288-e91240fa37a6":
            ("Plan View Style", "Plan View Style"),
        "2058bbe8-8fa8-49e0-8d64-8cd1328e704f":
            ("PlanViewOpts", "Plan View Options"),
        "f2e78a75-e607-4ff6-b375-4842a2c8ee39": ("Plan Type", "Goo"),
    }
    for guid, (name, param_type) in expected_params.items():
        assert by_guid[guid]["name"] == name
        assert by_guid[guid]["param_type"] == param_type

    expected_components = {
        "80e8af5b-abcf-4140-8a7c-85ac93f5c159": (
            "Plan View Options",
            [
                ("Style", "Plan View Style"), ("Title", "Text"),
                ("Depth", "Number"), ("Scale", "Number"),
                ("Update", "Boolean"), ("Boundary", "Boolean"),
                ("Plan type", "Integer"),
            ],
            [("Options", "Plan View Options")],
        ),
        "1f8b7469-9fbd-4335-b68c-b900dfe8a64c": (
            "Plan View",
            [
                ("Point", "Point"), ("Curve", "Curve"),
                ("Level", "Level"), ("Options", "Plan View Options"),
            ],
            [("PlanView", "plan view")],
        ),
        "568a1929-fa07-4d80-943f-d50718eeaa3f": (
            "Deconstruct PlanView",
            [("PlanView", "plan view")],
            [
                ("Point", "Point"), ("Curve", "Curve"),
                ("Level", "Level"), ("Options", "Plan View Options"),
            ],
        ),
        "656bcfff-4f1a-4e46-87ec-3c0551dc720d": (
            "Deconstruct PlanView Options",
            [("Options", "Plan View Options")],
            [
                ("Style", "Plan View Style"), ("Title", "Text"),
                ("Depth", "Number"), ("Scale", "Number"),
                ("Update", "Boolean"), ("Boundary", "Boolean"),
                ("Plan type", "Integer"),
            ],
        ),
        "76328ca5-bd0f-4542-b3ba-ae361480df8b": (
            "Deconstruct Level",
            [("Level", "Level")],
            [
                ("Name", "Text"), ("Elevation", "Number"),
                ("Cut plane", "Number"), ("Top offset", "Number"),
                ("Bottom offset", "Number"), ("SubLevels", "Level"),
            ],
        ),
    }
    for guid, (name, inputs, outputs) in expected_components.items():
        item = by_guid[guid]
        assert item["name"] == name
        assert [(port["n"], port["t"]) for port in item["in"]] == inputs
        assert [(port["n"], port["t"]) for port in item["out"]] == outputs


def test_plan_view_handler_requires_exact_guid_identity_and_honest_level():
    source = SOURCE_PATH.read_text()
    expected_guids = {
        "d1a0be43-97e5-4f0b-87c9-d2e862770f6a",
        "95991b42-f12f-417d-aa5a-a31bbeb54eba",
        "d01ae38c-5350-4bb3-b288-e91240fa37a6",
        "2058bbe8-8fa8-49e0-8d64-8cd1328e704f",
        "f2e78a75-e607-4ff6-b375-4842a2c8ee39",
        "80e8af5b-abcf-4140-8a7c-85ac93f5c159",
        "1f8b7469-9fbd-4335-b68c-b900dfe8a64c",
        "568a1929-fa07-4d80-943f-d50718eeaa3f",
        "656bcfff-4f1a-4e46-87ec-3c0551dc720d",
        "76328ca5-bd0f-4542-b3ba-ae361480df8b",
    }
    assert all(guid in source.lower() for guid in expected_guids)
    assert 'FindUniqueRuntimeType("GhVaPlanView")' in source
    assert 'expectedType.Name != "GhVaPlanView"' in source
    assert "referenceId.Value != planViewId" in source
    assert "GhVaPlanView ReferenceID did not roundtrip" in source
    assert 'FindUniqueRuntimeType("GhVaLevel")' in source
    assert '["id"] = null' in source
    assert '["identity_status"] = "unresolved"' in source
    assert '["identity_verified"] = false' in source
    assert '["candidate_level_ids"] = new JArray()' in source
    assert "VisualArqReferenceHandle(level" not in source
    assert "mReferenceID" not in source
    assert "CastFrom" not in source


def test_plan_view_readback_solves_once_and_validates_geometry_and_options():
    source = SOURCE_PATH.read_text()
    snapshot = source.split(
        "private static JObject ReadPlanViewSnapshot", 1)[1].split(
            "private static JObject ValidatePlanViewBoundary", 1)[0]

    assert snapshot.count("ghDoc.NewSolution(") == 1
    assert "RuntimeIssues(" in snapshot
    assert 'issue["level"]?.ToString() == "warning"' in snapshot
    assert "boundary.IsClosed" not in snapshot
    assert "ValidatePlanViewBoundary(" in snapshot
    assert "TryGetPlane" in source
    assert "Intersection.CurveSelf(curve, tolerance)" in source
    assert "selfIntersections.Count > 0" in source
    assert '["self_intersection_count"] = 0' in source
    assert "AreaMassProperties.Compute" in source
    assert "double.IsPositiveInfinity(value)" in source
    assert '["raw_class"] = "positive_infinity"' in source
    assert '"reflected_ceiling"' in source
    assert "instanceObject.InstanceDefinition.GetObjects()" in snapshot
    assert '["non_empty"] = true' in snapshot
    assert "documentServer.Contains(ghDoc)" in snapshot
    assert "CleanupGrasshopperBuildDocument(" in snapshot
    assert '["transient_document_cleanup"] = cleanup' in snapshot
    assert 'cleanup["complete"]?.Value<bool>() != true' in snapshot


def test_plan_view_reads_guard_rhino_styles_and_complete_hierarchy():
    source = SOURCE_PATH.read_text()
    reads = source.split(
        "public JObject ListVisualArqPlanViews", 1)[1].split(
            "public JObject CreateVisualArqPlanView", 1)[0]

    assert reads.count("CaptureDocumentBaseline(doc)") == 2
    assert reads.count("CaptureVisualArqStyleInventory()") >= 4
    assert reads.count("CaptureVisualArqHierarchy()") >= 4
    assert "GetAllBuildingIds" in source
    assert 'FindOptionalVisualArqScriptMethodAnyReturn(\n                "GetAllLevelIds")' in source
    assert "GetBuildingLevelIds" in source
    assert "GetLevelCutElevation" in source
    assert "VisualArqHierarchiesEqual" in source
    hierarchy = source.split(
        "private static JObject CaptureVisualArqHierarchy", 1)[1].split(
            "private static bool VisualArqHierarchiesEqual", 1)[0]
    membership = hierarchy.split(
        "List<Guid> memberIds = GuidSequence(", 1)[1].split(
            "foreach (Guid levelId in memberIds)", 1)[0]
    assert ".OrderBy(" not in membership
    assert "global_buildings_levels_ordered_membership" in hierarchy
    assert '"building_reachable"' in hierarchy
    assert '["global_level_inventory_available"]' in hierarchy
    assert '["orphan_check_available"]' in hierarchy
    assert '["mutation_baseline_complete"]' in hierarchy
    assert "levelIds.Add(levelId)" in hierarchy
    assert 'before["inventory_scope"]' in source
    assert 'before["mutation_baseline_complete"]' in source
    assert '["visualarq_hierarchy_state"]' in source
    assert 'result["code"] = "PARTIAL_MUTATION"' in source


def test_plan_view_create_is_explicitly_pre_solve_pre_bake_unsupported():
    source = SOURCE_PATH.read_text()
    create = source.split(
        "public JObject CreateVisualArqPlanView", 1)[1].split(
            "private static void ValidatePlanViewReadContract", 1)[0]

    assert '"UNSUPPORTED_OPERATION"' in create
    assert '"pre_solve_pre_bake"' in create
    assert '["mutation_phase_started"] = false' in create
    assert '["graph_constructed"] = false' in create
    assert '["solve_attempted"] = false' in create
    assert '["bake_attempted"] = false' in create
    assert "ghDoc.NewSolution(" not in create
    assert "BakeSingleNativeItem(" not in create
    assert "CreateLoadedStyleGoo(" not in create
    assert "GhVaLevel" in create
    assert "CaptureDocumentBaseline(doc)" in create
    assert "CaptureVisualArqStyleInventory()" in create
    assert "CaptureVisualArqHierarchy()" in create
    assert "VerifyReadOnlyCall(" in create


def test_plan_view_commands_are_dispatched_advertised_and_reexported():
    server = (PLUGIN / "RhinoClawServer.cs").read_text()
    compact_server = " ".join(server.split())
    capabilities = (FUNCTIONS / "ListCapabilities.cs").read_text()
    for command, handler in {
        "va_list_plan_views": "ListVisualArqPlanViews",
        "va_get_plan_view": "GetVisualArqPlanView",
        "va_create_plan_view": "CreateVisualArqPlanView",
    }.items():
        assert f'["{command}"] = this.handler.{handler}' in compact_server
        assert f'"{command}"' in capabilities

    undo_free = server.split(
        "private static readonly HashSet<string> UndoFreeCommands", 1)[1].split(
            "private JObject ExecuteCommandInternal", 1)[0]
    assert '"va_list_plan_views"' in undo_free
    assert '"va_get_plan_view"' in undo_free
    assert '"va_create_plan_view"' in undo_free

    import rhinoclaw

    assert callable(rhinoclaw.va_list_plan_views)
    assert callable(rhinoclaw.va_get_plan_view)
    assert callable(rhinoclaw.va_create_plan_view)
