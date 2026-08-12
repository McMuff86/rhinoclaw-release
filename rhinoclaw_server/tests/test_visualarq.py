"""Tests for the VisualARQ BIM tools (4.1) — incl. graceful degradation."""
import ast
import json
from unittest.mock import MagicMock, patch

PATCH = "rhinoclaw.tools.visualarq.get_rhino_connection"
PRINT = "Script successfully executed! Print output: "


def _rhino(va_result):
    rhino = MagicMock()
    rhino.send_command.return_value = PRINT + "RESULT:" + json.dumps(va_result)
    return rhino


def _rhino_sequence(*va_results):
    rhino = MagicMock()
    rhino.send_command.side_effect = [
        PRINT + "RESULT:" + json.dumps(result) for result in va_results
    ]
    return rhino


def _params_from_code(code):
    marker = "params_reader = JsonTextReader(System.IO.StringReader("
    line = next(line for line in code.splitlines() if marker in line)
    literal = line.split(marker, 1)[1].rsplit("))", 1)[0]
    return json.loads(ast.literal_eval(literal))


def _opening_profile_snapshot_runtime():
    """Execute the pure profile snapshot helper with a replaceable fake VA."""
    from rhinoclaw.tools.visualarq import _STYLE_SCRIPT_HELPERS

    start = _STYLE_SCRIPT_HELPERS.index("def va_opening_profile_snapshot(")
    end = _STYLE_SCRIPT_HELPERS.index("def va_opening_template_snapshot(")
    source = _STYLE_SCRIPT_HELPERS[start:end]

    class Guid:
        Empty = "EMPTY"

    namespace = {
        "Guid": Guid,
        "va": None,
        "va_text": lambda value: value,
        "va_valid_double": lambda value: float(value),
        "va_method_available": lambda name: name == "IsOpeningProfile",
        "va_opening_profile_shape_contract": lambda: {
            "pass": True,
            "failed_methods": [],
        },
    }
    exec(compile(source, "<va_opening_profile_snapshot>", "exec"), namespace)
    return namespace


def _ifc_parser_functions():
    """Execute the pure STEP parser functions from the generated Rhino code."""
    from rhinoclaw.tools.visualarq import va_ifc_export

    rhino = _rhino({"status": "error", "message": "parser capture"})
    with patch(PATCH, return_value=rhino):
        va_ifc_export(MagicMock(), "C:/x/parser-capture.ifc")
    code = rhino.send_command.call_args[0][1]["code"]
    module = ast.parse(code, filename="<va_ifc_export_parser>")

    generated_functions = sorted(
        (
            node for node in ast.walk(module)
            if isinstance(node, ast.FunctionDef)
        ),
        key=lambda node: node.lineno,
    )
    start = next(
        index for index, node in enumerate(generated_functions)
        if node.name == "step_statements"
    )
    end = next(
        index for index, node in enumerate(generated_functions[start:], start)
        if node.name == "validate_ifc"
    )
    parser_nodes = generated_functions[start:end]

    assert parser_nodes
    assert parser_nodes[0].name == "step_statements"
    assert any(node.name == "step_entity_inventory" for node in parser_nodes)
    parser_module = ast.Module(body=parser_nodes, type_ignores=[])
    namespace = {"math": __import__("math"), "re": __import__("re")}
    exec(compile(parser_module, "<va_ifc_export_parser>", "exec"), namespace)
    return namespace


def _valid_ifc_project_statements():
    """Small, reference-complete IFC project fixture for parser tests."""
    return [
        (
            "#1=IFCPROJECT('0000000000000000000000',$,"
            "'RhinoClaw parser fixture',$,$,$,$,(#2),#3);"
        ),
        "#2=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#4,$);",
        "#3=IFCUNITASSIGNMENT((#5));",
        "#4=IFCAXIS2PLACEMENT3D(#6,$,$);",
        "#5=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);",
        "#6=IFCCARTESIANPOINT((0.,0.,0.));",
    ]


def _valid_ifc_header_statements(schema="IFC4"):
    return [
        "FILE_DESCRIPTION(('CoordinationView'),'2;1');",
        (
            "FILE_NAME('model.ifc','2026-08-08T18:00:00',('RhinoClaw'),"
            "('OpenAI'),'RhinoClaw','Rhino','');"
        ),
        f"FILE_SCHEMA(('{schema}'));",
    ]


UNAVAILABLE = {"available": False, "status": "unavailable",
               "message": "VisualARQ not available: not found"}


def test_status_available_reports_inventory():
    from rhinoclaw.tools.visualarq import va_status

    rhino = _rhino({
        "available": True,
        "visualarq": {
            "version": "3.7.2.19413",
            "product_version": "3.7.2.19413",
            "file_version": "3.7.2.19413",
            "assembly_version": "3.7.2.0",
        },
        "document": {
            "units": "Millimeters", "absolute_tolerance": 0.01,
            "relative_tolerance": 0.01,
            "angle_tolerance_radians": 0.0174532925199433,
        },
        "capabilities": {
            "methods": {
                "AddDoor": True,
                "SetDoorWidth": False,
                "SetDoorHeight": False,
                "GetOpeningHost": True,
            },
            "door_direct_dimension_override": False,
            "opening_profile_readback": True,
            "method_shapes": {
                "AddWall": [["styleId", "startPoint", "endPoint"]],
                "AddDoor": [["doorStyleId", "position", "rotation"]],
            },
        },
        "wall_styles": 4, "door_styles": 6,
        "window_styles": 5, "slab_styles": 3, "space_styles": 2,
        "levels": 2,
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_status(MagicMock()))

    assert data["success"] is True
    assert data["data"]["available"] is True
    assert data["data"]["door_styles"] == 6
    assert data["data"]["slab_styles"] == 3
    assert data["data"]["space_styles"] == 2
    assert data["data"]["visualarq"]["version"] == "3.7.2.19413"
    assert data["data"]["document"]["units"] == "Millimeters"
    assert data["data"]["document"]["absolute_tolerance"] == 0.01
    methods = data["data"]["capabilities"]["methods"]
    assert methods["GetOpeningHost"] is True
    assert methods["SetDoorWidth"] is False
    assert rhino.send_command.call_count == 2
    load_probe = rhino.send_command.call_args_list[0][0][1]["code"]
    assert "VA_LOAD_PROBE:ready" in load_probe
    status_code = rhino.send_command.call_args[0][1]["code"]
    compile(status_code, "<va_status>", "exec")
    for method_name in (
        "GetWallThickness", "GetWallPathCurve", "GetWallLayers",
        "GetWallLayerTopOffsetSource", "GetWallLayerBottomOffsetSource",
        "GetOpeningProfile", "SetOpeningProfile",
        "AddDoorStyle", "AddOpeningStyleSizeProfile",
        "SetRectangularProfileSize", "DeleteProfile",
        "AddWindow", "AddWindowStyle", "AddBuilding", "GetAllBuildingIds",
        "AddSlabFromCurve", "GetSlabContour", "AddSpaceFromCurve",
        "GetSpaceCurve", "GetSpaceArea", "SetSpaceLabelPosition",
    ):
        assert f'"{method_name}"' in status_code
    assert 'window_modern_shape = va_exact_method_shape("AddWindow", [' in \
        status_code
    assert '"window_point_api": window_modern_shape["verified"]' in \
        status_code
    assert '"slab_curve_api": slab_curve_shape["verified"]' in status_code
    assert '"space_curve_api": space_curve_shape["verified"]' in status_code
    assert (
        'window_style_shape = va_exact_method_shape("AddWindowStyle", ['
    ) in status_code
    assert (
        '"window_style_rectangular_api": '
        'window_style_shape["verified"]'
    ) in status_code
    assert '"AddWindow": va_method_parameter_sets("AddWindow")' in \
        status_code
    assert "ModelUnitSystem" in status_code


def test_status_degrades_gracefully_without_va():
    from rhinoclaw.tools.visualarq import va_status

    with patch(PATCH, return_value=_rhino(UNAVAILABLE)):
        data = json.loads(va_status(MagicMock()))

    # A query: not-installed is an ANSWER, not an error.
    assert data["success"] is True
    assert data["data"]["available"] is False
    assert "hint" in data["data"]


def test_status_retries_only_the_read_only_body_after_cold_bootstrap():
    from rhinoclaw.tools.visualarq import va_status

    ready = {
        "available": True,
        "wall_styles": 0,
        "door_styles": 0,
        "window_styles": 0,
        "levels": 0,
        "buildings": 0,
    }
    rhino = MagicMock()
    rhino.send_command.side_effect = [
        {"success": True, "result": "VA_LOAD_PROBE:ready"},
        {"success": True, "result": PRINT},
        PRINT + "RESULT:" + json.dumps(ready),
    ]

    with patch(PATCH, return_value=rhino):
        result = json.loads(va_status(MagicMock()))

    assert result["success"] is True
    assert result["data"]["bootstrap_retry_attempted"] is True
    assert result["data"]["bootstrap_retry_reason"] == \
        "missing_result_marker"
    assert rhino.send_command.call_count == 3


def test_status_does_not_retry_an_explicit_script_failure():
    from rhinoclaw.tools.visualarq import va_status

    rhino = MagicMock()
    rhino.send_command.side_effect = [
        {"success": True, "result": "VA_LOAD_PROBE:ready"},
        {"success": False, "message": "script traceback"},
    ]

    with patch(PATCH, return_value=rhino):
        result = json.loads(va_status(MagicMock()))

    assert result["success"] is False
    assert result["data"]["runner_failure"] == "script_execution_failed"
    assert rhino.send_command.call_count == 2


def test_status_surfaces_script_errors_instead_of_reporting_available():
    from rhinoclaw.tools.visualarq import va_status

    with patch(PATCH, return_value=_rhino({
        "status": "error", "message": "reflection failed",
    })):
        data = json.loads(va_status(MagicMock()))

    assert data["success"] is False
    assert data["message"] == "reflection failed"


def test_action_tools_fail_cleanly_without_va():
    from rhinoclaw.tools.visualarq import va_create_wall

    with patch(PATCH, return_value=_rhino(UNAVAILABLE)):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 0, 0], [4000, 0, 0], 2400))

    assert data["success"] is False
    assert data["data"]["available"] is False
    assert "visualarq.com" in data["message"]


def test_create_wall_injects_params_and_returns_id():
    from rhinoclaw.tools.visualarq import va_create_wall

    rhino = _rhino({
        "status": "success", "wall_id": "guid-w1",
        "style": "Generic", "requested_height": 2400,
        "applied_height": 2400, "actual_height": 2399.5,
        "height_source": "GetWallHeight",
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 3000, 0], [4000, 3000, 0], 2400))

    assert data["success"] is True
    assert data["data"]["wall_id"] == "guid-w1"
    assert data["data"]["actual_height"] == 2399.5
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_wall>", "exec")
    # Params travel as JSON, not string interpolation.
    sent = _params_from_code(code)
    assert sent["style"] == "Generic"
    assert sent["start"] == [0, 3000, 0]
    assert sent["height"] == 2400
    assert 'va_resolve_style(params["style"], "wall")' in code
    assert '"wall_style_has_no_measurable_layers"' in code
    assert "va_product_snapshot(obj, classification_probe)" in code
    assert "va_instance_definition_volume_snapshot" in code
    assert 'volume_source = "object_geometry"' in code
    assert 'volume_source = quantity.get("source")' in code
    assert '"creation_pass"' in code
    assert '"quantity_verification_pass"' in code


def test_create_wall_refreshes_async_definition_quantity_without_sleeping():
    from rhinoclaw.tools.visualarq import va_create_wall

    initial_actual = {
        "runtime_serial_number": 101,
        "height": 2800.0,
        "quantity": {
            "source": "instance_definition_solid_geometry",
            "volume": None, "volume_verified": False,
        },
    }
    refreshed_actual = {
        "runtime_serial_number": 101,
        "readback_complete": True,
        "style_id": "style-guid",
        "classifications": ["wall", "product", "building_element"],
        "height": 2800.0,
        "height_source": {"name": "Object", "value": 1},
        "thickness": 230.0,
        "path": {
            "start": [0.0, 0.0, 0.0],
            "end": [4000.0, 0.0, 0.0],
            "length": 4000.0,
        },
        "geometry": {
            "volume": None, "is_valid": True,
            "bbox_valid": True, "bbox_diagonal": 4950.0,
        },
        "quantity": {
            "source": "instance_definition_solid_geometry",
            "volume": 2576000000.0, "volume_verified": True,
            "measurement_complete": True,
        },
    }
    rhino = _rhino_sequence(
        {
            "status": "success", "wall_id": "guid-w1",
            "style": {
                "id": "style-guid", "total_layer_thickness": 230.0,
            },
            "actual": initial_actual,
            "warnings": [
                "Independent positive volume is not verified; verify later",
            ],
            "verification": {
                "pass": False, "creation_pass": True,
                "quantity_verification_pass": False,
                "tolerance": 0.001,
            },
        },
        {"status": "success", "object": refreshed_actual},
    )
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 0, 0], [4000, 0, 0], 2800))

    verification = data["data"]["verification"]
    assert data["success"] is True
    assert rhino.send_command.call_count == 2
    assert verification["pass"] is True
    assert verification["creation_pass"] is True
    assert verification["quantity_verification_pass"] is True
    assert verification["volume"] == 2576000000.0
    assert verification["volume_source"] == \
        "instance_definition_solid_geometry"
    assert verification["post_creation_readback"] == {
        "attempted": True,
        "attempt_count": 1,
        "complete": True,
        "reason": "visualarq_instance_definition_is_populated_asynchronously",
        "readback_runtime_serial_number": 101,
    }
    assert data["data"]["warnings"] == []
    refresh_code = rhino.send_command.call_args_list[1][0][1]["code"]
    compile(refresh_code, "<va_create_wall_refresh>", "exec")
    assert "va_instance_definition_volume_snapshot" in refresh_code
    assert "sleep" not in refresh_code.lower()


def test_create_wall_refresh_rechecks_fields_and_retains_mismatch():
    from rhinoclaw.tools.visualarq import va_create_wall

    rhino = _rhino_sequence(
        {
            "status": "success", "wall_id": "guid-w1",
            "style": {
                "id": "expected-style", "total_layer_thickness": 230.0,
            },
            "actual": {"runtime_serial_number": 102},
            "verification": {
                "pass": False, "creation_pass": True,
                "creation_checks": {"object_readable": True},
                "quantity_verification_pass": False, "tolerance": 0.001,
            },
            "warnings": [],
        },
        {
            "status": "success",
            "object": {
                "runtime_serial_number": 102,
                "style_id": "wrong-style",
                "classifications": ["wall", "product"],
                "height": 2800.0, "thickness": 230.0,
                "path": {
                    "start": [0, 0, 0], "end": [4000, 0, 0],
                    "length": 4000.0,
                },
                "geometry": {
                    "volume": None, "is_valid": True,
                    "bbox_valid": True, "bbox_diagonal": 4950.0,
                },
                "quantity": {
                    "source": "instance_definition_solid_geometry",
                    "volume": 2576000000.0, "volume_verified": True,
                },
            },
        },
    )
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 0, 0], [4000, 0, 0], 2800))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    assert data["data"]["wall_id"] == "guid-w1"
    assert data["data"]["cleanup_verified"] is False
    assert data["data"]["cleanup_deleted"] is False
    assert data["data"]["cleanup_refused_reason"] == \
        "cross_command_readback_is_read_only"
    assert data["data"]["verification"]["creation_pass"] is False
    assert data["data"]["verification"]["creation_checks"][
        "style_matches"
    ] is False
    assert data["data"]["verification"]["pass"] is False
    assert rhino.send_command.call_count == 2


def test_create_wall_verifies_visualarq_regeneration_for_readback_only():
    """VA 3.7 keeps the wall GUID but replaces its Rhino generation."""
    from rhinoclaw.tools.visualarq import va_create_wall

    refreshed_actual = {
        "runtime_serial_number": 106,
        "readback_complete": True,
        "style_id": "style-guid",
        "classifications": ["wall", "product", "building_element"],
        "height": 2800.0,
        "thickness": 230.0,
        "path": {
            "start": [0.0, 0.0, 0.0],
            "end": [4000.0, 0.0, 0.0],
            "length": 4000.0,
        },
        "geometry": {
            "volume": None, "is_valid": True,
            "bbox_valid": True, "bbox_diagonal": 4950.0,
        },
        "quantity": {
            "source": "instance_definition_solid_geometry",
            "volume": 2576000000.0, "volume_verified": True,
        },
    }
    rhino = _rhino_sequence(
        {
            "status": "success", "wall_id": "guid-w1",
            "creation_runtime_serial_floor": 100,
            "owned_runtime_serial_number": 101,
            "runtime_generation_history": [101],
            "style": {
                "id": "style-guid", "total_layer_thickness": 230.0,
            },
            "actual": {"runtime_serial_number": 101},
            "verification": {
                "pass": False, "creation_pass": True,
                "quantity_verification_pass": False, "tolerance": 0.001,
            },
            "warnings": [],
        },
        {"status": "success", "object": refreshed_actual},
    )
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 0, 0], [4000, 0, 0], 2800))

    assert data["success"] is True
    wall = data["data"]
    assert wall["owned_runtime_serial_number"] == 101
    assert wall["readback_runtime_serial_number"] == 106
    assert wall["runtime_generation_history"] == [101, 106]
    generation = wall["verification"]["runtime_generation"]
    assert generation["replacement_verified_for_readback"] is True
    assert generation["cross_command_cleanup_authorized"] is False
    assert generation["initial_command_owned_runtime_serial_number"] == 101
    assert generation["readback_runtime_serial_number"] == 106
    assert generation["creation_runtime_serial_floor"] == 100
    assert wall["verification"]["pass"] is True


def test_create_wall_changed_generation_mismatch_refuses_cleanup():
    from rhinoclaw.tools.visualarq import va_create_wall

    rhino = _rhino_sequence(
        {
            "status": "success", "wall_id": "guid-w1",
            "creation_runtime_serial_floor": 100,
            "owned_runtime_serial_number": 101,
            "runtime_generation_history": [101],
            "style": {
                "id": "expected-style", "total_layer_thickness": 230.0,
            },
            "actual": {"runtime_serial_number": 101},
            "verification": {
                "pass": False, "creation_pass": True,
                "quantity_verification_pass": False, "tolerance": 0.001,
            },
            "warnings": [],
        },
        {
            "status": "success",
            "object": {
                "runtime_serial_number": 109,
                "readback_complete": True,
                "style_id": "wrong-style",
                "classifications": ["wall", "product"],
                "height": 2800.0, "thickness": 230.0,
                "path": {
                    "start": [0, 0, 0], "end": [4000, 0, 0],
                    "length": 4000.0,
                },
                "geometry": {
                    "volume": None, "is_valid": True,
                    "bbox_valid": True, "bbox_diagonal": 4950.0,
                },
                "quantity": {
                    "source": "instance_definition_solid_geometry",
                    "volume": 2576000000.0, "volume_verified": True,
                },
            },
        },
    )
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 0, 0], [4000, 0, 0], 2800))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    wall = data["data"]
    assert wall["cleanup_deleted"] is False
    assert wall["cleanup_verified"] is False
    assert wall["owned_runtime_serial_number"] == 101
    assert wall["readback_runtime_serial_number"] == 109
    assert wall["runtime_generation_history"] == [101, 109]
    assert rhino.send_command.call_count == 2


def test_create_wall_refresh_exception_preserves_created_wall_identity():
    from rhinoclaw.tools.visualarq import va_create_wall

    rhino = MagicMock()
    initial = {
        "status": "success", "wall_id": "guid-w1",
        "style": {"id": "style-guid", "total_layer_thickness": 230.0},
        "actual": {"runtime_serial_number": 103},
        "verification": {
            "pass": False, "creation_pass": True,
            "quantity_verification_pass": False, "tolerance": 0.001,
        },
        "warnings": [],
    }
    rhino.send_command.side_effect = [
        PRINT + "RESULT:" + json.dumps(initial),
        RuntimeError("refresh transport failed"),
        RuntimeError("refresh transport failed"),
        RuntimeError("refresh transport failed"),
    ]
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 0, 0], [4000, 0, 0], 2800))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    assert data["data"]["wall_id"] == "guid-w1"
    verification = data["data"]["verification"]
    assert verification["creation_pass"] is True
    assert verification["quantity_verification_pass"] is False
    assert verification["post_creation_readback"]["attempt_count"] == 3
    assert "refresh transport failed" in verification[
        "post_creation_readback"
    ]["last_error"]
    assert data["data"]["warnings"]
    assert data["data"]["cleanup_deleted"] is False
    assert data["data"]["cleanup_refused_reason"] == \
        "cross_command_readback_is_read_only"


def test_create_wall_bounds_generation_before_add_and_guards_only_delete():
    from rhinoclaw.tools.visualarq import va_create_wall

    rhino = _rhino({
        "status": "success", "wall_id": "guid-w1",
        "style": {"id": "style-guid", "total_layer_thickness": 230.0},
        "actual": {"runtime_serial_number": 101},
        "verification": {
            "pass": True, "creation_pass": True,
            "quantity_verification_pass": True,
        },
        "warnings": [],
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 0, 0], [4000, 0, 0], 2800))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_wall_generation_guard>", "exec")

    generation_bound = code.index("next_runtime_serial_before = int(")
    guid_baseline = code.index(
        "object_ids_before = set(str(obj.Id) for obj in sc.doc.Objects)")
    add_wall = code.index("wall_id = va.AddWall(")
    initial_find = code.index("initial_obj = sc.doc.Objects.FindId(wall_id)")
    initial_serial = code.index(
        "candidate_runtime_serial = int(initial_obj.RuntimeSerialNumber)")
    ownership_check = code.index(
        "if candidate_runtime_serial < next_runtime_serial_before:")
    owned_serial = code.index(
        "created_runtime_serial = candidate_runtime_serial")
    set_height = code.index("set_height = va.SetWallHeight(")
    assert generation_bound < guid_baseline < add_wall < initial_find < \
        initial_serial
    assert "if returned_guid_was_preexisting:" in code
    assert "AddWall returned a pre-existing object Guid" in code
    assert '"readback_complete": actual is not None and' in code
    assert '"returned_guid_was_preexisting":' in code
    assert initial_serial < ownership_check < owned_serial < set_height

    assert code.count("sc.doc.Objects.Delete(") == 1
    assert "sc.doc.Objects.Delete(wall_id" not in code
    cleanup_find = code.index("cleanup_obj = sc.doc.Objects.FindId(object_id)")
    serial_check = code.index("actual_serial == expected_serial")
    cleanup_guard = code.index(
        "if cleanup_obj is not None and serial_matches:")
    cleanup_delete = code.index("sc.doc.Objects.Delete(object_id, True)")
    assert cleanup_find < serial_check < cleanup_guard < cleanup_delete
    assert "expected_serial is not None" in code
    assert '"replacement_detected": serial_matches is False' in code
    squashed = "".join(code.replace("\\", "").split())
    assert (
        '"cleanup_verified":object_existsisFalseand'
        "serial_matchesisnotFalseandis_wallisFalse"
    ) in squashed


def test_create_wall_retains_empty_guid_candidate_and_reports_residuals():
    from rhinoclaw.tools.visualarq import va_create_wall

    wall_failure = {
        "status": "error", "code": "PARTIAL_MUTATION",
        "message": "Created wall generation could not be cleaned safely",
        "wall_id": "11111111-1111-1111-1111-111111111111",
        "created_runtime_serial_number": 101,
        "cleanup_actual_runtime_serial_number": 202,
        "cleanup_runtime_serial_matches": False,
        "replacement_detected": True,
        "cleanup_verified": False,
        "residual_new_generations": [{
            "id": "11111111-1111-1111-1111-111111111111",
            "runtime_serial_number": 202,
        }],
        "residual_scan_errors": [],
    }
    rhino = _rhino(wall_failure)
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall(
            MagicMock(), "Generic", [0, 0, 0], [4000, 0, 0], 2800))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    assert data["data"]["replacement_detected"] is True
    assert data["data"]["cleanup_runtime_serial_matches"] is False
    assert data["data"]["residual_new_generations"] == \
        wall_failure["residual_new_generations"]

    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_wall_residual_recovery>", "exec")
    assert "sc.doc.Objects.AllObjectsSince(" in code
    assert "max(next_runtime_serial_before - 1, 0)" in code
    squashed = "".join(code.replace("\\", "").split())
    assert (
        "current_obj.RuntimeSerialNumber)!=int("
        "recent_obj.RuntimeSerialNumber)"
    ) in squashed
    assert "active_generations.append({" in code
    assert "if va.IsWall(current_obj.Id):" in code
    assert "candidate_style_id == style_id" in code

    empty_guid_recovery = code.index(
        "if cleanup_target_id == Guid.Empty and len(candidates) == 1 and")
    next_branch = code.index(
        "elif cleanup_target_id != Guid.Empty and", empty_guid_recovery)
    empty_guid_branch = code[empty_guid_recovery:next_branch]
    assert 'cleanup_target_id = Guid(candidates[0]["id"])' not in \
        empty_guid_branch
    assert 'cleanup_target_serial = candidates[0]["runtime_serial_number"]' \
        not in empty_guid_branch
    assert "recovered_wall_id = candidates[0][\"id\"]" in code
    assert '"recovered_wall_id": recovered_wall_id' in code
    assert "diagnostic evidence, not causal ownership" in code
    assert '"cleanup_refused_reason": cleanup_refused_reason' in code
    assert "not active_generations and not candidate_errors" in code

    residual_scan = code.rindex(
        "residual_candidates, residual_errors, residual_generations =")
    residual_gate = code.rindex(
        "if residual_generations or residual_errors:")
    result_assignment = code.index(
        '"residual_new_generations": residual_generations', residual_gate)
    assert empty_guid_recovery < residual_scan < residual_gate < result_assignment
    assert 'else "PARTIAL_MUTATION"' in code


def test_create_door_by_point():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({"status": "success", "door_id": "guid-d1",
                    "style": "T80", "point": [2500, 3000, 0],
                    "host": {"id": "guid-w1", "source": "GetOpeningHost"},
                    "requested_dimensions": {"width": None, "height": None},
                    "applied_dimensions": {}, "actual_dimensions": {},
                    "dimension_sources": {}})
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80", point=[2500, 3000, 0]))

    assert data["success"] is True
    assert data["data"]["door_id"] == "guid-d1"
    assert data["data"]["host"]["source"] == "GetOpeningHost"


def _async_opening_receipt(kind="door"):
    wall_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    profile_id = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
    api_return_id = "cccccccc-dddd-eeee-ffff-000000000001"
    empty_key = f"add{kind}_returned_empty_guid"
    return {
        "status": "error",
        "code": "PARTIAL_MUTATION",
        "message": f"{kind.title()} creation deferred",
        "reason": f"{kind}_materialization_pending_after_add",
        f"{kind}_id": None,
        "api_return_id": api_return_id,
        "resolved_style_id": "dddddddd-eeee-ffff-0000-111111111111",
        "creation_runtime_serial_floor": 590,
        "preadd_object_ids": [wall_id],
        "selected_profile_id": profile_id,
        "style_profiles_before": [{
            "id": profile_id,
            "name": "900x2100",
            "readback_complete": True,
        }],
        "host_cleanup_results": [{
            "wall_id": wall_id,
            "baseline": {
                "id": wall_id,
                "readback_complete": True,
            },
        }],
        "spatial_host_baseline_complete": True,
        "mutation_started": True,
        "materialization_pending": True,
        "returned_guid_was_preexisting": False,
        empty_key: False,
        "created_runtime_serial_number": None,
        "cleanup_object_exists": False,
        "cleanup_deleted": False,
        "cleanup_verified": False,
    }


def test_create_door_resolves_deferred_materialization_to_actual_guid():
    from rhinoclaw.tools.visualarq import va_create_door

    receipt = _async_opening_receipt()
    actual_id = "eeeeeeee-ffff-0000-1111-222222222222"
    final = {
        "status": "success",
        "door_id": actual_id,
        "api_return_id": receipt["api_return_id"],
        "verification": {"pass": True},
        "candidate_generations": [{
            "id": actual_id,
            "runtime_serial_number": 596,
        }],
    }
    rhino = _rhino_sequence(receipt, final)
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(),
            "Deferred Door",
            point=[1800, 0, 0],
            rotation=0,
            wall_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            width=900,
            height=2100,
        ))

    assert data["success"] is True
    actual = data["data"]
    assert actual["door_id"] == actual_id
    assert actual["api_return_id"] == receipt["api_return_id"]
    async_readback = actual["async_materialization"]
    assert async_readback["complete"] is True
    assert async_readback["object_id_changed"] is True
    assert async_readback["materialization_attribution_verified"] is True
    assert async_readback["exact_generation_verified"] is True
    assert async_readback["cleanup_ownership_verified"] is False
    assert async_readback["attribution_method"] == \
        "unique_active_object_delta_plus_full_contract"
    assert async_readback["cross_command_cleanup_authorized"] is False
    assert rhino.send_command.call_count == 2

    creation_code = rhino.send_command.call_args_list[0][0][1]["code"]
    compile(creation_code, "<va_create_door_async_receipt>", "exec")
    pending_mark = creation_code.index(
        '"door_materialization_pending_after_add"')
    pending_cleanup = creation_code.index(
        "if materialization_pending:", pending_mark)
    cleanup_delete = creation_code.index(
        "sc.doc.Objects.Delete(cleanup_target_id, True)", pending_cleanup)
    assert pending_cleanup < cleanup_delete
    assert "cleanup_target_id = Guid.Empty" in \
        creation_code[pending_cleanup:cleanup_delete]
    assert '"door_id": None if materialization_pending else (' in \
        creation_code
    assert '"api_return_id": str(door_id)' in creation_code
    assert '"preadd_object_ids": sorted(object_ids_before)' in creation_code

    refresh_call = rhino.send_command.call_args_list[1]
    refresh_code = refresh_call[0][1]["code"]
    refresh_params = _params_from_code(refresh_code)
    compile(refresh_code, "<va_create_door_async_readback>", "exec")
    assert refresh_params["serial_floor"] == 590
    assert refresh_params["api_return_id"] == receipt["api_return_id"]
    assert refresh_params["preadd_object_ids"] == receipt[
        "preadd_object_ids"]
    assert "AllObjectsSince" in refresh_code
    assert "added_object_ids" in refresh_code
    assert "removed_object_ids" in refresh_code
    assert "only_authoritative_host_definition_changed" in refresh_code
    assert "other_spatial_hosts_unchanged" in refresh_code
    assert "cross_command_cleanup_authorized" in refresh_code
    assert "sc.doc.Objects.Delete" not in refresh_code
    assert "SetOpeningProfile" not in refresh_code
    assert "AddDoor(" not in refresh_code
    assert "sleep" not in refresh_code.lower()


def test_create_door_bounds_deferred_materialization_retries_without_sleep():
    from rhinoclaw.tools.visualarq import va_create_door

    receipt = _async_opening_receipt()
    pending = {
        "status": "pending",
        "reason": "async_opening_object_not_published_yet",
        "candidate_generations": [],
    }
    final = {
        "status": "success",
        "door_id": "eeeeeeee-ffff-0000-1111-222222222222",
        "candidate_generations": [{
            "id": "eeeeeeee-ffff-0000-1111-222222222222",
            "runtime_serial_number": 596,
        }],
    }
    rhino = _rhino_sequence(receipt, pending, final)
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "Deferred Door", point=[1800, 0, 0]))

    assert data["success"] is True
    async_readback = data["data"]["async_materialization"]
    assert async_readback["attempt_count"] == 2
    assert [item["status"] for item in async_readback["attempts"]] == [
        "pending", "success",
    ]
    assert rhino.send_command.call_count == 3


def test_create_door_deferred_ambiguity_remains_partial_without_cleanup():
    from rhinoclaw.tools.visualarq import va_create_door

    receipt = _async_opening_receipt()
    ambiguous = {
        "status": "error",
        "code": "PARTIAL_MUTATION",
        "reason": "async_opening_generation_delta_unverified",
        "message": "two matching deferred doors",
        "candidate_generations": [
            {"id": "candidate-1", "runtime_serial_number": 596},
            {"id": "candidate-2", "runtime_serial_number": 597},
        ],
        "cross_command_cleanup_authorized": False,
    }
    rhino = _rhino_sequence(receipt, ambiguous)
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "Deferred Door", point=[1800, 0, 0]))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    failure = data["data"]
    assert len(failure["candidate_generations"]) == 2
    assert failure["cleanup_deleted"] is False
    assert failure["cleanup_verified"] is False
    assert failure["cleanup_refused_reason"] == \
        "cross_command_cleanup_is_forbidden"
    assert failure["async_materialization"][
        "cross_command_cleanup_authorized"] is False


def test_create_window_specializes_the_shared_verified_opening_vertical():
    from rhinoclaw.tools.visualarq import va_create_window

    rhino = _rhino({
        "status": "success", "window_id": "guid-win1",
        "style": "W90", "host": {
            "id": "guid-wall1", "source": "GetOpeningHost",
        },
        "verification": {"pass": True},
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_window(
            MagicMock(), "W90", point=[2500, 0, 1000],
            wall_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            width=900, height=1200,
        ))

    assert data["success"] is True
    assert data["data"]["window_id"] == "guid-win1"
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_window>", "exec")
    assert 'va_resolve_style(params["style"], "window")' in code
    assert 'window_modern_shape = va_exact_method_shape("AddWindow", [' in code
    assert "returned_window_id = va.AddWindow(" in code
    assert '"classified_as_window": bool(va.IsWindow(window_id))' in code
    assert '"reason": "window_add_signature_unverified"' in code
    assert '"window_id": str(window_id)' in code
    assert "GetOpeningHost" in code
    assert "SetWindowWidth" not in code
    assert "SetWindowHeight" not in code
    assert _params_from_code(code)["wall_id"] == \
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_create_window_uses_the_same_local_input_guards_as_door():
    from rhinoclaw.tools.visualarq import va_create_window

    missing_placement = json.loads(va_create_window(MagicMock(), "W90"))
    bad_point = json.loads(va_create_window(
        MagicMock(), "W90", point=[0, float("nan"), 0]))
    bad_width = json.loads(va_create_window(
        MagicMock(), "W90", point=[0, 0, 0], width=0))

    assert missing_placement["code"] == "INVALID_PARAMS"
    assert bad_point["code"] == "INVALID_PARAMS"
    assert bad_width["code"] == "INVALID_PARAMS"


def test_create_door_canonicalizes_legacy_wall_guid_in_params():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "success", "door_id": "guid-d1", "style": "T80",
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80",
            wall_id="{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}",
            position=1250,
        ))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_legacy>", "exec")
    assert _params_from_code(code)["wall_id"] == \
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_create_door_fails_closed_for_legacy_position_overload_before_add():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "success", "door_id": "guid-d1", "style": "T80",
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80", point=[2500, 3000, 0]))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_placement_contract>", "exec")
    modern_guard = 'elif point_placement_api and not params.get("point"):'
    legacy_guard = "elif not point_placement_api:"
    first_mutation = code.index("door_id = va.AddDoor(")
    assert 'door_modern_shape = va_exact_method_shape("AddDoor", [' in code
    assert (
        '"System.Guid", "Rhino.Geometry.Point3d", "System.Double"]'
    ) in code
    assert 'point_placement_api = door_modern_shape["verified"]' in code
    assert modern_guard in code
    assert legacy_guard in code
    assert code.index(modern_guard) < first_mutation
    assert code.index(legacy_guard) < first_mutation
    assert '"reason": "door_add_signature_unverified"' in code
    assert "has no unique supported point-placement" in code
    assert "Legacy wall-position" in code
    assert "PointAtLength" not in code
    assert 'sc.doc.Objects.FindId(Guid(params["wall_id"]))' not in code
    assert 'va.IsWall(Guid(params["wall_id"]))' not in code
    assert "va.GetWallPathCurve(wall_obj.Id)" in code
    assert "def door_instance_placement(obj):" in code
    assert "xform = obj.InstanceXform" in code
    assert '"opening_position_matches"' in code
    assert '"rotation_matches"' in code
    assert "rotation_delta_degrees" in code
    assert '"product_readback_complete"' in code
    assert '"geometry_valid"' in code
    assert '"bbox_nondegenerate"' in code
    assert '"profile_matches_product_readback"' in code
    assert '"host_object_exists"' in code
    assert '"host_classified_as_wall"' in code
    assert '"host_cut_independently_verified"' in code
    assert "door_host_wall_state" in code
    assert "host_cut_volume_delta" in code
    assert "host_cleanup_verified" in code
    assert "def door_host_wall_state_matches(" in code
    assert "va_instance_definition_fingerprints_match(" in code
    assert 'before_state.get("definition_fingerprint")' in code
    assert '"host_cleanup_results": host_cleanup_results' in code
    assert "if mutation_started:" in code
    for getter, return_type in (
        ("GetOpeningPosition", "Rhino.Geometry.Point3d"),
        ("GetOpeningRotation", "System.Double"),
        ("GetOpeningProfile", "System.Guid"),
        ("GetOpeningHost", "System.Guid"),
    ):
        assert f'"{getter}", ["System.Guid"], "{return_type}"' in code
    assert "object_ids_before = set(" in code
    assert "AddDoor returned a pre-existing object Guid" in code
    assert "legacy_wall_path" not in code
    assert "va.AddDoor(Guid(params[\"wall_id\"])" not in code
    assert "candidate_host_id is not None" in code


def test_create_door_rejects_missing_matching_size_profile_before_add():
    """Requested dimensions resolve through style Size Profiles, not setters."""
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "error", "code": "INVALID_PARAMS",
        "reason": "matching_door_size_profile_not_found",
        "message": "No existing rectangular profile matches",
        "requested_dimensions": {"width": 900, "height": 2100},
        "mutation_started": False,
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80", point=[2500, 3000, 0],
            width=900, height=2100))

    assert data["success"] is False
    assert data["code"] == "INVALID_PARAMS"
    assert data["data"]["reason"] == \
        "matching_door_size_profile_not_found"
    assert data["data"]["requested_dimensions"] == {
        "width": 900, "height": 2100,
    }
    assert "actual_dimensions" not in data["data"]
    assert rhino.send_command.call_count == 1
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_size_profile_preflight>", "exec")
    assert "GetOpeningStyleSizeProfiles" in code
    assert "GetRectangularProfileSize" in code
    assert "matching_profile_ids" in code
    assert "SetDoorWidth" not in code
    assert "SetDoorHeight" not in code
    preflight_cleanup = code.index(
        "# Preflight failed before AddDoor; no host mutation was called.")
    final_cleanup_gate = code.index(
        "cleanup_verified = cleanup_verified and", preflight_cleanup)
    assert "cleanup_verified = True" in \
        code[preflight_cleanup:final_cleanup_gate]


def test_create_door_reports_dimensions_from_selected_size_profile():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "success", "door_id": "guid-d1", "style": "T80",
        "selected_profile_id": "profile-guid",
        "requested_dimensions": {"width": 900, "height": 2100},
        "applied_dimensions": {"width": 900, "height": 2100},
        "actual_dimensions": {"width": 900.0, "height": 2100.0},
        "dimension_sources": {
            "width": "GetRectangularProfileSize",
            "height": "GetRectangularProfileSize",
        },
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80", point=[2500, 3000, 0],
            width=900, height=2100))

    assert data["success"] is True
    assert data["data"]["actual_dimensions"] == {
        "width": 900.0, "height": 2100.0,
    }
    assert "width" not in data["data"]
    assert "height" not in data["data"]
    creation_code = rhino.send_command.call_args[0][1]["code"]
    compile(creation_code, "<va_create_door>", "exec")
    assert '"GetOpeningHost"' in creation_code
    assert "va.GetRectangularProfileSize(profile_id)" in creation_code
    assert "va.SetOpeningProfile(door_id, selected_profile_id)" in \
        creation_code
    assert "va.GetDoorWidth(door_id)" not in creation_code
    assert 'va_resolve_style(params["style"], "door")' in creation_code
    assert 'sc.doc.Objects.Delete(cleanup_target_id, True)' in creation_code
    assert '"cleanup_verified"' in creation_code


def test_create_door_refetches_after_profile_set_and_refuses_replacement_cleanup():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino(
        {"status": "success", "door_id": "guid-d1", "style": "T80"})
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80", point=[2500, 3000, 0], width=900))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_runtime_identity>", "exec")
    initial_find = code.index("initial_obj = sc.doc.Objects.FindId(door_id)")
    initial_serial = code.index(
        "candidate_runtime_serial = int(initial_obj.RuntimeSerialNumber)")
    ownership_check = code.index(
        "if candidate_runtime_serial < next_runtime_serial_before:")
    owned_serial = code.index(
        "created_runtime_serial = candidate_runtime_serial")
    setter = code.index("profile_set_result = bool(")
    final_find = code.index("final_obj = sc.doc.Objects.FindId(door_id)")
    final_serial = code.index(
        "final_runtime_serial = int(final_obj.RuntimeSerialNumber)")
    serial_guard = code.index(
        "if final_runtime_serial != created_runtime_serial:")
    assert initial_find < initial_serial < ownership_check < owned_serial
    assert owned_serial < setter < final_find
    assert final_find < final_serial < serial_guard

    cleanup_find = code.index(
        "cleanup_obj = sc.doc.Objects.FindId(cleanup_target_id)")
    cleanup_guard = code.index(
        "cleanup_runtime_serial_matches = cleanup_obj is None or (")
    cleanup_delete = code.index(
        "sc.doc.Objects.Delete(cleanup_target_id, True)")
    assert cleanup_find < cleanup_guard < cleanup_delete
    assert "cleanup_actual_runtime_serial == cleanup_target_serial" in code
    guarded_cleanup = code[cleanup_guard:cleanup_delete]
    assert "if cleanup_obj is not None" in guarded_cleanup
    assert "cleanup_runtime_serial_matches:" in guarded_cleanup
    assert '"replacement_detected": cleanup_replacement_detected' in code


def test_create_door_requires_point_or_wall_position():
    from rhinoclaw.tools.visualarq import va_create_door

    data = json.loads(va_create_door(MagicMock(), "T80"))
    assert data["success"] is False
    assert "point" in data["message"]


def test_create_wall_validates_positive_height_and_axis():
    from rhinoclaw.tools.visualarq import va_create_wall

    zero_height = json.loads(va_create_wall(
        MagicMock(), "Generic", [0, 0, 0], [1000, 0, 0], 0))
    degenerate = json.loads(va_create_wall(
        MagicMock(), "Generic", [0, 0, 0], [0, 0, 0], 2400))

    assert zero_height["success"] is False
    assert zero_height["code"] == "INVALID_PARAMS"
    assert "positive" in zero_height["message"]
    assert degenerate["success"] is False
    assert degenerate["code"] == "INVALID_PARAMS"
    assert "degenerate" in degenerate["message"]


def test_create_slab_validates_and_normalizes_boundary_before_rhino():
    from rhinoclaw.tools.visualarq import va_create_slab

    self_intersecting = json.loads(va_create_slab(
        MagicMock(), "Slab", [
            [0, 0, 0], [10, 10, 0], [0, 10, 0], [10, 0, 0],
        ]))
    non_horizontal = json.loads(va_create_slab(
        MagicMock(), "Slab", [
            [0, 0, 0], [10, 0, 0], [10, 10, 1], [0, 10, 0],
        ]))
    bad_alignment = json.loads(va_create_slab(
        MagicMock(), "Slab", [
            [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
        ], alignment="upper"))

    assert self_intersecting["success"] is False
    assert "self-intersecting" in self_intersecting["message"]
    assert non_horizontal["success"] is False
    assert "horizontal" in non_horizontal["message"]
    assert bad_alignment["success"] is False
    assert "alignment" in bad_alignment["message"]


def test_create_space_validates_label_and_height_before_rhino():
    from rhinoclaw.tools.visualarq import va_create_space

    boundary = [[0, 0, 10], [100, 0, 10], [100, 80, 10], [0, 80, 10]]
    outside = json.loads(va_create_space(
        MagicMock(), "Space", boundary, 300, [200, 20, 10]))
    wrong_z = json.loads(va_create_space(
        MagicMock(), "Space", boundary, 300, [50, 40, 0]))
    zero_height = json.loads(va_create_space(
        MagicMock(), "Space", boundary, 0, [50, 40, 10]))

    assert outside["success"] is False
    assert "strictly inside" in outside["message"]
    assert wrong_z["success"] is False
    assert "z must match" in wrong_z["message"]
    assert zero_height["success"] is False
    assert "positive" in zero_height["message"]


def test_create_slab_generates_reflected_verified_creation_contract():
    from rhinoclaw.tools.visualarq import va_create_slab

    object_id = "11111111-2222-3333-4444-555555555555"
    rhino = _rhino({
        "status": "success", "kind": "slab", "object_id": object_id,
        "verification": {"pass": True},
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_slab(
            MagicMock(), "Concrete 250", [
                [0, 0, 3200], [6000, 0, 3200],
                [6000, 4000, 3200], [0, 4000, 3200],
            ], alignment="top"))

    assert data["success"] is True
    assert data["data"]["object_id"] == object_id
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_slab>", "exec")
    params = _params_from_code(code)
    assert params["kind"] == "slab"
    assert params["alignment"] == "top"
    assert params["boundary"][0] == params["boundary"][-1]
    assert 'va_exact_method_shape("AddSlabFromCurve", [' in code
    assert '"VisualARQ.Script+SlabAlignment"' in code
    assert "va_slab_contour_snapshot" in code
    assert '"runtime_generation_matches"' in code
    assert '"top_level_delta_is_exact"' in code
    assert '"PARTIAL_MUTATION"' in code
    assert "cleanup_serial == created_serial" in code


def test_create_space_generates_semantic_verified_creation_contract():
    from rhinoclaw.tools.visualarq import va_create_space

    object_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    rhino = _rhino({
        "status": "success", "kind": "space", "object_id": object_id,
        "verification": {"pass": True},
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_space(
            MagicMock(), "Residential", [
                [0, 0, 0], [5000, 0, 0],
                [5000, 3500, 0], [0, 3500, 0],
            ], 2800, [2500, 1750, 0]))

    assert data["success"] is True
    assert data["data"]["object_id"] == object_id
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_space>", "exec")
    params = _params_from_code(code)
    assert params["kind"] == "space"
    assert params["height"] == 2800.0
    assert params["label_point"] == [2500.0, 1750.0, 0.0]
    assert 'va_exact_method_shape("AddSpaceFromCurve", [' in code
    assert '"SetSpaceHeight"' in code
    assert '"GetSpaceArea"' in code
    assert '"label_position_matches"' in code
    assert "va_horizontal_curve_snapshot" in code


def test_create_door_validates_dimensions_point_and_wall_guid():
    from rhinoclaw.tools.visualarq import va_create_door

    bad_width = json.loads(va_create_door(
        MagicMock(), "T80", point=[0, 0, 0], width=-1))
    bad_point = json.loads(va_create_door(
        MagicMock(), "T80", point=[0, float("nan"), 0]))
    bad_guid = json.loads(va_create_door(
        MagicMock(), "T80", wall_id="not-a-guid", position=100))
    empty_guid = json.loads(va_create_door(
        MagicMock(), "T80",
        wall_id="00000000-0000-0000-0000-000000000000", position=100))
    mixed_modes = json.loads(va_create_door(
        MagicMock(), "T80", point=[0, 0, 0], position=100))

    assert bad_width["code"] == "INVALID_PARAMS"
    assert bad_point["code"] == "INVALID_PARAMS"
    assert bad_guid["code"] == "INVALID_PARAMS"
    assert empty_guid["code"] == "INVALID_PARAMS"
    assert mixed_modes["code"] == "INVALID_PARAMS"
    assert "mutually exclusive" in mixed_modes["message"]
    assert "GUID" in bad_guid["message"]
    assert "empty GUID" in empty_guid["message"]


def test_create_door_scans_all_spatial_hosts_with_explicit_wall_assertion():
    """wall_id asserts the selected host; it never narrows the baseline."""
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "success", "door_id": "guid-d1", "style": "T80",
    })
    wall_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80", point=[2500, 3000, 0], wall_id=wall_id))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_spatial_host_baseline>", "exec")
    assert _params_from_code(code)["wall_id"] == wall_id
    scan = code.index("for candidate_obj in sc.doc.Objects:")
    requested_id_gate = code.index(
        "if requested_wall_id != Guid.Empty and not requested_wall_valid:")
    requested_spatial_gate = code.index("not requested_wall_contains_point:")
    mutation = code.index("returned_door_id = va.AddDoor(")
    assert scan < requested_id_gate < requested_spatial_gate < mutation
    assert "Always scan every active wall" in code
    assert "door_wall_spatial_probe" in code
    assert "spatial_candidate_ids = sorted(wall_states_before)" in code
    assert "candidate_wall_objects = [requested" not in code
    assert '"requested_wall_does_not_contain_point"' in code


def test_create_opening_host_probe_accepts_elevated_windows_planarly():
    """Window sill elevation must not count as wall-path separation."""
    from rhinoclaw.tools.visualarq import va_create_window

    rhino = _rhino({
        "status": "success", "window_id": "guid-w1", "style": "W120",
    })
    wall_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_window(
            MagicMock(), "W120", point=[4200, 0, 900], wall_id=wall_id,
            width=1200, height=1200))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_window_planar_host_probe>", "exec")
    probe = code[code.index("def window_wall_spatial_probe"):
                 code.index("spatial_tolerance =")]
    assert "closest_point.DistanceTo(point)" not in probe
    assert "planar_path_distance" in probe
    assert "vertical_offset_from_path" in probe
    assert "vertical_within_host" in probe
    assert '"path_distance_semantics": "planar_xy"' in probe
    assert "planar_path_distance <= maximum_path_distance" in probe
    assert "bbox.Min.Z - tolerance <= point.Z" in probe


def test_create_door_requires_authoritative_host_in_complete_preadd_baseline():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "success", "door_id": "guid-d1", "style": "T80",
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80", point=[2500, 3000, 0]))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_authoritative_host>", "exec")
    exact_getter = code.index(
        "opening_host_id = va.GetOpeningHost(door_id)")
    baseline_membership = code.index(
        "opening_host_in_preadd_baseline =", exact_getter)
    canonical_host = code.index("host_id = opening_host_id", baseline_membership)
    creation_checks = code.index("creation_checks = {", canonical_host)
    assert exact_getter < baseline_membership < canonical_host < creation_checks
    membership_block = code[baseline_membership:canonical_host]
    assert "opening_host_text is not None" in membership_block
    assert "spatial_host_baseline_complete" in membership_block
    assert "opening_host_text in wall_states_before" in membership_block
    assert '"opening_host_nonempty": opening_host_text is not None' in code
    checks_start = code.index('"spatial_host_baseline_complete":')
    checks_end = code.index('"host_readable":', checks_start)
    checks = code[checks_start:checks_end]
    assert '"opening_host_in_preadd_baseline":' in checks
    assert "opening_host_in_preadd_baseline is True" in checks
    assert "valid_host_ids[0]" not in code
    assert "unique_host_texts[0]" not in code


def test_create_door_empty_guid_is_partial_and_never_recovered_for_cleanup():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "error", "code": "PARTIAL_MUTATION",
        "reason": "adddoor_returned_empty_guid_ownership_unprovable",
        "cleanup_verified": False,
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(
            MagicMock(), "T80", point=[2500, 3000, 0]))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_empty_guid>", "exec")
    empty_result = code.index(
        "if returned_door_id is None or returned_door_id == Guid.Empty:")
    mutation = code.index("returned_door_id = va.AddDoor(")
    assert mutation < empty_result
    assert "adddoor_returned_empty_guid = True" in code[empty_result:]
    assert "adddoor_returned_empty_guid_ownership_unprovable" in code
    empty_cleanup = code.index("if adddoor_returned_empty_guid:")
    next_cleanup_branch = code.index(
        "elif cleanup_target_id != Guid.Empty", empty_cleanup)
    cleanup_block = code[empty_cleanup:next_cleanup_branch]
    assert 'cleanup_target_id = Guid(candidates[0]["id"])' not in cleanup_block
    assert 'cleanup_target_serial = candidates[0]["runtime_serial_number"]' \
        not in cleanup_block
    assert "va.IsDoor(Guid.Empty)" not in code
    squashed = "".join(code.replace("\\", "").split())
    assert (
        "cleanup_verified=cleanup_verifiedand"
        "host_cleanup_verifiedisTrueandnotadddoor_returned_empty_guid"
    ) in squashed


def test_door_host_definition_fingerprint_covers_every_leaf_and_full_path():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "success", "door_id": "guid-d1", "style": "T80",
    })
    with patch(PATCH, return_value=rhino):
        va_create_door(MagicMock(), "T80", point=[2500, 3000, 0])

    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_definition_fingerprint>", "exec")
    leaf_fingerprint = code.index("record_fingerprint_leaf(")
    volume_type_switch = code.index("if isinstance(geometry, rg.Brep):")
    assert leaf_fingerprint < volume_type_switch
    assert "geometry.DataCRC(System.UInt32(0))" in code
    assert "transform.ToDoubleArray(True)" in code
    assert "len(normalized) != 16" in code
    assert '"instance_path": list(instance_path)' in code
    assert '"attributes": va_object_attributes_fingerprint(leaf.Attributes)' \
        in code
    assert '"attributes": va_object_attributes_fingerprint(' in code
    assert '"user_strings": user_strings' in code
    assert "fingerprint_leaves.sort(" in code
    assert "if len(fingerprint_leaves) <" not in code
    assert '"canonical_leaves": fingerprint_leaves' in code


def test_door_host_cleanup_matches_exact_fingerprint_not_volume_or_outer_crc():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "success", "door_id": "guid-d1", "style": "T80",
    })
    with patch(PATCH, return_value=rhino):
        va_create_door(MagicMock(), "T80", point=[2500, 3000, 0])

    code = rhino.send_command.call_args[0][1]["code"]
    matcher_start = code.index("def door_host_wall_state_matches(")
    matcher_end = code.index("wall_states_before = {}", matcher_start)
    matcher = code[matcher_start:matcher_end]
    assert "va_instance_definition_fingerprints_match(" in matcher
    assert "definition_fingerprint" in matcher
    assert "volume" not in matcher
    assert "geometry_crc" not in matcher
    host_cut_start = code.index("host_cut_verified =")
    host_cut_end = code.index("post_readback_obj =", host_cut_start)
    host_cut = code[host_cut_start:host_cut_end]
    assert "host_semantics_stable and host_definition_changed" in \
        host_cut.replace("\\\n", "")
    assert "host_cut_volume_delta" not in host_cut


def test_unbaselined_actual_door_host_forces_partial_cleanup():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({
        "status": "error", "code": "PARTIAL_MUTATION",
        "cleanup_host_was_in_preadd_baseline": False,
        "cleanup_verified": False,
    })
    with patch(PATCH, return_value=rhino):
        va_create_door(MagicMock(), "T80", point=[2500, 3000, 0])

    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_unbaselined_host_cleanup>", "exec")
    assert "cleanup_host_was_in_preadd_baseline = \\\n" in code
    assert "cleanup_host_id in wall_states_before" in code
    cleanup_gate = code.index("host_cleanup_verified = bool(")
    final_gate = code.index(
        "cleanup_verified = cleanup_verified and", cleanup_gate)
    gate = code[cleanup_gate:final_gate]
    assert 'item["state_matches"] for item in host_cleanup_results' in gate
    assert "spatial_host_baseline_complete" in gate
    assert "cleanup_host_was_in_preadd_baseline" in gate


def test_style_error_passes_message_through():
    from rhinoclaw.tools.visualarq import va_create_door

    rhino = _rhino({"status": "error", "message": "Door style not found: X"})
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door(MagicMock(), "X", point=[0, 0, 0]))

    assert data["success"] is False
    assert "not found" in data["message"]


def test_hierarchy_list_tools_expose_owner_and_scope_contracts():
    from rhinoclaw.tools.visualarq import va_list_buildings, va_list_levels

    verification = {
        "pass": True,
        "inventory_scope": "building_reachable",
        "global_level_inventory_available": False,
        "mutation_baseline_complete": False,
    }
    rhino = _rhino({
        "status": "success", "buildings": [],
        "building_count": 0, "level_count": 0,
        "verification": verification,
    })
    with patch(PATCH, return_value=rhino):
        buildings = json.loads(va_list_buildings(MagicMock()))
    building_code = rhino.send_command.call_args[0][1]["code"]

    rhino = _rhino({
        "status": "success", "levels": [], "level_count": 0,
        "building_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "buildings": [], "verification": verification,
    })
    with patch(PATCH, return_value=rhino):
        levels = json.loads(va_list_levels(
            MagicMock(), "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"))
    level_code = rhino.send_command.call_args[0][1]["code"]

    assert buildings["success"] is True
    assert levels["success"] is True
    assert _params_from_code(level_code)["building_id"] == \
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    for code in (building_code, level_code):
        compile(code, "<va_hierarchy_list>", "exec")
        assert "def va_hierarchy_snapshot():" in code
        assert '"inventory_scope": "global"' in code
        assert 'else "building_reachable"' in code
        assert '"mutation_baseline_complete"' in code
        assert '"duplicate_owner_level_ids"' in code
        assert '"owner_conflicts"' in code
        assert "GetLevelBuidlingId" in code
        assert "GetLevelCutElevation" in code
        assert '"unavailable_state_fields"' in code
        assert 'level_error("GetLevelCutElevation"' in code


def test_add_building_embeds_exact_hierarchy_delta_and_cleanup_contract():
    from rhinoclaw.tools.visualarq import va_add_building

    rhino = _rhino({
        "status": "success",
        "building_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_add_building(MagicMock(), " Haus A ", 15.0))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_add_building>", "exec")
    assert _params_from_code(code) == {"name": "Haus A", "elevation": 15.0}
    assert (
        '"AddBuilding", ["System.String", "System.Double"]' in code
    )
    assert (
        '"DeleteBuilding", ["System.Guid"], "System.Boolean"' in code
    )
    assert '"exact_building_delta"' in code
    assert 'delta["added_building_ids"] == [str(building_id)]' in code
    assert '"no_level_delta"' in code
    assert '"no_membership_delta"' in code
    assert '"reason": "global_level_inventory_unavailable"' not in code
    assert '"inventory_scope":' in code
    assert '"orphan_check_available":' in code
    assert "va.DeleteBuilding(building_id)" in code
    assert 'not cleanup_delta["mutation_detected"]' in code
    assert "cleanup_classified_as_building is False" in code


def test_add_level_canonicalizes_params_and_embeds_atomic_contracts():
    from rhinoclaw.tools.visualarq import va_add_level

    rhino = _rhino({
        "status": "success", "level_id": "guid-l1",
        "requested": {
            "name": "EG", "elevation": 0.0,
            "building_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        },
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_add_level(
            MagicMock(), "  EG  ", 0,
            building_id="{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}",
        ))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_add_level>", "exec")
    params = _params_from_code(code)
    assert params == {
        "name": "EG", "elevation": 0.0,
        "building_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    }

    first_add_level = code.index("level_id = va.AddLevel(")
    assert 'add_shape = va_exact_method_shape(' in code
    assert (
        '"AddLevel", ["System.Guid", "System.String", "System.Double"]'
        in code
    )
    assert (
        '"DeleteLevel", ["System.Guid"], "System.Boolean"' in code
    )
    assert "before = va_hierarchy_snapshot()" in code
    assert 'requested_building_id = params["building_id"]' in code
    assert 'requested_building_id not in before_building_ids' in code
    assert "va.AddBuilding" not in code
    creation_error_handler = code.index("except Exception as creation_error:")
    for readback_contract in (
        '"exact_level_delta"',
        'delta["added_level_ids"] == [str(level_id)]',
        '"exact_membership_delta"',
        'actual["owner_verified"]',
        'actual["owner_building_id"] == requested_building_id',
    ):
        assert readback_contract in code
        assert code.index(readback_contract) < creation_error_handler
    assert first_add_level < code.index("after = va_hierarchy_snapshot()")
    assert "va.DeleteLevel(level_id)" in code
    assert '"guid_freshness_scope":' in code
    assert '"global_guid_freshness_verified":' in code
    assert 'after["verification"]["inventory_scope"] == "global"' in code
    assert '"cleanup_hierarchy_delta"' in code
    assert "cleanup_classified_as_level is False" in code
    assert 'else "PARTIAL_MUTATION"' in code
    assert "level_id != Guid.Empty" in code
    assert 'delta["added_level_ids"] == [returned_id]' in code
    assert 'delta["added_membership_edges"] == [expected_edge]' in code


def test_partial_mutation_and_replacement_evidence_pass_through_api():
    from rhinoclaw.tools.visualarq import va_add_level, va_create_door

    door_failure = {
        "status": "error", "code": "PARTIAL_MUTATION",
        "message": "Door was replaced; cleanup refused",
        "door_id": "11111111-1111-1111-1111-111111111111",
        "created_runtime_serial_number": 101,
        "final_runtime_serial_number": 202,
        "cleanup_actual_runtime_serial_number": 202,
        "cleanup_runtime_serial_matches": False,
        "replacement_detected": True,
        "cleanup_deleted": False,
        "cleanup_verified": False,
    }
    with patch(PATCH, return_value=_rhino(door_failure)):
        door = json.loads(va_create_door(
            MagicMock(), "T80", point=[0, 0, 0]))

    assert door["success"] is False
    assert door["code"] == "PARTIAL_MUTATION"
    assert door["data"]["door_id"] == door_failure["door_id"]
    assert door["data"]["replacement_detected"] is True
    assert door["data"]["cleanup_runtime_serial_matches"] is False
    assert door["data"]["cleanup_verified"] is False

    level_failure = {
        "status": "error", "code": "PARTIAL_MUTATION",
        "message": "Level cleanup could not be verified",
        "level_id": "22222222-2222-2222-2222-222222222222",
        "created_building_id": "33333333-3333-3333-3333-333333333333",
        "cleanup_level_verified": False,
        "cleanup_building_verified": False,
        "cleanup_verified": False,
    }
    with patch(PATCH, return_value=_rhino(level_failure)):
        level = json.loads(va_add_level(
            MagicMock(), "EG", 0,
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ))

    assert level["success"] is False
    assert level["code"] == "PARTIAL_MUTATION"
    assert level["data"]["level_id"] == level_failure["level_id"]
    assert level["data"]["created_building_id"] == \
        level_failure["created_building_id"]
    assert level["data"]["cleanup_verified"] is False


def test_list_styles_validates_kind():
    from rhinoclaw.tools.visualarq import va_list_styles

    data = json.loads(va_list_styles(MagicMock(), kind="roof"))
    assert data["success"] is False


def test_ifc_export_requires_ifc_extension():
    from rhinoclaw.tools.visualarq import va_ifc_export

    data = json.loads(va_ifc_export(MagicMock(), "C:/x/model.step"))
    assert data["success"] is False


def test_ifc_export_success():
    from rhinoclaw.tools.visualarq import va_ifc_export

    rhino = _rhino({
        "status": "success", "path": "C:/x/m.ifc",
        "target_path": "C:/x/m.ifc",
        "requested_schema": "IFC4", "actual_schema": "IFC2X3",
        "schema_request_honored": False,
        "warnings": [
            "Requested schema IFC4 was not honored; exporter wrote IFC2X3",
        ],
        "file_exists": True, "file_size": 12345, "header_valid": True,
        "fresh_artifact_verified": True,
        "staged_artifact_validated": True,
        "published": True, "publication_mode": "replace",
        "sha256": "a" * 64,
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_ifc_export(MagicMock(), "C:/x/m.ifc"))

    assert data["success"] is True
    assert data["data"]["requested_schema"] == "IFC4"
    assert data["data"]["actual_schema"] == "IFC2X3"
    assert data["data"]["schema_request_honored"] is False
    assert data["data"]["fresh_artifact_verified"] is True
    assert data["data"]["staged_artifact_validated"] is True
    assert data["data"]["published"] is True
    assert data["data"]["publication_mode"] == "replace"
    assert data["data"]["sha256"] == "a" * 64
    assert "not honored" in data["data"]["warnings"][0]
    assert "actual schema IFC2X3" in data["message"]
    assert "requested IFC4" in data["message"]
    assert "version" not in data["data"]


def test_ifc_export_validates_schema_and_generated_script_checks_file():
    from rhinoclaw.tools.visualarq import va_ifc_export

    invalid = json.loads(va_ifc_export(
        MagicMock(), "C:/x/m.ifc", version="IFC5"))
    assert invalid["success"] is False
    assert invalid["code"] == "INVALID_PARAMS"

    rhino = _rhino({
        "status": "error",
        "message": "IFC exporter returned success but output validation failed",
        "file_exists": False, "file_size": 0, "header_valid": False,
        "actual_schema": None,
    })
    with patch(PATCH, return_value=rhino):
        failed = json.loads(va_ifc_export(MagicMock(), "C:/x/m.ifc"))

    assert failed["success"] is False
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_ifc_export>", "exec")
    assert "FileInfo" in code
    assert "ISO-10303-21;" in code
    assert "FILE_SCHEMA" in code


def test_ifc_export_stages_validates_hashes_and_publishes_atomically():
    from rhinoclaw.tools.visualarq import va_ifc_export

    rhino = _rhino({
        "status": "error", "code": "PARTIAL_MUTATION",
        "message": "IFC publication failed after target mutation",
        "path": "C:/x/m.ifc", "target_path": "C:/x/m.ifc",
        "staging_path": "C:/x/.m.rhinoclaw-unique.ifc",
        "staged_validation": {
            "file_exists": True, "file_size": 12345,
            "header_valid": True, "actual_schema": "IFC4", "valid": True,
        },
        "staged_artifact_validated": True,
        "publication_attempted": True,
        "publication_mode": "replace",
        "staged_was_published": False,
        "target_preserved": False,
        "temp_cleanup_verified": True,
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_ifc_export(MagicMock(), "C:/x/m.ifc"))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    assert data["data"]["staged_artifact_validated"] is True
    assert data["data"]["publication_attempted"] is True
    assert data["data"]["target_preserved"] is False
    assert data["data"]["temp_cleanup_verified"] is True

    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_ifc_export_atomic_publish>", "exec")
    assert "from System.Security.Cryptography import SHA256" in code
    assert "directory = Path.GetDirectoryName(target_path)" in code
    assert "temp_path = Path.Combine(" in code
    assert 'Guid.NewGuid().ToString("N")' in code
    assert '".rhinoclaw-"' in code
    assert '".ifc")' in code
    assert "backup_path = Path.Combine(" in code
    assert "recovery_path = Path.Combine(" in code
    assert "File.Exists(temp_path) or File.Exists(backup_path)" in code
    assert "Unique IFC transaction path already exists" in code
    assert "def va_file_evidence(file_path):" in code
    assert "def va_same_file_state(left, right):" in code

    export_to_temp = code.index(
        'export_success = va.ExportIFC(temp_path, params["version"])')
    fallback_to_temp = code.index(
        "export_success = sc.doc.WriteFile(temp_path, opts)")
    validate_temp = code.index("staged_validation = validate_ifc(")
    hash_temp = code.index("staged_hash = file_sha256(temp_path)")
    prepublication = code.index(
        "target_prepublication = va_file_evidence(target_path)")
    compare_and_swap = code.index(
        "va_same_file_state(target_before, target_prepublication)")
    replace_target = code.index(
        "File.Replace(temp_path, target_path, backup_path)")
    move_target = code.index("File.Move(temp_path, target_path)")
    validate_target = code.index(
        "published_validation = validate_ifc(")
    verify_backup = code.index(
        "backup_evidence = va_file_evidence(backup_path)")
    cleanup_backup = code.index("File.Delete(backup_path)")
    assert export_to_temp < validate_temp < hash_temp < prepublication
    assert fallback_to_temp < validate_temp < hash_temp < prepublication
    assert prepublication < compare_and_swap < replace_target
    assert prepublication < compare_and_swap < move_target
    assert replace_target < validate_target
    assert move_target < validate_target
    assert validate_target < verify_backup < cleanup_backup
    assert "File.Replace(temp_path, target_path, None)" not in code
    assert "va.ExportIFC(target_path" not in code
    assert "sc.doc.WriteFile(target_path" not in code

    cleanup_temp = code.index("File.Delete(temp_path)")
    cleanup_proof = code.index(
        'temp_cleanup_verified = temp_evidence["read_complete"] is True')
    assert validate_target < cleanup_temp < cleanup_proof
    assert "publication_may_have_mutated" in code
    assert "target_preserved is not True" in code
    assert "File.Replace(backup_path, target_path, recovery_path)" in code
    assert "File.Move(target_path, recovery_path)" in code
    assert '"rollback_refused_reason"' in code
    export_catch = code[code.index("except Exception as export_error:"):]
    assert "file_sha256(" not in export_catch
    assert '"staging_path": temp_path' in code
    assert '"backup_path": backup_path' in code
    assert '"recovery_path": recovery_path' in code
    assert '"staged_validation": staged_validation' in code
    assert '"temp_cleanup_verified": temp_cleanup_verified' in code
    assert 'normalized[0] == "ISO-10303-21;"' in code
    assert 'normalized[1] == "HEADER;"' in code
    assert 'normalized.count("DATA;") == 1' in code
    assert 'final_marker = "END-ISO-10303-21;"' in code
    assert 'counts.get("IFCPROJECT", 0)' in code
    assert 'inventory["project_count"] == 1' in code
    assert "def step_references(statement):" in code
    assert "if not in_string and character == \"#\":" in code
    assert "step_entity_inventory(data_statements, actual_schema)" in code
    assert "max_validation_bytes = 536870912" in code
    assert "if exists and size > 0 and size_within_limit:" in code
    assert '"file_size_within_limit": size_within_limit' in code
    assert '"IFC4_ADD2_TC1"' in code
    assert '"IFC4X3_ADD2"' in code
    assert "def step_header_inventory(header_statements):" in code
    assert 'names[:3] != required_names' in code
    assert 'schema_supported = actual_schema in supported_schemas' in code
    assert 'entity["type"] == "IFCRELASSOCIATESMATERIAL"' in code
    assert 'entity["type"] == "IFCRELDEFINESBYTYPE"' in code
    assert "valid_layer_set_ids" in code
    assert "valid_layer_usage_ids" in code
    assert "layered_material_wall_targets" in code
    assert "layered_material_wall_type_targets" in code
    assert "duplicate_entity_ids.add(entity_id)" in code
    assert 'not inventory["duplicate_entity_ids"]' in code
    assert "wall_material_association_counts" in code
    assert "occurrence_association_count == 1" in code
    assert "occurrence_association_count == 0" in code
    assert "type_association_count == 1" in code
    assert '"wall_material_layer_association_pass"' in code
    params = _params_from_code(code)
    assert params["require_wall_material_layers"] is False


def test_ifc_export_strict_wall_material_gate_is_explicit_and_typed():
    from rhinoclaw.tools.visualarq import va_ifc_export

    rhino = _rhino({
        "status": "error", "code": "RHINO_ERROR",
        "message": "staged output validation failed",
        "staged_validation": {
            "valid": False,
            "complete_step_structure": True,
            "wall_count": 1,
            "wall_material_layer_association_pass": False,
            "wall_material_layers_required": True,
        },
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_ifc_export(
            MagicMock(), "C:/x/layered.ifc",
            require_wall_material_layers=True,
        ))

    assert data["success"] is False
    code = rhino.send_command.call_args[0][1]["code"]
    params = _params_from_code(code)
    assert params["require_wall_material_layers"] is True
    assert "not require_wall_material_layers or" in code

    invalid = json.loads(va_ifc_export(
        MagicMock(), "C:/x/layered.ifc",
        require_wall_material_layers="yes",  # type: ignore[arg-type]
    ))
    assert invalid["success"] is False
    assert invalid["code"] == "INVALID_PARAMS"


def test_ifc_import_requires_ifc_extension_before_connecting():
    from rhinoclaw.tools.visualarq import va_ifc_import

    with patch(PATCH) as connection:
        data = json.loads(va_ifc_import(MagicMock(), "C:/model.step"))

    assert data["success"] is False
    assert data["code"] == "INVALID_PARAMS"
    connection.assert_not_called()


def test_ifc_import_is_prevalidated_exact_and_inventory_verified():
    from rhinoclaw.tools.visualarq import va_ifc_import

    rhino = _rhino({
        "status": "success",
        "path": "C:/model.ifc",
        "source_sha256": "abc",
        "import_returned": True,
        "mutation_detected": True,
        "automatic_cleanup_attempted": False,
        "undo_recommended": False,
        "delta": {
            "additive": True,
            "verified_visualarq_addition": True,
        },
        "verification": {"pass": True, "additive": True},
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_ifc_import(
            MagicMock(), " C:/model.ifc "))

    assert data["success"] is True
    assert data["data"]["verification"]["pass"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_ifc_import>", "exec")
    params = _params_from_code(code)
    assert params["path"] == "C:/model.ifc"
    assert '"ImportIFC", ["System.String"], "System.Boolean"' in code
    assert "sc.doc.Import" not in code
    assert "validate_ifc(staging_path, False)" in code
    assert "validate_ifc(source_path, False)" not in code
    assert "va.ImportIFC(staging_path)" in code
    assert "va.ImportIFC(source_path)" not in code
    assert "FileMode.Open, FileAccess.Read, FileShare.Read" in code
    assert "File.Copy(source_path, staging_path, False)" in code
    assert "file_sha256(source_path)" in code
    assert "file_sha256(staging_path)" in code
    assert '"source_copy_verified": source_copy_verified' in code
    assert "va_ifc_import_object_inventory" in code
    assert "va_ifc_import_style_inventory" in code
    assert 'name.endswith("StyleIds")' in code
    assert "va_hierarchy_snapshot()" in code
    assert 'get("mutation_baseline_complete") is True' in code
    assert '"automatic_cleanup_attempted": False' in code

    existence = code.index("if not File.Exists(source_path):")
    shape = code.index("import_shape = va_exact_method_shape(")
    source_guard = code.index("source_guard = File.Open(")
    copy = code.index("File.Copy(source_path, staging_path, False)")
    stage_guard = code.index("stage_guard = File.Open(")
    validate = code.index("source_validation = validate_ifc")
    baseline = code.index("before = va_ifc_import_snapshot()")
    mutation = code.index("import_returned = bool(va.ImportIFC(staging_path))")
    readback = code.index("after = va_ifc_import_snapshot()")
    delta = code.index("delta = va_ifc_import_delta(before, after)")
    close_stage = code.index("stage_guard.Close()")
    delete_stage = code.index("File.Delete(staging_path)")
    assert existence < shape < source_guard < copy < stage_guard
    assert stage_guard < validate < baseline < mutation < readback < delta
    assert delta < close_stage < delete_stage
    assert 'mutation_detected = delta["mutation_detected"]' in code
    assert "if delta is not None else None" in code
    assert '"undo_recommended": mutation_detected is not False' in code
    assert '"post_snapshot_error": post_snapshot_error' in code
    assert '"delta_error": delta_error' in code
    assert '"staging_cleanup_verified"' in code


def test_ifc_import_preserves_partial_mutation_error_and_undo_evidence():
    from rhinoclaw.tools.visualarq import va_ifc_import

    with patch(PATCH, return_value=_rhino({
        "status": "error",
        "code": "PARTIAL_MUTATION",
        "message": "changed but not verified",
        "mutation_attempted": True,
        "mutation_detected": True,
        "automatic_cleanup_attempted": False,
        "undo_recommended": True,
        "delta": {"additive": False},
    })):
        data = json.loads(va_ifc_import(MagicMock(), "C:/model.ifc"))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    assert data["data"]["mutation_detected"] is True
    assert data["data"]["automatic_cleanup_attempted"] is False
    assert data["data"]["undo_recommended"] is True


def test_ifc_import_preserves_unknown_mutation_state_after_readback_failure():
    from rhinoclaw.tools.visualarq import va_ifc_import

    with patch(PATCH, return_value=_rhino({
        "status": "error",
        "code": "PARTIAL_MUTATION",
        "message": "post snapshot failed",
        "mutation_attempted": True,
        "mutation_detected": None,
        "post_snapshot_error": "readback exploded",
        "before": {"read_complete": True},
        "import_returned": True,
        "automatic_cleanup_attempted": False,
        "undo_recommended": True,
    })):
        data = json.loads(va_ifc_import(MagicMock(), "C:/model.ifc"))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    assert data["data"]["mutation_detected"] is None
    assert data["data"]["post_snapshot_error"] == "readback exploded"
    assert data["data"]["before"]["read_complete"] is True
    assert data["data"]["undo_recommended"] is True


def test_ifc_parser_rejects_unbalanced_entity_statement():
    parser = _ifc_parser_functions()
    statements, lexical_complete = parser["step_statements"](
        "#1=IFCPROJECT(;"
    )

    inventory = parser["step_entity_inventory"](statements)

    assert lexical_complete is True
    assert inventory["project_count"] == 0
    assert inventory["invalid_entity_statements"]


def test_ifc_header_requires_complete_ordered_entities_and_known_schema():
    parser = _ifc_parser_functions()
    validate_header = parser["step_header_inventory"]

    valid = validate_header(_valid_ifc_header_statements())
    assert valid["valid"] is True
    assert valid["actual_schema"] == "IFC4"

    only_schema = validate_header(["FILE_SCHEMA(('IFC4'));"])
    disguised = validate_header([
        *_valid_ifc_header_statements()[:2],
        "SOMETHING(FILE_SCHEMA(('IFC4')));",
    ])
    bogus = validate_header(_valid_ifc_header_statements("IFC4_BOGUS"))
    multiple = validate_header([
        *_valid_ifc_header_statements()[:2],
        "FILE_SCHEMA(('IFC4','IFC2X3'));",
    ])

    assert only_schema["valid"] is False
    assert disguised["valid"] is False
    assert bogus["valid"] is False
    assert bogus["schema_supported"] is False
    assert multiple["valid"] is False


def test_ifc_parser_rejects_garbage_statement_in_data():
    parser = _ifc_parser_functions()

    inventory = parser["step_entity_inventory"](
        ["GARBAGE;"] + _valid_ifc_project_statements()
    )

    assert inventory["valid_project_count"] == 1
    assert inventory["unrecognized_data_statements"] == [{
        "index": 0, "excerpt": "GARBAGE;",
    }]


def test_ifc_parser_rejects_dangling_entity_references():
    parser = _ifc_parser_functions()
    statements = _valid_ifc_project_statements()
    statements[0] = statements[0].replace("#3);", "#999);")

    inventory = parser["step_entity_inventory"](statements)

    assert inventory["dangling_reference_ids"] == ["#999"]


def test_ifc_parser_rejects_duplicate_targeted_ifcroot_global_ids():
    parser = _ifc_parser_functions()
    duplicated_global_id = "0000000000000000000000"
    statements = [
        (
            "#1=IFCPROJECT('" + duplicated_global_id + "',$,'Project',"
            "$,$,$,$,$,$);"
        ),
        "#10=IFCMATERIALLAYER($,200.,$,$,$,$,$);",
        "#11=IFCMATERIALLAYERSET((#10),'Set',$);",
        "#12=IFCMATERIALLAYERSETUSAGE(#11,.AXIS2.,.POSITIVE.,0.,$);",
        (
            "#20=IFCWALL('" + duplicated_global_id +
            "',$,$,$,$,$,$,$,$);"
        ),
        (
            "#21=IFCRELASSOCIATESMATERIAL('" + duplicated_global_id +
            "',$,$,$,(#20),#12);"
        ),
    ]

    inventory = parser["step_entity_inventory"](statements, "IFC4")

    assert inventory["duplicate_entity_ids"] == []
    assert inventory["duplicate_global_ids"] == [{
        "global_id": duplicated_global_id,
        "entity_ids": ["#1", "#20", "#21"],
    }]
    assert set(inventory["invalid_semantic_entity_ids"]) == {
        "#1", "#20", "#21",
    }


def test_ifc_parser_rejects_global_id_outside_128_bit_encoding_domain():
    parser = _ifc_parser_functions()

    assert parser["valid_ifc_global_id"](
        "'3zzzzzzzzzzzzzzzzzzzzz'") is True
    assert parser["valid_ifc_global_id"](
        "'4zzzzzzzzzzzzzzzzzzzzz'") is False
    inventory = parser["step_entity_inventory"]([
        "#1=IFCPROJECT('4zzzzzzzzzzzzzzzzzzzzz',$,'Project',"
        "$,$,$,$,$,$);",
    ], "IFC4")
    assert inventory["valid_project_count"] == 0
    assert inventory["invalid_semantic_entity_ids"] == ["#1"]


def test_ifc_parser_rejects_ambiguous_wall_type_even_with_direct_material():
    parser = _ifc_parser_functions()
    statements = [
        "#10=IFCMATERIALLAYER($,200.,$,$,$,$,$);",
        "#11=IFCMATERIALLAYERSET((#10),'Set',$);",
        "#12=IFCMATERIALLAYERSETUSAGE(#11,.AXIS2.,.POSITIVE.,0.,$);",
        (
            "#20=IFCWALL('0000000000000000000020',$,$,$,$,$,$,$,$);"
        ),
        (
            "#30=IFCWALLTYPE('0000000000000000000030',$,$,$,$,$,$,$,$,"
            ".NOTDEFINED.);"
        ),
        (
            "#31=IFCWALLTYPE('0000000000000000000031',$,$,$,$,$,$,$,$,"
            ".NOTDEFINED.);"
        ),
        (
            "#40=IFCRELDEFINESBYTYPE("
            "'0000000000000000000040',$,$,$,(#20),#30);"
        ),
        (
            "#41=IFCRELDEFINESBYTYPE("
            "'0000000000000000000041',$,$,$,(#20),#31);"
        ),
        (
            "#42=IFCRELASSOCIATESMATERIAL("
            "'0000000000000000000042',$,$,$,(#20),#12);"
        ),
    ]

    inventory = parser["step_entity_inventory"](statements, "IFC4")

    assert inventory["ambiguous_wall_type_ids"] == ["#20"]
    assert inventory["unassociated_wall_ids"] == []
    assert inventory["wall_material_layer_association_pass"] is False
    assert "#20" in inventory["invalid_semantic_entity_ids"]


def test_ifc_parser_rejects_wall_type_relation_to_non_wall_type():
    parser = _ifc_parser_functions()
    statements = [
        "#10=IFCMATERIALLAYER($,200.,$,$,$,$,$);",
        "#11=IFCMATERIALLAYERSET((#10),'Set',$);",
        "#12=IFCMATERIALLAYERSETUSAGE(#11,.AXIS2.,.POSITIVE.,0.,$);",
        "#20=IFCWALL('0000000000000000000020',$,$,$,$,$,$,$,$);",
        (
            "#40=IFCRELDEFINESBYTYPE("
            "'0000000000000000000040',$,$,$,(#20),#11);"
        ),
        (
            "#41=IFCRELASSOCIATESMATERIAL("
            "'0000000000000000000041',$,$,$,(#20),#12);"
        ),
    ]

    inventory = parser["step_entity_inventory"](statements, "IFC4")

    assert inventory["invalid_wall_type_target_ids"] == ["#20"]
    assert inventory["wall_material_layer_association_pass"] is False
    assert {"#20", "#40"}.issubset(
        set(inventory["invalid_semantic_entity_ids"])
    )


def test_ifc_parser_does_not_join_tokens_across_comments():
    parser = _ifc_parser_functions()
    content = (
        "#1=IFC/* a removed comment must leave a separator */PROJECT("
        "'0000000000000000000000',$,$,$,$,$,$,(#2),#3);"
    )

    statements, lexical_complete = parser["step_statements"](content)
    inventory = parser["step_entity_inventory"](statements)

    assert lexical_complete is True
    assert "IFC PROJECT" in statements[0].upper()
    assert inventory["project_count"] == 0
    assert inventory["unrecognized_data_statements"]


def test_ifc_parser_requires_every_layer_set_member_to_be_a_layer():
    parser = _ifc_parser_functions()
    statements = [
        "#10=IFCMATERIALLAYER($,0.2,$);",
        "#11=IFCMATERIALLAYERSET((#10,#999),'Mixed layer set',$);",
    ]

    inventory = parser["step_entity_inventory"](statements)

    assert inventory["material_layer_set_count"] == 1
    assert inventory["valid_material_layer_set_count"] == 0
    assert inventory["dangling_reference_ids"] == ["#999"]


def test_ifc_parser_rejects_semantically_invalid_ifc_project():
    parser = _ifc_parser_functions()
    statements = [
        (
            "#1=IFCPROJECT('0000000000000000000000',$,$,"
            "$,$,$,$,$,$);"
        ),
    ]

    inventory = parser["step_entity_inventory"](statements)

    assert inventory["project_count"] == 1
    assert inventory["valid_project_count"] == 0
    assert "#1" in inventory["invalid_semantic_entity_ids"]


def test_ifc_project_optional_contexts_follow_declared_schema():
    parser = _ifc_parser_functions()
    statement = (
        "#1=IFCPROJECT('0000000000000000000000',$,'Named project',"
        "$,$,$,$,$,$);"
    )

    ifc4 = parser["step_entity_inventory"]([statement], "IFC4")
    ifc2x3 = parser["step_entity_inventory"]([statement], "IFC2X3")

    assert ifc4["valid_project_count"] == 1
    assert ifc4["invalid_semantic_entity_ids"] == []
    assert ifc2x3["valid_project_count"] == 0
    assert ifc2x3["invalid_semantic_entity_ids"] == ["#1"]


def test_ifc_parser_requires_exact_schema_specific_entity_arities():
    parser = _ifc_parser_functions()
    ifc4 = parser["step_entity_inventory"]([
        "#10=IFCMATERIALLAYER($,0.2,$,$,$,$,$);",
        "#11=IFCMATERIALLAYERSET((#10),'Set',$);",
        "#12=IFCMATERIALLAYERSETUSAGE(#11,.AXIS2.,.POSITIVE.,0.,$);",
        (
            "#20=IFCWALL('1111111111111111111111',$,$,$,$,$,$,$,$);"
        ),
        (
            "#21=IFCWALLTYPE('2222222222222222222222',$,$,$,$,$,$,$,$,"
            ".NOTDEFINED.);"
        ),
    ], "IFC4")
    assert ifc4["invalid_semantic_entity_ids"] == []
    assert ifc4["valid_material_layer_set_count"] == 1
    assert ifc4["valid_material_layer_set_usage_count"] == 1

    malformed_ifc4 = parser["step_entity_inventory"]([
        "#30=IFCMATERIALLAYER($,0.2,$,$,$,$,$,$);",
        "#31=IFCMATERIALLAYERSET((#30),'Set',$,$);",
        "#32=IFCMATERIALLAYERSETUSAGE(#31,.AXIS2.,.POSITIVE.,0.,$,123);",
        "#33=IFCWALL('3333333333333333333333',$,$,$,$,$,$,$);",
    ], "IFC4")
    assert set(malformed_ifc4["invalid_semantic_entity_ids"]) == {
        "#30", "#31", "#32", "#33",
    }
    assert malformed_ifc4["valid_material_layer_set_count"] == 0
    assert malformed_ifc4["valid_material_layer_set_usage_count"] == 0

    ifc2x3 = parser["step_entity_inventory"]([
        "#40=IFCMATERIALLAYER($,0.2,$);",
        "#41=IFCMATERIALLAYERSET((#40),'Set');",
        "#42=IFCMATERIALLAYERSETUSAGE(#41,.AXIS2.,.POSITIVE.,0.);",
        "#43=IFCWALL('3444444444444444444444',$,$,$,$,$,$,$);",
    ], "IFC2X3")
    assert ifc2x3["invalid_semantic_entity_ids"] == []
    assert ifc2x3["valid_material_layer_set_count"] == 1
    assert ifc2x3["valid_material_layer_set_usage_count"] == 1


def test_ifc_parser_rejects_invalid_layer_values_and_wall_usage_axis():
    parser = _ifc_parser_functions()
    invalid_values = ["-200.", "'oops'", ".NAN.", "$"]
    for thickness in invalid_values:
        inventory = parser["step_entity_inventory"]([
            "#10=IFCMATERIALLAYER($," + thickness + ",$,$,$,$,$);",
            "#11=IFCMATERIALLAYERSET((#10),'Set',$);",
            (
                "#12=IFCMATERIALLAYERSETUSAGE("
                "#11,.AXIS2.,.POSITIVE.,0.,$);"
            ),
        ], "IFC4")
        assert "#10" in inventory["invalid_semantic_entity_ids"]
        assert inventory["valid_material_layer_set_count"] == 0
        assert inventory["valid_material_layer_set_usage_count"] == 0

    bad_usage = parser["step_entity_inventory"]([
        "#20=IFCMATERIALLAYER($,200.,$,$,$,$,$);",
        "#21=IFCMATERIALLAYERSET((#20),'Set',$);",
        "#22=IFCMATERIALLAYERSETUSAGE(#21,.BOGUS.,.WRONG.,0.,$);",
    ], "IFC4")
    assert "#22" in bad_usage["invalid_semantic_entity_ids"]
    assert bad_usage["valid_material_layer_set_usage_count"] == 0

    axis3_wall = parser["step_entity_inventory"]([
        "#30=IFCMATERIALLAYER($,200.,$,$,$,$,$);",
        "#31=IFCMATERIALLAYERSET((#30),'Set',$);",
        "#32=IFCMATERIALLAYERSETUSAGE(#31,.AXIS3.,.POSITIVE.,0.,$);",
        "#33=IFCWALL('3333333333333333333333',$,$,$,$,$,$,$,$);",
        (
            "#34=IFCRELASSOCIATESMATERIAL("
            "'2444444444444444444444',$,$,$,(#33),#32);"
        ),
    ], "IFC4")
    assert axis3_wall["invalid_semantic_entity_ids"] == []
    assert axis3_wall["valid_material_layer_set_usage_count"] == 1
    assert axis3_wall["wall_material_layer_association_pass"] is False
    assert axis3_wall["unassociated_wall_ids"] == ["#33"]


def test_ifc_parser_validates_material_targets_and_schema_subtypes():
    parser = _ifc_parser_functions()
    wrong_target = parser["step_entity_inventory"]([
        (
            "#1=IFCPROJECT('0000000000000000000000',$,'Project',"
            "$,$,$,$,$,$);"
        ),
        "#10=IFCMATERIALLAYER(#1,200.,$,$,$,$,$);",
        "#11=IFCMATERIALLAYERSET((#10),'Set',$);",
    ], "IFC4")
    assert "#10" in wrong_target["invalid_semantic_entity_ids"]
    assert wrong_target["valid_material_layer_set_count"] == 0

    offset_wall_statements = [
        "#10=IFCMATERIAL('Concrete',$,$);",
        (
            "#11=IFCMATERIALLAYERWITHOFFSETS("
            "#10,200.,$,$,$,$,$,.AXIS3.,(0.,0.));"
        ),
        "#12=IFCMATERIALLAYERSET((#11),'Offset set',$);",
        (
            "#13=IFCMATERIALLAYERSETUSAGE("
            "#12,.AXIS2.,.POSITIVE.,0.,2800.);"
        ),
        (
            "#20=IFCWALLELEMENTEDCASE("
            "'1111111111111111111111',$,$,$,$,$,$,$,$);"
        ),
        (
            "#21=IFCRELASSOCIATESMATERIAL("
            "'2222222222222222222222',$,$,$,(#20),#13);"
        ),
    ]
    offset_wall = parser["step_entity_inventory"](
        offset_wall_statements, "IFC4")
    assert offset_wall["invalid_semantic_entity_ids"] == []
    assert offset_wall["wall_count"] == 1
    assert offset_wall["material_layer_count"] == 1
    assert offset_wall["valid_material_layer_set_count"] == 1
    assert offset_wall["wall_material_layer_association_pass"] is True

    missing_extent = list(offset_wall_statements)
    missing_extent[3] = missing_extent[3].replace("2800.", "$")
    invalid_usage = parser["step_entity_inventory"](missing_extent, "IFC4")
    assert "#13" in invalid_usage["invalid_semantic_entity_ids"]
    assert invalid_usage["wall_material_layer_association_pass"] is False

    one_offset = list(offset_wall_statements)
    one_offset[1] = one_offset[1].replace("(0.,0.)", "(0.)")
    invalid_offset_count = parser["step_entity_inventory"](
        one_offset, "IFC4")
    assert "#11" in invalid_offset_count["invalid_semantic_entity_ids"]
    assert invalid_offset_count["valid_material_layer_set_count"] == 0

    parallel_offset = list(offset_wall_statements)
    parallel_offset[1] = parallel_offset[1].replace(".AXIS3.", ".AXIS2.")
    invalid_offset_direction = parser["step_entity_inventory"](
        parallel_offset, "IFC4")
    assert "#13" in invalid_offset_direction["invalid_semantic_entity_ids"]
    assert invalid_offset_direction[
        "wall_material_layer_association_pass"] is False


def test_ifc_parser_applies_schema_specific_wall_and_priority_contracts():
    parser = _ifc_parser_functions()

    ifc4_final = parser["step_entity_inventory"]([
        "#10=IFCMATERIALLAYER($,200.,$,$,$,$,0.5);",
    ], "IFC4")
    ifc4_addendum_header_alias = parser["step_entity_inventory"]([
        "#10=IFCMATERIALLAYER($,200.,$,$,$,$,50);",
    ], "IFC4")
    ifc4_add1 = parser["step_entity_inventory"]([
        "#10=IFCMATERIALLAYER($,200.,$,$,$,$,0.5);",
    ], "IFC4_ADD1")
    assert ifc4_final["invalid_semantic_entity_ids"] == []
    assert ifc4_addendum_header_alias["invalid_semantic_entity_ids"] == []
    assert ifc4_add1["invalid_semantic_entity_ids"] == ["#10"]

    elemented_wall = (
        "#20=IFCWALLELEMENTEDCASE("
        "'1111111111111111111111',$,$,$,$,$,$,$,$);"
    )
    ifc4 = parser["step_entity_inventory"]([elemented_wall], "IFC4")
    ifc4x3 = parser["step_entity_inventory"]([elemented_wall], "IFC4X3")
    assert ifc4["wall_ids"] == ["#20"]
    assert ifc4["invalid_semantic_entity_ids"] == []
    assert ifc4x3["wall_ids"] == []
    assert ifc4x3["invalid_semantic_entity_ids"] == ["#20"]


def test_wall_layer_contract_normalizes_and_rejects_unsupported_combinations():
    from rhinoclaw.tools.visualarq import _normalize_wall_layers

    layers = _normalize_wall_layers([
        {
            "name": " Innenputz ", "thickness": 15,
            "type": "normal", "wrapping_ends": True,
            "wrapping_openings": True,
        },
        {"name": "Tragwerk", "thickness": 200, "core": True},
    ])

    assert layers == [
        {
            "name": "Innenputz", "thickness": 15.0,
            "type": "normal", "wrapping_ends": True,
            "wrapping_openings": True,
        },
        {
            "name": "Tragwerk", "thickness": 200.0,
            "type": "core", "wrapping_ends": False,
            "wrapping_openings": False,
        },
    ]

    for invalid_layers, expected in (
        ([{"name": "Core", "thickness": 200, "type": "core",
           "wrapping_ends": True}], "cannot wrap"),
        ([{"name": "A", "thickness": 10},
          {"name": "a", "thickness": 20}], "duplicate"),
        ([{"name": "A", "thickness": 0}], "positive"),
        ([{"name": "A", "thickness": 10, "type": "normal",
           "core": "false"}], "boolean"),
    ):
        try:
            _normalize_wall_layers(invalid_layers)
        except ValueError as exc:
            assert expected in str(exc)
        else:  # pragma: no cover - keeps each negative contract explicit
            raise AssertionError("invalid wall layer contract was accepted")


def test_create_wall_style_returns_requested_and_measured_contract():
    from rhinoclaw.tools.visualarq import va_create_wall_style

    style_id = "11111111-1111-1111-1111-111111111111"
    actual_layers = [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "name": "Innenputz", "thickness": 15.0,
            "type": "normal", "type_value": 0,
            "wrapping": {"ends": True, "openings": True, "value": 3},
        },
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "name": "Tragwerk", "thickness": 200.0,
            "type": "core", "type_value": 1,
            "wrapping": {"ends": False, "openings": False, "value": 0},
        },
    ]
    rhino = _rhino({
        "status": "success", "style_id": style_id,
        "requested": {
            "name": "RC_G3", "height": 2800.0,
            "layers": [], "total_layer_thickness": 215.0,
            "layer_order": "inside_to_outside",
        },
        "actual": {
            "id": style_id, "kind": "wall", "name": "RC_G3",
            "height": 2800.0, "layers": actual_layers,
            "layer_count": 2, "total_layer_thickness": 215.0,
        },
        "verification": {
            "pass": True, "tolerance": 0.001,
            "source": "VisualARQ.Script readback",
        },
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_wall_style(
            MagicMock(), " RC_G3 ", [
                {
                    "name": "Innenputz", "thickness": 15,
                    "type": "normal", "wrapping_ends": True,
                    "wrapping_openings": True,
                },
                {"name": "Tragwerk", "thickness": 200, "type": "core"},
            ], height=2800,
        ))

    assert data["success"] is True
    assert data["data"]["actual"]["layers"] == actual_layers
    assert data["data"]["verification"]["pass"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_wall_style>", "exec")
    params = _params_from_code(code)
    assert params["name"] == "RC_G3"
    assert params["layers"][1]["type"] == "core"
    assert params["layers"][1]["wrapping_ends"] is False
    assert "GetStyleComponentName" in code
    assert "GetSubStyleComponents" in code
    assert "GetWallLayers" in code
    assert '"sources_agree"' in code
    assert "created_layer_ids" in code
    assert "DeleteStyleComponent" in code
    assert '"leaked_ids"' in code

    inventory_before = code.index(
        "global_inventory_before = va_global_style_inventory()")
    add_style = code.index("created_id = va.AddWallStyle(requested_name)")
    inventory_after = code.index(
        "global_inventory_after_style = va_global_style_inventory()")
    delta_check = code.index("added_style_ids != [str(created_id)]")
    name_check = code.index(
        "va_text(va.GetStyleName(created_id)) != requested_name")
    assert inventory_before < add_style < inventory_after
    assert inventory_after < delta_check
    assert inventory_after < name_check
    assert "AddWallStyle global inventory delta/identity mismatch" in code
    assert '"GetAllWallStyleIds"' in code
    assert 'global_inventory_before["all_component_ids"]' in code
    assert 'actual.get("product_count_read_complete") is not True' in code
    assert 'actual.get("product_count") != 0' in code
    assert 'actual.get("readback_complete") is not True' in code
    layer_add = code.index("layer_id = va.AddWallLayer(")
    layer_setter = code.index("set_type = va.SetWallLayerType(")
    assert code.index("layer_inventory_before =", layer_add - 300) < layer_add
    assert code.index("layer_inventory_after =", layer_add) < layer_setter
    assert code.index("parent_id = va.GetParentStyleComponent", layer_add) < \
        layer_setter
    assert "added_layer_ids != [layer_id] or" in code
    assert "added_global_components != [str(layer_id)]" in code
    assert '"component_owners"].get(str(layer_id))' in code
    assert "AddWallLayer global inventory delta/parent mismatch" in code
    assert "final global style/component delta is not isolated" in code
    assert "if cleanup_parent_id == cleanup_target_id:" in code
    assert '"parent_verified": False' in code

    assert "cleanup_verified = created_id == Guid.Empty" not in code
    assert "style_ownership_verified = False" in code
    assert "style_ownership_verified = True" in code
    assert "ownership_verified = style_ownership_verified" in code
    assert "returned_matches = created_id != Guid.Empty and" in code
    assert "if not ownership_verified and len(new_style_ids) == 1 and" in code
    assert "if inferred_name == requested_name and returned_matches:" in code
    inference_start = code.index(
        "if not ownership_verified and len(new_style_ids) == 1 and")
    cleanup_start = code.index(
        "if cleanup_target_id != Guid.Empty and ownership_verified:")
    inference_branch = code[inference_start:cleanup_start]
    assert "created_id != Guid.Empty" in inference_branch
    assert "cleanup_target_id = inferred_id" in inference_branch
    assert "created_id == Guid.Empty or" not in inference_branch
    assert (
        "if cleanup_target_id != Guid.Empty and ownership_verified:"
    ) in code
    assert "cleanup_verified = inventory_restored" in code
    assert "cleanup_verified = cleanup_verified and not leaked_layer_ids" in code
    assert "global_inventory_after_cleanup == global_inventory_before" in code
    assert '"inventory_before": inventory_before_text' in code
    assert '"inventory_after_cleanup": [' in code
    assert '"global_inventory_before": global_inventory_before' in code
    assert '"global_inventory_after_cleanup":' in code
    assert '"inventory_restored": inventory_restored' in code
    assert "residual_style_ids = sorted(" in code
    assert "residual_component_ids = sorted(" in code


def test_create_wall_style_fails_before_rhino_for_unsupported_layer_fields():
    from rhinoclaw.tools.visualarq import va_create_wall_style

    unsupported = json.loads(va_create_wall_style(
        MagicMock(), "RC_G3", [
            {"name": "Core", "thickness": 200, "function": "load_bearing"},
        ],
    ))
    core_wrap = json.loads(va_create_wall_style(
        MagicMock(), "RC_G3", [
            {
                "name": "Core", "thickness": 200, "type": "core",
                "wrapping_openings": True,
            },
        ],
    ))

    assert unsupported["success"] is False
    assert unsupported["code"] == "UNSUPPORTED_OPERATION"
    assert "VisualARQ 3.7.2" in unsupported["message"]
    assert core_wrap["success"] is False
    assert core_wrap["code"] == "INVALID_PARAMS"


def test_create_door_style_uses_exact_rectangular_contract_and_owned_cleanup():
    from rhinoclaw.tools.visualarq import va_create_door_style

    style_id = "11111111-1111-1111-1111-111111111111"
    rhino = _rhino({
        "status": "success", "style_id": style_id,
        "requested": {
            "name": "RC_Door", "profile_template": "rectangular",
        },
        "actual": {
            "id": style_id, "kind": "door", "name": "RC_Door",
        },
        "automatic_component_ids": [], "automatic_profile_ids": [],
        "verification": {"pass": True},
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_door_style(
            MagicMock(), "  RC_Door  "))

    assert data["success"] is True
    assert data["data"]["style_id"] == style_id
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_door_style>", "exec")
    assert _params_from_code(code)["name"] == "RC_Door"
    assert (
        '"AddDoorStyle", ["System.String", "System.Guid"], '
        '"System.Guid"'
    ) in code
    assert "va.GetRectangularProfileTemplate()" in code
    assert "va.GetProfileTemplates()" in code
    assert "va.IsProfileTemplate(template_id)" in code
    baseline_global = code.index("global_before = va_global_style_inventory()")
    baseline_profiles = code.index(
        "profiles_before = va_opening_profile_inventory()")
    add_style = code.index("created_id = va.AddDoorStyle(")
    post_global = code.index(
        "global_after = va_global_style_inventory()", add_style)
    post_profiles = code.index(
        "profiles_after = va_opening_profile_inventory()", add_style)
    assert baseline_global < add_style < post_global
    assert baseline_profiles < add_style < post_profiles
    assert 'added_style_ids == [str(created_id)]' in code
    assert '"component_owners".get(component_id)' not in code
    assert 'global_after["component_owners"].get(component_id)' in code
    assert 'profiles_after["profile_owners"].get(profile_id)' in code
    assert '"automatic_component_ids": added_component_ids' in code
    assert '"automatic_profile_ids": added_profile_ids' in code
    cleanup_gate = code.index("if ownership_verified:", add_style)
    cleanup_delete = code.index("va.DeleteStyle(created_id)", cleanup_gate)
    assert cleanup_gate < cleanup_delete
    assert "va.GetProductsByStyle(created_id, False)" in \
        code[cleanup_gate:cleanup_delete]
    assert "global_cleanup == global_before" in code
    assert "profiles_cleanup == profiles_before" in code
    assert '"PARTIAL_MUTATION"' in code


def test_create_window_style_specializes_the_owned_style_vertical():
    from rhinoclaw.tools.visualarq import va_create_window_style

    style_id = "22222222-2222-2222-2222-222222222222"
    rhino = _rhino({
        "status": "success", "style_id": style_id,
        "requested": {
            "name": "RC_Window", "profile_template": "rectangular",
        },
        "actual": {
            "id": style_id, "kind": "window", "name": "RC_Window",
        },
        "automatic_component_ids": [], "automatic_profile_ids": [],
        "verification": {"pass": True},
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_create_window_style(
            MagicMock(), "  RC_Window  "))

    assert data["success"] is True
    assert data["data"]["style_id"] == style_id
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_create_window_style>", "exec")
    assert _params_from_code(code)["name"] == "RC_Window"
    assert (
        '"AddWindowStyle", ["System.String", "System.Guid"], '
        '"System.Guid"'
    ) in code
    assert "created_id = va.AddWindowStyle(" in code
    assert 'entry["inventory_method"] == "GetAllWindowStyleIds"' in code
    assert 'expected_profile_style_key = "window|" + str(created_id)' in code
    assert 'actual.get("kind") == "window"' in code
    assert "va.IsWindowStyle(created_id)" in code
    assert "va.DeleteStyle(created_id)" in code
    assert "global_cleanup == global_before" in code
    assert "profiles_cleanup == profiles_before" in code


def test_add_rectangular_opening_profile_validates_locally():
    from rhinoclaw.tools.visualarq import (
        va_add_rectangular_opening_size_profile,
    )

    valid_style = "11111111-1111-1111-1111-111111111111"
    with patch(PATCH) as connection:
        results = [
            json.loads(va_add_rectangular_opening_size_profile(
                MagicMock(), "not-a-guid", "900x2100", 900, 2100)),
            json.loads(va_add_rectangular_opening_size_profile(
                MagicMock(), valid_style, "  ", 900, 2100)),
            json.loads(va_add_rectangular_opening_size_profile(
                MagicMock(), valid_style, "900x2100", 0, 2100)),
            json.loads(va_add_rectangular_opening_size_profile(
                MagicMock(), valid_style, "900x2100", 900, float("nan"))),
        ]

    assert all(result["success"] is False for result in results)
    assert all(result["code"] == "INVALID_PARAMS" for result in results)
    connection.assert_not_called()


def test_add_rectangular_opening_profile_has_exact_delta_and_safe_cleanup():
    from rhinoclaw.tools.visualarq import (
        va_add_rectangular_opening_size_profile,
    )

    style_id = "11111111-1111-1111-1111-111111111111"
    profile_id = "22222222-2222-2222-2222-222222222222"
    rhino = _rhino({
        "status": "success", "profile_id": profile_id,
        "style_id": style_id, "style_kind": "door",
        "requested": {"name": "900x2100", "width": 900, "height": 2100},
        "actual": {
            "id": profile_id, "name": "900x2100", "style_id": style_id,
            "rectangular": True,
            "dimensions": {"width": 900.0, "height": 2100.0},
        },
        "verification": {"pass": True},
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_add_rectangular_opening_size_profile(
            MagicMock(), "{11111111-1111-1111-1111-111111111111}",
            "  900x2100  ", 900, 2100))

    assert data["success"] is True
    assert data["data"]["profile_id"] == profile_id
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_add_rectangular_opening_size_profile>", "exec")
    assert _params_from_code(code) == {
        "style_id": style_id, "name": "900x2100",
        "width": 900.0, "height": 2100.0,
    }
    assert "def va_rectangular_profile_size_constructor_contract():" in code
    assert '"VisualARQ.Script+RectangularProfileSize"' in code
    assert "va.RectangularProfileSize(" in code
    baseline_global = code.index("global_before = va_global_style_inventory()")
    baseline_profiles = code.index(
        "profiles_before = va_opening_profile_inventory()")
    add_profile = code.index(
        "created_id = va.AddOpeningStyleSizeProfile(")
    owner_check = code.index(
        'profiles_after_add["profile_owners"].get(', add_profile)
    setter = code.index("setter_result = bool(va.SetRectangularProfileSize(")
    assert baseline_global < add_profile < owner_check < setter
    assert baseline_profiles < add_profile
    assert "added_profile_ids == [str(created_id)]" in code
    assert "found_id = va.FindOpeningStyleSizeProfile(" in code
    assert "actual.get(\"dimensions\")" in code
    cleanup_gate = code.index("if ownership_verified:", setter)
    in_use_gate = code.index(
        "va.FindOpeningsBySizeProfile(", cleanup_gate)
    cleanup_delete = code.index("va.DeleteProfile(created_id)", in_use_gate)
    assert cleanup_gate < in_use_gate < cleanup_delete
    assert "global_cleanup == global_before" in code
    assert "profiles_cleanup == profiles_before" in code
    assert '"PARTIAL_MUTATION"' in code


def test_opening_style_reader_reports_profile_identity_shape_and_dimensions():
    from rhinoclaw.tools.visualarq import va_get_style

    style_id = "11111111-1111-1111-1111-111111111111"
    rhino = _rhino({
        "status": "success",
        "style": {
            "id": style_id, "kind": "door", "name": "RC_Door",
            "size_profiles": [],
        },
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_get_style(
            MagicMock(), style_id, expected_kind="door"))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_get_opening_style>", "exec")
    assert "def va_opening_profile_snapshot(" in code
    assert "va.GetProfileName(profile_id)" in code
    assert "va.GetOpeningStyleFromSizeProfile(profile_id)" in code
    assert "va.IsOpeningStyleSizeProfile(" in code
    assert "va.IsOpeningProfile(profile_id)" in code
    assert "va.IsRectangularProfile(profile_id)" in code
    assert "va.GetRectangularProfileSize(profile_id)" in code
    assert "va_opening_template_snapshot(style_id)" in code

    profile_helper = code[
        code.index("def va_opening_profile_snapshot("):
        code.index("def va_opening_template_snapshot(")
    ]
    assert "if is_opening_profile is not True" not in profile_helper
    assert "independent profile-family classifier" in profile_helper
    assert 'va_method_available("IsOpeningProfile")' in profile_helper
    assert '"is_opening_profile": is_opening_profile' in profile_helper
    assert '"profile_family_diagnostic_non_gating"' in profile_helper

    template_helper = code[
        code.index("def va_opening_template_snapshot("):
        code.index("def va_opening_profile_inventory(")
    ]
    assert "available = template_id != Guid.Empty" in template_helper
    assert '"available": available' in template_helper
    assert "style profile template is empty" not in template_helper


def test_opening_size_profile_membership_is_independent_of_family_classifier():
    namespace = _opening_profile_snapshot_runtime()

    class Text(str):
        def Trim(self):
            return self.strip()

    class Size:
        Width = 900.0
        Height = 2100.0

    class FakeVa:
        def __init__(self, *, owner="STYLE", membership=True, probe_error=None):
            self.owner = owner
            self.membership = membership
            self.probe_error = probe_error

        def GetProfileName(self, profile_id):
            return Text("900 x 2100")

        def GetOpeningStyleFromSizeProfile(self, profile_id):
            return self.owner

        def IsOpeningStyleSizeProfile(self, style_id, profile_id):
            return self.membership

        def IsProfile(self, profile_id):
            return True

        def IsOpeningProfile(self, profile_id):
            if self.probe_error is not None:
                raise self.probe_error
            return False

        def IsRectangularProfile(self, profile_id):
            return True

        def GetRectangularProfileSize(self, profile_id):
            return Size()

    snapshot = namespace["va_opening_profile_snapshot"]

    namespace["va"] = FakeVa()
    valid = snapshot("STYLE", "PROFILE")
    assert valid["readback_complete"] is True
    assert valid["owner_matches"] is True
    assert valid["membership_verified"] is True
    assert valid["is_opening_profile"] is False
    assert valid["dimensions"] == {"width": 900.0, "height": 2100.0}
    assert valid["diagnostic_warnings"] == []

    namespace["va"] = FakeVa(probe_error=RuntimeError("probe unavailable"))
    warning_only = snapshot("STYLE", "PROFILE")
    assert warning_only["readback_complete"] is True
    assert warning_only["is_opening_profile"] is None
    assert warning_only["diagnostic_warnings"][0]["stage"] == (
        "opening_profile_family_probe"
    )

    namespace["va"] = FakeVa(membership=False)
    invalid_membership = snapshot("STYLE", "PROFILE")
    assert invalid_membership["readback_complete"] is False
    assert any(
        error["stage"] == "membership"
        for error in invalid_membership["readback_errors"]
    )

    namespace["va"] = FakeVa(owner="OTHER")
    invalid_owner = snapshot("STYLE", "PROFILE")
    assert invalid_owner["readback_complete"] is False
    assert invalid_owner["owner_matches"] is False


def test_style_queries_and_mutations_keep_canonical_guid_contract():
    from rhinoclaw.tools.visualarq import (
        va_delete_style,
        va_get_style,
        va_rename_style,
    )

    style_id = "11111111-1111-1111-1111-111111111111"
    style = {
        "id": style_id, "kind": "wall", "name": "RC_G3",
        "layers": [], "layer_count": 0, "total_layer_thickness": 0,
    }
    with patch(PATCH, return_value=_rhino({
        "status": "success", "style": style,
    })):
        queried = json.loads(va_get_style(
            MagicMock(), style_id, expected_kind="wall"))
    with patch(PATCH, return_value=_rhino({
        "status": "success", "changed": True,
        "before": style, "actual": {**style, "name": "RC_G3_Renamed"},
    })):
        renamed = json.loads(va_rename_style(
            MagicMock(), style_id, "RC_G3_Renamed"))
    with patch(PATCH, return_value=_rhino({
        "status": "error", "code": "RESOURCE_IN_USE",
        "message": "Style is used by document products",
        "product_ids": ["22222222-2222-2222-2222-222222222222"],
        "product_count": 1, "style": style,
    })):
        in_use = json.loads(va_delete_style(
            MagicMock(), style_id, confirm=True))

    assert queried["success"] is True
    assert queried["data"]["style"]["id"] == style_id
    assert renamed["data"]["actual"]["name"] == "RC_G3_Renamed"
    assert in_use["success"] is False
    assert in_use["code"] == "RESOURCE_IN_USE"
    assert in_use["data"]["product_count"] == 1

    no_confirm = json.loads(va_delete_style(MagicMock(), style_id))
    bad_guid = json.loads(va_get_style(MagicMock(), "not-a-guid"))
    assert no_confirm["code"] == "INVALID_PARAMS"
    assert bad_guid["code"] == "INVALID_PARAMS"


def test_delete_style_requires_exact_global_style_and_component_delta():
    from rhinoclaw.tools.visualarq import va_delete_style

    style_id = "11111111-1111-1111-1111-111111111111"
    with patch(PATCH, return_value=_rhino({
        "status": "error", "code": "PARTIAL_MUTATION",
        "message": "Style removed but size profile remains",
        "presence": False,
        "component_presence": {
            "22222222-2222-2222-2222-222222222222": True,
        },
        "residual_component_ids": [
            "22222222-2222-2222-2222-222222222222",
        ],
    })) as connection:
        data = json.loads(va_delete_style(
            MagicMock(), style_id, confirm=True))

    assert data["success"] is False
    assert data["code"] == "PARTIAL_MUTATION"
    code = connection.return_value.send_command.call_args[0][1]["code"]
    compile(code, "<va_delete_style_components>", "exec")
    assert "def va_global_style_delete_contract(" in code
    assert "global_before = va_global_style_inventory()" in code
    assert "global_after = va_global_style_inventory()" in code
    assert "global_contract = va_global_style_delete_contract(" in code
    assert '"styles_exact": after.get("styles") == expected_styles' in code
    assert '"style_owners_exact"' in code
    assert '"component_owners_exact"' in code
    assert '"inventory_counts_exact"' in code
    assert 'global_contract["target_component_ids"]' in code
    assert "child_presence is not False" in code
    assert 'global_contract["pass"]' in code
    assert "global_after == global_before" in code
    assert '"residual_component_ids": residual_component_ids' in code


def test_rename_style_requires_global_exact_delta_and_global_rollback():
    from rhinoclaw.tools.visualarq import va_rename_style

    style_id = "11111111-1111-1111-1111-111111111111"
    rhino = _rhino({
        "status": "success", "changed": True,
        "actual": {"id": style_id, "name": "Renamed"},
    })
    with patch(PATCH, return_value=rhino):
        data = json.loads(va_rename_style(
            MagicMock(), style_id, "Renamed"))

    assert data["success"] is True
    code = rhino.send_command.call_args[0][1]["code"]
    compile(code, "<va_rename_style_global>", "exec")
    assert "def va_global_style_rename_contract(" in code
    assert "global_before = va_global_style_inventory()" in code
    assert "global_actual = va_global_style_inventory()" in code
    assert "global_contract = va_global_style_rename_contract(" in code
    assert 'actual == expected_after and global_contract["pass"]' in code
    assert '"style_owners_unchanged"' in code
    assert '"component_owners_unchanged"' in code
    assert "rollback_global == global_before" in code


def test_object_inventory_exposes_classifications_and_measured_wall_fields():
    from rhinoclaw.tools.visualarq import va_get_object, va_list_objects

    object_id = "22222222-2222-2222-2222-222222222222"
    wall = {
        "id": object_id, "kind": "wall",
        "classifications": ["wall", "product", "building_element"],
        "style": {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "RC_G3", "kind": "wall",
        },
        "height": 2800.0, "thickness": 230.0,
        "path": {
            "start": [0, 0, 0], "end": [4000, 0, 0],
            "length": 4000.0, "is_valid": True,
        },
        "geometry": {
            "is_valid": True, "bbox_valid": True,
            "bbox_min": [0, -115, 0], "bbox_max": [4000, 115, 2800],
            "volume": None, "volume_verified": False,
        },
        "quantity": {
            "source": "instance_definition_solid_geometry",
            "volume": 2576000000.0, "volume_verified": True,
            "measurement_complete": True,
        },
    }
    rhino = _rhino({
        "status": "success", "kind": "wall", "objects": [wall],
        "matched_count": 1, "returned_count": 1, "truncated": False,
    })
    with patch(PATCH, return_value=rhino):
        listed = json.loads(va_list_objects(MagicMock(), kind="wall"))
    list_code = rhino.send_command.call_args[0][1]["code"]

    rhino = _rhino({"status": "success", "object": wall})
    with patch(PATCH, return_value=rhino):
        queried = json.loads(va_get_object(
            MagicMock(), object_id, expected_kind="building_element"))
    get_code = rhino.send_command.call_args[0][1]["code"]

    assert listed["data"]["objects"][0]["classifications"] == [
        "wall", "product", "building_element",
    ]
    assert queried["data"]["object"]["geometry"]["volume_verified"] is False
    for label, code in (("list", list_code), ("get", get_code)):
        compile(code, f"<va_{label}_objects>", "exec")
        assert "va_object_classification_probe" in code
        assert "GetWallHeightSource" in code
        assert "GetWallLayerThicknessSource" in code
        assert "GetWallLayerTopOffsetSource" in code
        assert "GetWallLayerBottomOffsetSource" in code
        assert "GetWallAlignmentOffset" in code
        assert "va_instance_definition_volume_snapshot" in code
        assert "abs(normalized) < 1e300" in code
        assert 'layer["style_thickness"]' in code
        assert 'layer["object_thickness"]' in code
    assert 'params["expected_kind"] not in classifications' in get_code
    assert '"scan_complete"' in list_code


def test_visualarq_new_tools_are_reexported():
    import rhinoclaw

    for name in (
        "va_add_building", "va_add_rectangular_opening_size_profile",
        "va_create_door_style", "va_create_slab", "va_create_space",
        "va_create_window",
        "va_create_window_style", "va_create_wall_style", "va_delete_style",
        "va_get_object", "va_get_style", "va_list_buildings",
        "va_list_objects", "va_rename_style",
    ):
        assert callable(getattr(rhinoclaw, name))


def test_build_va_script_is_ironpython2_safe():
    from rhinoclaw.utils.visualarq import build_va_script

    script = build_va_script(
        "result = {'status': 'success'}", {"a": 1, "name": "Außenwand"})
    assert "f\"" not in script and "f'" not in script  # no f-strings
    assert "VisualARQ.Script" in script
    assert "va_assembly = clr.AddReference" in script
    assert "System.AppDomain.CurrentDomain.GetAssemblies()" in script
    assert "def va_method_parameter_sets" in script
    assert "def va_method_has_parameter" in script
    assert "def va_method_signatures" in script
    assert "def va_exact_method_shape" in script
    assert "isinstance(value, (int, long))" in script
    assert "JValue(System.Int64(integer))" in script
    assert "JValue(System.UInt64(integer))" in script
    assert "Newtonsoft.Json" in script
    assert "StringEscapeHandling.EscapeNonAscii" in script
    assert "def va_text_key" in script
    assert "__doc__" not in script
    assert '"a": 1' in script
    assert "Außenwand" not in script
    assert _params_from_code(script)["name"] == "Außenwand"


def test_run_va_classifies_missing_result_without_retrying_body():
    from rhinoclaw.utils.visualarq import run_va

    rhino = MagicMock()
    rhino.send_command.return_value = {
        "success": True,
        "result": "Script successfully executed! Print output: ",
    }

    result = run_va(rhino, "result = {'status': 'success'}")

    assert result["status"] == "error"
    assert result["code"] == "SCRIPT_ERROR"
    assert result["runner_failure"] == "missing_result_marker"
    assert rhino.send_command.call_count == 1


def test_run_va_preserves_script_execution_failure_without_retry():
    from rhinoclaw.utils.visualarq import run_va

    rhino = MagicMock()
    rhino.send_command.return_value = {
        "success": False,
        "message": "VisualARQ script traceback",
    }

    result = run_va(rhino, "result = {'status': 'success'}")

    assert result == {
        "status": "error",
        "code": "SCRIPT_ERROR",
        "runner_failure": "script_execution_failed",
        "message": "VisualARQ script traceback",
    }
    assert rhino.send_command.call_count == 1
