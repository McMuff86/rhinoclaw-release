import json
import math
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch


PATCH = "rhinoclaw.tools.visualarq_roofs.get_rhino_connection"
ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "rhinoclaw_plugin"
SERVICE = PLUGIN / "Functions" / "VisualArqRoofService.cs"
OPERATIONS = PLUGIN / "Functions" / "VisualArqRoofOperations.cs"
DISPATCHER = PLUGIN / "RhinoClawServer.cs"


def _connection(result):
    rhino = MagicMock()
    rhino.send_command.return_value = result
    return rhino


def _state_guard(*, styles=True):
    guard = {"covered_state_unchanged": True}
    if styles:
        guard["visualarq_roof_style_state"] = {
            "covered": True,
            "unchanged": True,
        }
    return guard


def _roof(*, roof_type="gable", slopes=None):
    if slopes is None:
        slopes = [0.43833655985543474, 0.43833655985543474]
    slopes_applicable = roof_type != "composite"
    native_bbox = {"min": [0, 0, 2900], "max": [9000, 7000, 5100]}
    return {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "identity_verified": True,
        "readback_complete": True,
        "is_roof": True,
        "is_product": True,
        "style_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "style_name": "Roof Style",
        "roof_type": roof_type,
        "contour_bbox": {"min": [0, 0, 3000], "max": [9000, 7000, 3000]},
        "native_bbox": native_bbox,
        "top_level_native_bbox": native_bbox,
        "native_bbox_source": "top_level_geometry",
        "native_bbox_status": {
            "status": "resolved",
            "resolved": True,
            "source": "top_level_geometry",
            "bbox": native_bbox,
            "top_level_bbox_valid": True,
            "fallback_attempted": False,
            "fallback_eligible": False,
            "fallback_complete": False,
            "ownership_verified": False,
            "transform_chain_verified": False,
            "cycle_detected": False,
            "failure_code": None,
            "definition_visit_count": 0,
            "member_count": 0,
            "leaf_geometry_count": 0,
        },
        "slopes_radians": slopes,
        "slopes_applicable": slopes_applicable,
        "axis": {"status": "unresolved", "reason": "not approved"},
    }


def _capabilities(*, mode="external_interactive_required", fallback_steps=None):
    direct = mode == "direct_api"
    if fallback_steps is None:
        fallback_steps = [
            "prime", "cancel", "select", "insert", "axis",
            "read", "set", "move", "verify", "reload",
        ]
    return {
        "status": "success",
        "schema_version": "1.0",
        "read_only": True,
        "available": True,
        "runtime": {
            "loaded": True,
            "product_version": "3.8.0.21000" if direct else "3.7.2.20500",
            "direct_version_approved": direct,
            "direct_create_contract_complete": direct,
        },
        "method_contracts": {"AddRoofFromCurve": {"available": direct}},
        "authoring": {
            "mode": mode,
            "direct_curve_api_supported": direct,
            "direct_supported_roof_types": ["hip"] if direct else [],
            "axis_dependent_roof_types": ["shed", "gable"],
            "axis_control_authoritatively_bound": False,
            "legacy_fallback": {
                "executed_by_this_tool": False,
                "required_steps": fallback_steps,
            },
        },
        "execution": {
            "document_mutation_attempted": False,
            "native_command_attempted": False,
            "ui_automation_attempted": False,
        },
        "state_guard": _state_guard(styles=False),
    }


@patch(PATCH)
def test_roof_capabilities_accepts_guarded_372_external_mode(mock_connection):
    from rhinoclaw.tools.visualarq_roofs import va_roof_capabilities

    result = {
        "status": "success",
        "schema_version": "1.0",
        "read_only": True,
        "available": True,
        "runtime": {
            "loaded": True,
            "product_version": "3.7.2.20500",
            "direct_version_approved": False,
            "direct_create_contract_complete": False,
        },
        "method_contracts": {
            "AddRoofFromCurve": {
                "available": False,
                "exact_match_count": 0,
                "reflected_signatures": [
                    {
                        "signature": (
                            "System.Guid VisualARQ.Script.AddRoofFromCurve("
                            "System.Guid,Rhino.Geometry.Curve)"
                        ),
                    },
                ],
            },
        },
        "authoring": {
            "mode": "external_interactive_required",
            "direct_curve_api_supported": False,
            "direct_supported_roof_types": [],
            "axis_dependent_roof_types": ["shed", "gable"],
            "axis_control_authoritatively_bound": False,
            "legacy_fallback": {
                "executed_by_this_tool": False,
                "required_steps": ["prime", "insert", "move", "read", "reload"],
            },
        },
        "execution": {
            "document_mutation_attempted": False,
            "native_command_attempted": False,
            "ui_automation_attempted": False,
        },
        "state_guard": _state_guard(styles=False),
    }
    rhino = _connection(result)
    mock_connection.return_value = rhino

    response = json.loads(va_roof_capabilities(MagicMock()))

    assert response["success"] is True
    assert response["data"]["authoring"]["mode"] == (
        "external_interactive_required"
    )
    assert response["data"]["method_contracts"]["AddRoofFromCurve"][
        "reflected_signatures"
    ][0]["signature"].endswith("System.Guid,Rhino.Geometry.Curve)")
    rhino.send_command.assert_called_once_with("va_roof_capabilities", {})


@patch(PATCH)
def test_create_roof_372_preserves_pre_mutation_fallback(mock_connection):
    from rhinoclaw.tools.visualarq_roofs import va_create_roof_from_curve

    fallback_steps = [
        "prime panel",
        "cancel prime",
        "select owned curve",
        "run FromCurves",
        "supply relative axis",
        "accept one IsRoof",
        "set slopes and height",
        "native Move",
        "fresh read",
        "Save-New-Open",
    ]
    rhino = _connection(_capabilities(fallback_steps=fallback_steps))
    mock_connection.return_value = rhino

    response = json.loads(va_create_roof_from_curve(
        MagicMock(),
        "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB",
        "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC",
        "gable",
        slope_radians=0.4,
        gable_height=1800,
    ))

    assert response["success"] is False
    assert response["code"] == "UNSUPPORTED_OPERATION"
    assert response["data"]["mutation_phase_started"] is False
    assert response["data"]["fallback_steps"] == fallback_steps
    assert response["data"]["create_command_sent"] is False
    rhino.send_command.assert_called_once_with("va_roof_capabilities", {})


@patch(PATCH)
def test_create_roof_rejects_bad_input_without_roundtrip(mock_connection):
    from rhinoclaw.tools.visualarq_roofs import va_create_roof_from_curve

    valid_style = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    valid_curve = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    cases = [
        ("bad", valid_curve, "gable", None, None),
        (valid_style, "bad", "gable", None, None),
        (valid_style, valid_curve, "composite", None, None),
        (valid_style, valid_curve, "gable", 0, None),
        (valid_style, valid_curve, "gable", math.pi / 2, None),
        (valid_style, valid_curve, "gable", float("nan"), None),
        (valid_style, valid_curve, "gable", True, None),
        (valid_style, valid_curve, "hip", None, 1000),
        (valid_style, valid_curve, "gable", None, -1),
    ]
    for style, curve, roof_type, slope, height in cases:
        response = json.loads(va_create_roof_from_curve(
            MagicMock(), style, curve, roof_type,
            slope_radians=slope, gable_height=height,
        ))
        assert response["success"] is False
        assert response["code"] == "INVALID_PARAMS"
    mock_connection.assert_not_called()


@patch(PATCH)
def test_create_roof_accepts_only_complete_direct_api_evidence(mock_connection):
    from rhinoclaw.tools.visualarq_roofs import va_create_roof_from_curve

    roof = _roof(roof_type="hip")
    direct_result = {
        "status": "success",
        "schema_version": "1.0",
        "authoring_route": "direct_api_visualarq_3_8_plus",
        "roof": roof,
        "setter_reports": {
            "slope_slots": [
                {"index": 0, "returned": False},
                {"index": 1, "returned": False},
            ],
            "gable_height": {"returned": False},
            "acceptance_source": "post_setter_exact_readback",
        },
        "verification": {
            "pass": True,
            "axis_control_applicable": False,
            "axis_control_verified": False,
            "contour_topology": {
                "pass": True,
                "valid": True,
                "manifold": True,
                "face_count": 1,
                "outer_loop_count": 1,
                "inner_loop_count": 0,
            },
            "boundary_match": {
                "pass": True,
                "same_bbox_alone_is_accepted": False,
                "perimeter_matches": True,
                "area_matches": True,
                "sampling_matches": True,
                "max_bidirectional_deviation": 0.001,
            },
        },
        "mutation_evidence": {
            "success": True,
            "ownership_proven": True,
        },
        "persistence": {
            "live_document_verified": True,
            "save_reopen_required": True,
            "save_reopen_verified": False,
        },
    }
    rhino = _connection(None)
    rhino.send_command.side_effect = [
        _capabilities(mode="direct_api"),
        direct_result,
    ]
    mock_connection.return_value = rhino

    response = json.loads(va_create_roof_from_curve(
        MagicMock(),
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "hip",
    ))

    assert response["success"] is True
    assert response["data"]["setter_reports"]["slope_slots"][0][
        "returned"
    ] is False
    assert response["data"]["persistence"]["save_reopen_verified"] is False
    assert rhino.send_command.call_args_list[0].args == (
        "va_roof_capabilities", {},
    )
    assert rhino.send_command.call_args_list[1].args[0] == (
        "va_create_roof_from_curve"
    )

    # A same-BBox nominal Roof is not enough: removing the real topology/form
    # evidence must turn the identical C# success claim into wrapper failure.
    bbox_only_result = deepcopy(direct_result)
    bbox_only_result["verification"].pop("contour_topology")
    bbox_only_result["verification"].pop("boundary_match")
    rhino.send_command.reset_mock()
    rhino.send_command.side_effect = [
        _capabilities(mode="direct_api"),
        bbox_only_result,
    ]

    rejected = json.loads(va_create_roof_from_curve(
        MagicMock(),
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "hip",
    ))

    assert rejected["success"] is False
    assert rejected["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_create_roof_direct_rejects_axis_dependent_types_without_create_send(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_roofs import va_create_roof_from_curve

    rhino = _connection(_capabilities(mode="direct_api"))
    mock_connection.return_value = rhino

    response = json.loads(va_create_roof_from_curve(
        MagicMock(),
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "gable",
    ))

    assert response["success"] is False
    assert response["code"] == "UNSUPPORTED_OPERATION"
    assert response["data"]["blocker"] == "axis_control_unavailable"
    assert response["data"]["create_command_sent"] is False
    assert response["data"]["direct_supported_roof_types"] == ["hip"]
    rhino.send_command.assert_called_once_with("va_roof_capabilities", {})


@patch(PATCH)
def test_get_roof_canonicalizes_guid_and_accepts_composite_without_slopes(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_roofs import va_get_roof

    composite = _roof(roof_type="composite", slopes=[])
    rhino = _connection({
        "status": "success",
        "roof": composite,
        "read_complete": True,
        "state_guard": _state_guard(),
    })
    mock_connection.return_value = rhino

    response = json.loads(va_get_roof(
        MagicMock(), "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"))

    assert response["success"] is True
    assert response["data"]["roof"]["roof_type"] == "composite"
    assert response["data"]["roof"]["slopes_applicable"] is False
    assert response["data"]["roof"]["slopes_radians"] == []
    rhino.send_command.assert_called_once_with(
        "va_get_roof",
        {"roof_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
    )


@patch(PATCH)
def test_get_roof_accepts_persisted_nested_definition_bbox_fallback(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_roofs import va_get_roof

    composite = _roof(roof_type="composite", slopes=[])
    persisted_bbox = {
        "min": [100, 5600, 3510],
        "max": [19500, 10900, 3660],
    }
    composite.update({
        "native_bbox": persisted_bbox,
        "top_level_native_bbox": None,
        "native_bbox_source": "instance_definition_geometry_traversal",
        "native_bbox_status": {
            "status": "resolved",
            "resolved": True,
            "source": "instance_definition_geometry_traversal",
            "bbox": persisted_bbox,
            "top_level_bbox_valid": False,
            "fallback_attempted": True,
            "fallback_eligible": True,
            "fallback_complete": True,
            "ownership_verified": True,
            "transform_chain_verified": True,
            "cycle_detected": False,
            "failure_code": None,
            "failure": None,
            "root_instance_definition_id": (
                "cccccccc-cccc-cccc-cccc-cccccccccccc"
            ),
            "definition_visit_count": 2,
            "unique_definition_count": 2,
            "definition_ids": [
                "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "dddddddd-dddd-dddd-dddd-dddddddddddd",
            ],
            "member_count": 2,
            "leaf_geometry_count": 1,
            "max_depth_observed": 1,
            "max_depth_limit": 32,
            "max_member_limit": 10000,
        },
    })
    mock_connection.return_value = _connection({
        "status": "success",
        "roof": composite,
        "read_complete": True,
        "state_guard": _state_guard(),
    })

    response = json.loads(va_get_roof(
        MagicMock(), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

    assert response["success"] is True
    roof = response["data"]["roof"]
    assert roof["native_bbox"] == persisted_bbox
    assert roof["top_level_native_bbox"] is None
    assert roof["native_bbox_source"] == (
        "instance_definition_geometry_traversal"
    )
    assert roof["native_bbox_status"]["definition_visit_count"] == 2


@patch(PATCH)
def test_get_roof_rejects_incomplete_or_unsafe_definition_bbox_fallback(
    mock_connection,
):
    from rhinoclaw.tools.visualarq_roofs import va_get_roof

    base = _roof(roof_type="composite", slopes=[])
    persisted_bbox = {
        "min": [100, 5600, 3510],
        "max": [19500, 10900, 3660],
    }
    fallback_status = {
        "status": "resolved",
        "resolved": True,
        "source": "instance_definition_geometry_traversal",
        "bbox": persisted_bbox,
        "top_level_bbox_valid": False,
        "fallback_attempted": True,
        "fallback_eligible": True,
        "fallback_complete": True,
        "ownership_verified": True,
        "transform_chain_verified": True,
        "cycle_detected": False,
        "failure_code": None,
        "failure": None,
        "root_instance_definition_id": (
            "cccccccc-cccc-cccc-cccc-cccccccccccc"
        ),
        "definition_visit_count": 2,
        "unique_definition_count": 2,
        "definition_ids": [
            "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "dddddddd-dddd-dddd-dddd-dddddddddddd",
        ],
        "member_count": 2,
        "leaf_geometry_count": 1,
        "max_depth_observed": 1,
        "max_depth_limit": 32,
        "max_member_limit": 10000,
    }
    unsafe_cases = (
        {"ownership_verified": False},
        {"transform_chain_verified": False},
        {"cycle_detected": True},
        {"fallback_complete": False},
        {"failure_code": "instance_definition_membership_mismatch"},
        {"leaf_geometry_count": 0},
        {"definition_ids": []},
        {"unique_definition_count": 1},
        {"max_depth_observed": 33},
        {"member_count": 10001},
    )
    for unsafe in unsafe_cases:
        roof = deepcopy(base)
        status = {**fallback_status, **unsafe}
        roof.update({
            "native_bbox": persisted_bbox,
            "top_level_native_bbox": None,
            "native_bbox_source": "instance_definition_geometry_traversal",
            "native_bbox_status": status,
        })
        mock_connection.return_value = _connection({
            "status": "success",
            "roof": roof,
            "read_complete": True,
            "state_guard": _state_guard(),
        })

        response = json.loads(va_get_roof(
            MagicMock(), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

        assert response["success"] is False
        assert response["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_get_roof_rejects_malformed_or_unowned_native_bbox(mock_connection):
    from rhinoclaw.tools.visualarq_roofs import va_get_roof

    malformed_boxes = (
        {},
        {"min": [0, 0, 0], "max": [1, 1]},
        {"min": [0, 0, 0], "max": [1, "bad", 1]},
        {"min": [0, 0, 0], "max": [1, math.nan, 1]},
        {"min": [2, 0, 0], "max": [1, 1, 1]},
        {"min": [False, 0, 0], "max": [1, 1, 1]},
        {"min": [1, 1, 1], "max": [1, 1, 1]},
    )
    for malformed_bbox in malformed_boxes:
        roof = _roof()
        roof["native_bbox"] = malformed_bbox
        roof["top_level_native_bbox"] = malformed_bbox
        roof["native_bbox_status"]["bbox"] = malformed_bbox
        mock_connection.return_value = _connection({
            "status": "success",
            "roof": roof,
            "read_complete": True,
            "state_guard": _state_guard(),
        })

        response = json.loads(va_get_roof(
            MagicMock(), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

        assert response["success"] is False
        assert response["code"] == "VERIFICATION_FAILED"

    fallback = _roof(roof_type="composite", slopes=[])
    fallback_bbox = {
        "min": [100, 5600, 3510],
        "max": [19500, 10900, 3660],
    }
    fallback.update({
        "native_bbox": fallback_bbox,
        "top_level_native_bbox": None,
        "native_bbox_source": "instance_definition_geometry_traversal",
        "native_bbox_status": {
            "status": "resolved",
            "resolved": True,
            "source": "instance_definition_geometry_traversal",
            "bbox": fallback_bbox,
            "top_level_bbox_valid": False,
            "fallback_attempted": True,
            "fallback_eligible": True,
            "fallback_complete": True,
            "ownership_verified": True,
            "transform_chain_verified": True,
            "cycle_detected": False,
            "failure_code": None,
            "failure": None,
            "root_instance_definition_id": None,
            "definition_visit_count": 1,
            "unique_definition_count": 1,
            "definition_ids": [
                "cccccccc-cccc-cccc-cccc-cccccccccccc",
            ],
            "member_count": 1,
            "leaf_geometry_count": 1,
            "max_depth_observed": 0,
            "max_depth_limit": 32,
            "max_member_limit": 10000,
        },
    })
    mock_connection.return_value = _connection({
        "status": "success",
        "roof": fallback,
        "read_complete": True,
        "state_guard": _state_guard(),
    })

    response = json.loads(va_get_roof(
        MagicMock(), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

    assert response["success"] is False
    assert response["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_get_roof_rejects_malformed_contour_bbox(mock_connection):
    from rhinoclaw.tools.visualarq_roofs import va_get_roof

    roof = _roof()
    roof["contour_bbox"] = {"min": [0, 0, 3000], "max": [0, 0, 3000]}
    mock_connection.return_value = _connection({
        "status": "success",
        "roof": roof,
        "read_complete": True,
        "state_guard": _state_guard(),
    })

    response = json.loads(va_get_roof(
        MagicMock(), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

    assert response["success"] is False
    assert response["code"] == "VERIFICATION_FAILED"


@patch(PATCH)
def test_list_roofs_accepts_mixed_gable_and_composite_inventory(mock_connection):
    from rhinoclaw.tools.visualarq_roofs import va_list_roofs

    roofs = [_roof(), _roof(roof_type="composite", slopes=[])]
    roofs[1]["id"] = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    mock_connection.return_value = _connection({
        "status": "success",
        "count": 2,
        "roofs": roofs,
        "read_complete": True,
        "state_guard": _state_guard(),
    })

    response = json.loads(va_list_roofs(MagicMock()))

    assert response["success"] is True
    assert [item["roof_type"] for item in response["data"]["roofs"]] == [
        "gable", "composite",
    ]


@patch(PATCH)
def test_list_roof_styles_requires_linkage_thickness_and_guard(mock_connection):
    from rhinoclaw.tools.visualarq_roofs import va_list_roof_styles

    style = {
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "name": "Roof Style",
        "slope_style_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "slope_style_name": "Roof Slab",
        "thickness": 120.0,
        "readback_complete": True,
    }
    mock_connection.return_value = _connection({
        "status": "success",
        "count": 1,
        "styles": [style],
        "read_complete": True,
        "state_guard": _state_guard(),
    })

    response = json.loads(va_list_roof_styles(MagicMock()))

    assert response["success"] is True
    assert response["data"]["styles"][0]["thickness"] == 120.0


def test_roof_tools_are_reexported():
    import rhinoclaw

    for name in (
        "va_roof_capabilities",
        "va_list_roof_styles",
        "va_list_roofs",
        "va_get_roof",
        "va_create_roof_from_curve",
    ):
        assert callable(getattr(rhinoclaw, name))


def test_csharp_roof_service_is_version_and_shape_gated_before_mutation():
    source = SERVICE.read_text(encoding="utf-8")

    assert 'DirectApiMinimumVersion = "3.8.0"' in source
    assert "contract.ParsedProductVersion.Major == 3" in source
    assert "parameters.Length == 3" in source
    assert "parameters[0].ParameterType == typeof(Guid)" in source
    assert "parameters[1].ParameterType == typeof(Curve)" in source
    assert '"RoofType"' in source
    assert (
        'contract, "GetRoofSlopes", typeof(double[]), typeof(Guid)'
    ) in source
    assert (
        "contract.AddRoofFromCurve.GetParameters()[2].ParameterType ==\n"
        "                contract.RoofType"
    ) in source
    gate = source.index("if (!contract.DirectVersionApproved ||")
    mutation = source.index("contract.AddRoofFromCurve.Invoke(")
    assert gate < mutation
    assert '"mutation_phase_started"] = false' in source[gate:mutation]
    assert '"fallback_steps"]' in source[gate:mutation]


def test_csharp_roof_service_has_truthful_readback_and_no_unsafe_fallback():
    source = SERVICE.read_text(encoding="utf-8")

    for method in (
        "GetAllRoofStyleIds",
        "GetRoofContour",
        "GetRoofSlopes",
        "GetRoofType",
        "GetProductStyle",
        "GetRoofGableHeight",
        "IsRoof",
        "IsProduct",
    ):
        assert method in source
    assert '"not_applicable_to_direct_hip"' in source
    assert '"not_exposed"' in source
    assert '"status"] = "unresolved"' in source
    assert "RhinoApp.RunScript" not in source
    assert "SetRoofContour(" not in source
    assert "Objects.Transform(" not in source


def test_csharp_direct_create_requires_real_contour_topology_and_shape_match():
    source = SERVICE.read_text(encoding="utf-8")

    for evidence in (
        "CompareBoundaryToRoofContour",
        "contour.IsValid",
        "contour.IsManifold",
        "contour.Faces.Count == 1",
        "BrepLoopType.Outer",
        "BrepLoopType.Inner",
        "Intersection.CurveSelf",
        "AreaMassProperties.Compute",
        "PointAtNormalizedLength",
        "ClosestPoint",
        'const int sampleSegments = 256',
        '["input_to_contour"]',
        '["contour_to_input"]',
        '["same_bbox_alone_is_accepted"] = false',
    ):
        assert evidence in source
    assert "BoundingBoxesNear(" not in source
    verify = source[source.index("private static JObject VerifyCreatedRoof") :]
    assert 'contourTopology?["pass"]?.Value<bool>() == true' in verify
    assert 'boundaryMatch?["pass"]?.Value<bool>() == true' in verify


def test_csharp_direct_create_is_hip_only_until_axis_is_authoritative():
    source = SERVICE.read_text(encoding="utf-8")

    axis_gate = source.index('if (roofType != "hip")')
    mutation = source.index("contract.AddRoofFromCurve.Invoke(")
    assert axis_gate < mutation
    assert '"pre_mutation_axis_capability_gate"' in source[axis_gate:mutation]
    assert '"axis_control_unavailable"' in source[axis_gate:mutation]
    assert '["direct_supported_roof_types"] = new JArray("hip")' in source
    assert '["axis_control_authoritatively_bound"] = false' in source


def test_csharp_composite_readback_allows_empty_slope_array():
    source = SERVICE.read_text(encoding="utf-8")

    assert 'roofType == "shed" || roofType == "gable" ||' in source
    assert 'roofType == "hip"' in source
    assert '"slopes_applicable"] = slopesApplicable' in source
    assert "(!slopesApplicable || slopes.Count > 0)" in source


def test_csharp_persisted_roof_bbox_traverses_nested_definitions_in_world_space():
    source = SERVICE.read_text(encoding="utf-8")

    direct = source.index("geometry.GetBoundingBox(true)")
    fallback = source.index("ResolveNativeGeometryBounds")
    assert fallback < direct
    for evidence in (
        "InstanceObject rootInstance",
        "InstanceReferenceGeometry rootReference",
        "rootReference.ParentIdefId != rootDefinition.Id",
        "documentDefinition.GetObjects()",
        "documentDefinition.GetObjectIds()",
        "InstanceObject nestedInstance",
        "InstanceReferenceGeometry nestedReference",
        "worldTransform * nestedReference.Xform",
        "memberGeometry.GetBoundingBox(worldTransform)",
        'resolution.Source = "instance_definition_geometry_traversal"',
        '["top_level_native_bbox"]',
        '["native_bbox_source"]',
        '["native_bbox_status"]',
    ):
        assert evidence in source


def test_csharp_persisted_roof_bbox_fallback_is_bounded_owned_and_fail_closed():
    source = SERVICE.read_text(encoding="utf-8")

    for evidence in (
        "InstanceBoundsMaxDepth = 32",
        "InstanceBoundsMaxMembers = 10000",
        "activeDefinitionPath.Add(definition.Id)",
        '"instance_definition_cycle_detected"',
        '"instance_definition_depth_limit_exceeded"',
        '"instance_definition_member_limit_exceeded"',
        "doc.InstanceDefinitions.Find(definition.Id, true)",
        "member.Attributes.IsInstanceDefinitionObject",
        "ObjectMode.InstanceDefinitionObject",
        "member.IsReference",
        "memberIds.SetEquals(declaredIdSet)",
        "nestedReference.ParentIdefId != nestedDefinition.Id",
        "nestedReference.Xform.IsAffine",
        "resolution.LeafGeometryCount == 0",
        "resolution.OwnershipVerified = true",
        "resolution.TransformChainVerified = true",
        '["failure_code"] = resolution.FailureCode',
        '["fallback_complete"] = resolution.FallbackComplete',
    ):
        assert evidence in source


def test_csharp_setter_boole_are_diagnostic_and_readback_is_authoritative():
    source = SERVICE.read_text(encoding="utf-8")

    assert '"acceptance_source"] = "post_setter_exact_readback"' in source
    assert '"returned"] = setterReturned' in source
    assert "SetSlope returned false" not in source
    assert "SetRoofGableHeight returned false" not in source
    assert '"slopes_match"] = slopeMatch' in source
    assert '"gable_height_matches"] = heightMatch' in source


def test_roof_dispatcher_registers_tools_and_keeps_create_undo_wrapped():
    source = DISPATCHER.read_text(encoding="utf-8")
    undo_start = source.index("private static readonly HashSet<string> UndoFreeCommands")
    undo_end = source.index("private JObject ExecuteCommandInternal", undo_start)
    undo_block = source[undo_start:undo_end]

    for name in (
        "va_roof_capabilities",
        "va_list_roof_styles",
        "va_list_roofs",
        "va_get_roof",
    ):
        assert f'"{name}"' in undo_block
        assert f'["{name}"]' in source
    assert '"va_create_roof_from_curve"' not in undo_block
    assert '["va_create_roof_from_curve"]' in source
    assert "this.handler.CreateVisualArqRoofFromCurve" in source


def test_roof_operations_are_thin_and_use_shared_service():
    source = OPERATIONS.read_text(encoding="utf-8")

    assert "VisualArqRoofService.CreateRoofFromCurve" in source
    assert "VisualArqRoofService.ListRoofStyles" in source
    assert "VisualArqRoofService.ListRoofs" in source
    assert "VisualArqRoofService.GetRoof" in source
    assert "AddRoofFromCurve.Invoke" not in source
