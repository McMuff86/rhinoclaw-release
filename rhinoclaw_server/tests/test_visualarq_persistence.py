"""Contract tests for the read-only VisualARQ persistence pre-save gate."""

import ast
import json
from unittest.mock import MagicMock, patch

import pytest


PATCH = "rhinoclaw.tools.visualarq_persistence.get_rhino_connection"
PRINT = "Script successfully executed! Print output: "
OBJECT_ID = "22222222-2222-2222-2222-222222222222"
DEFINITION_ID = "33333333-3333-3333-3333-333333333333"


def _wire(result):
    return PRINT + "RESULT:" + json.dumps(result)


def _semantic(*, passed=True):
    return {
        "pass": passed,
        "contract": "VisualARQ.Script IsProduct(Guid) -> Boolean",
        "method_shape": {
            "verified": True,
            "match_count": 1,
            "parameter_types": ["System.Guid"],
            "return_type": "System.Boolean",
        },
        "is_product": passed,
        "kind": "wall" if passed else None,
        "classifications": ["wall", "product"] if passed else [],
        "style_id": "11111111-1111-1111-1111-111111111111",
        "style_read_error": None,
        "errors": [],
        "classifier_errors": [],
        "unavailable_classifiers": [],
    }


def _definition(*, name="*Wall{fixture}", system=False, members=1):
    return {
        "definition_id": DEFINITION_ID,
        "name": name,
        "index": 7,
        "is_system": system,
        "is_deleted": False,
        "is_valid": True,
        "table_resident": True,
        "object_count": members,
        "member_count": members,
        "depth": 0,
    }


def _persistence(*, passed=True, name="*Wall{fixture}"):
    definition = _definition(
        name=name,
        system=name.upper().startswith("*EMPTYDEFINITION"),
        members=1 if passed else 0,
    )
    errors = [] if passed else [{
        "code": "empty_definition",
        "message": "Instance definition is Rhino's placeholder",
    }]
    return {
        "applicable": True,
        "pass": passed,
        "root_object_type": "Rhino.DocObjects.InstanceObject",
        "root_geometry_type": "Rhino.Geometry.InstanceReferenceGeometry",
        "root_is_definition_member": False,
        "root_definition_id": DEFINITION_ID,
        "root_parent_definition_id": DEFINITION_ID,
        "root_parent_matches": True,
        "root_definition": definition,
        "definition_count": 1,
        "definitions": [definition],
        "node_count": 1 if passed else 0,
        "leaf_count": 1 if passed else 0,
        "valid_leaf_count": 1 if passed else 0,
        "max_depth": 0,
        "system_definition_count": 0 if passed else 1,
        "empty_definition_count": 0 if passed else 1,
        "zero_member_definition_count": 0 if passed else 1,
        "error_count": len(errors),
        "errors": errors,
        "errors_truncated": False,
        "limits": {
            "max_depth": 32,
            "max_nodes": 10000,
            "max_definitions": 128,
        },
    }


def _result(
    *,
    object_id=OBJECT_ID,
    semantic_pass=True,
    persistence_pass=True,
    definition_name="*Wall{fixture}",
):
    semantics = _semantic(passed=semantic_pass)
    persistence = _persistence(
        passed=persistence_pass,
        name=definition_name,
    )
    ready = semantic_pass and persistence_pass
    failures = []
    if not semantic_pass:
        failures.append("visualarq_semantics_unverified")
    if not persistence_pass:
        failures.append("rhino_persistence_root_unready")
    return {
        "status": "success",
        "ready": ready,
        "requested_ids": [object_id],
        "requested_count": 1,
        "ready_count": 1 if ready else 0,
        "not_ready_count": 0 if ready else 1,
        "objects": [{
            "id": object_id,
            "exists": True,
            "ready": ready,
            "visualarq_semantics": semantics,
            "rhino_persistence_root": persistence,
            "failures": failures,
        }],
        "shared_root_definitions": [],
        "state_guard": {
            "modified_before": False,
            "modified_after": False,
            "object_count_before": 1,
            "object_count_after": 1,
            "instance_definition_count_before": 2,
            "instance_definition_count_after": 2,
            "pass": True,
        },
        "contract": {
            "read_only": True,
            "visualarq_semantics": "exact IsProduct(Guid) -> Boolean",
            "rhino_persistence_root": (
                "recursive non-system non-empty InstanceDefinition graph"
            ),
            "save_or_reload_performed": False,
        },
    }


def _rhino(result):
    connection = MagicMock()
    connection.send_command.return_value = _wire(result)
    return connection


def test_ready_product_keeps_semantics_and_persistence_as_separate_evidence():
    from rhinoclaw.tools.visualarq_persistence import (
        va_validate_persistence_readiness,
    )

    rhino = _rhino(_result())
    with patch(PATCH, return_value=rhino):
        response = json.loads(va_validate_persistence_readiness(
            MagicMock(), ["{22222222-2222-2222-2222-222222222222}"]
        ))

    assert response["success"] is True
    assert response["data"]["ready"] is True
    item = response["data"]["objects"][0]
    assert item["visualarq_semantics"]["pass"] is True
    assert item["rhino_persistence_root"]["pass"] is True
    assert item["rhino_persistence_root"]["root_definition"]["name"] == (
        "*Wall{fixture}"
    )
    assert rhino.send_command.call_count == 2
    load_probe = rhino.send_command.call_args_list[0][0][1]["code"]
    assert "VA_LOAD_PROBE:ready" in load_probe
    script = rhino.send_command.call_args_list[1][0][1]["code"]
    assert '"22222222-2222-2222-2222-222222222222"' in script
    compile(script, "<va_validate_persistence_readiness>", "exec")


def test_empty_definition_is_a_successful_negative_verdict_not_api_failure():
    from rhinoclaw.tools.visualarq_persistence import (
        va_validate_persistence_readiness,
    )

    result = _result(
        persistence_pass=False,
        definition_name="*EmptyDefinition",
    )
    rhino = _rhino(result)
    with patch(PATCH, return_value=rhino):
        response = json.loads(va_validate_persistence_readiness(
            MagicMock(), [OBJECT_ID]
        ))

    assert response["success"] is True
    assert response["data"]["ready"] is False
    item = response["data"]["objects"][0]
    assert item["visualarq_semantics"]["pass"] is True
    root = item["rhino_persistence_root"]
    assert root["pass"] is False
    assert root["empty_definition_count"] == 1
    assert root["system_definition_count"] == 1
    assert root["zero_member_definition_count"] == 1


def test_python_envelope_rejects_optimistic_empty_definition_pass():
    from rhinoclaw.tools.visualarq_persistence import (
        va_validate_persistence_readiness,
    )

    result = _result()
    root = result["objects"][0]["rhino_persistence_root"]
    root["root_definition"]["name"] = "*EmptyDefinition"
    root["definitions"][0]["name"] = "*EmptyDefinition"
    rhino = _rhino(result)
    with patch(PATCH, return_value=rhino):
        response = json.loads(va_validate_persistence_readiness(
            MagicMock(), [OBJECT_ID]
        ))

    assert response["success"] is False
    assert response["code"] == "VERIFICATION_FAILED"
    assert "optimistic persistence pass" in response["message"]


@pytest.mark.parametrize(
    "ids",
    [
        [],
        ["not-a-guid"],
        ["00000000-0000-0000-0000-000000000000"],
        [OBJECT_ID, "{22222222-2222-2222-2222-222222222222}"],
    ],
)
def test_invalid_ids_fail_before_rhino_round_trip(ids):
    from rhinoclaw.tools.visualarq_persistence import (
        va_validate_persistence_readiness,
    )

    with patch(PATCH) as connection:
        response = json.loads(va_validate_persistence_readiness(
            MagicMock(), ids
        ))

    assert response["success"] is False
    assert response["code"] == "INVALID_PARAMS"
    connection.assert_not_called()


def test_unavailable_visualarq_is_a_structured_error():
    from rhinoclaw.tools.visualarq_persistence import (
        va_validate_persistence_readiness,
    )

    rhino = _rhino({
        "available": False,
        "status": "unavailable",
        "message": "VisualARQ not available",
    })
    with patch(PATCH, return_value=rhino):
        response = json.loads(va_validate_persistence_readiness(
            MagicMock(), [OBJECT_ID]
        ))

    assert response["success"] is False
    assert response["code"] == "RHINO_ERROR"
    assert "va_status" in response["message"]


def test_read_only_body_may_retry_once_after_cold_missing_result_marker():
    from rhinoclaw.tools.visualarq_persistence import (
        va_validate_persistence_readiness,
    )

    rhino = MagicMock()
    rhino.send_command.side_effect = [
        "Script successfully executed! Print output: VA_LOAD_PROBE:ready",
        "Script successfully executed! Print output: ",
        _wire(_result()),
    ]
    with patch(PATCH, return_value=rhino):
        response = json.loads(va_validate_persistence_readiness(
            MagicMock(), [OBJECT_ID]
        ))

    assert response["success"] is True
    assert response["data"]["bootstrap_retry_attempted"] is True
    assert rhino.send_command.call_count == 3
    assert (
        rhino.send_command.call_args_list[1][0][1]["code"]
        == rhino.send_command.call_args_list[2][0][1]["code"]
    )


def test_generated_body_is_recursive_bounded_and_has_no_mutation_path():
    from rhinoclaw.tools.visualarq_persistence import (
        _PERSISTENCE_READINESS_BODY,
    )

    ast.parse(_PERSISTENCE_READINESS_BODY)
    for required in (
        "va_exact_method_shape",
        "IsProduct",
        "Rhino.DocObjects.InstanceObject",
        "rg.InstanceReferenceGeometry",
        "ParentIdefId",
        "IsSystemComponent",
        "*EMPTYDEFINITION",
        "ObjectCount",
        "GetObjects",
        "IsInstanceDefinitionObject",
        "definition_cycle",
        "max_depth",
        "max_nodes",
        "max_definitions",
    ):
        assert required in _PERSISTENCE_READINESS_BODY
    for forbidden in (
        "sc.doc.Objects.Add",
        "sc.doc.Objects.Delete",
        "sc.doc.InstanceDefinitions.Add",
        "sc.doc.InstanceDefinitions.Delete",
        "RhinoApp.Wait",
        "WriteFile",
        "SaveAs",
    ):
        assert forbidden not in _PERSISTENCE_READINESS_BODY


def test_tool_is_registered_and_reexported():
    import asyncio

    import rhinoclaw

    registered = {
        tool.name for tool in asyncio.run(rhinoclaw.mcp.list_tools())
    }
    assert "va_validate_persistence_readiness" in registered
    assert callable(rhinoclaw.va_validate_persistence_readiness)
