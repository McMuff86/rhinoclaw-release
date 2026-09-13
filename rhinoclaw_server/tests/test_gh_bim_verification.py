"""BIM contracts cannot be satisfied by successful geometry-only baking."""

import copy
import json
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.tools.bake_grasshopper import bake_grasshopper
from rhinoclaw.utils.gh_bim_verification import verify_bim_bake


OBJECT = "11111111-1111-1111-1111-111111111111"
SECOND = "22222222-2222-2222-2222-222222222222"
STYLE = "33333333-3333-3333-3333-333333333333"
HOST = "44444444-4444-4444-4444-444444444444"
TARGETS = [{"component_instance_id": SECOND, "output_instance_id": STYLE}]


def product(object_id=OBJECT, kind="wall", **overrides):
    snapshot = {
        "id": object_id, "kind": kind, "classifications": [kind],
        "classification_complete": True, "classification_errors": [],
        "readback_complete": True, "readback_errors": [], "style_id": STYLE,
    }
    snapshot.update(overrides)
    return json.dumps({"success": True, "data": {"object": snapshot}})


def expectation(kind="wall", **overrides):
    result = {"kind": kind, "count": None, "style_id": None, "host_id": None}
    result.update(overrides)
    return result


@pytest.mark.parametrize("kind", ["wall", "slab", "space", "door", "window"])
def test_all_five_native_bim_categories(kind):
    reader = MagicMock(side_effect=lambda oid, k: product(oid, k, host_id=HOST))
    result = verify_bim_bake([OBJECT], expectation(kind, count=1, style_id=STYLE), reader)
    assert result["pass"] is True
    if kind in {"door", "window"}:
        reader.assert_any_call(HOST, "wall")
        assert result["hosts"][0]["pass"] is True
    else:
        assert result["hosts"] == []
    assert "opening_host_cut" in result["unmeasured"]


@pytest.mark.parametrize("overrides", [
    {"id": SECOND}, {"kind": "slab"}, {"classifications": []},
    {"classification_complete": False}, {"classification_complete": 1},
    {"classification_errors": [{"error": "missing API"}]},
    {"readback_complete": False}, {"readback_errors": ["no wall path"]},
    {"style_id": None}, {"style_id": "00000000-0000-0000-0000-000000000000"},
])
def test_incomplete_or_wrong_identity_fails(overrides):
    result = verify_bim_bake([OBJECT], expectation(), lambda *_: product(**overrides))
    assert result["pass"] is False
    assert result["issues"]


@pytest.mark.parametrize("response", [
    json.dumps({"success": False, "message": "Object is not a VisualARQ product"}),
    json.dumps({"success": True, "data": {"available": False}}),
    json.dumps({"success": True, "data": {"object": None}}),
    "not JSON", "[]",
])
def test_brep_missing_plugin_or_malformed_readback_fails(response):
    result = verify_bim_bake([OBJECT], expectation(), lambda *_: response)
    assert result["pass"] is False


def test_timeout_is_evidence_and_remaining_objects_are_still_checked():
    reader = MagicMock(side_effect=[TimeoutError("UI busy"), product(SECOND)])
    result = verify_bim_bake([OBJECT, SECOND], expectation(), reader)
    assert result["pass"] is False
    assert len(result["objects"]) == 2
    assert result["objects"][1]["pass"] is True
    assert "UI busy" in result["issues"][0]


def test_count_and_style_expectations_fail_independently():
    result = verify_bim_bake([OBJECT], expectation(count=2, style_id=HOST),
                             lambda *_: product())
    assert result["pass"] is False
    assert len(result["issues"]) == 2


def test_empty_batch_never_passes():
    reader = MagicMock()
    assert verify_bim_bake([], expectation(), reader)["pass"] is False
    reader.assert_not_called()


@pytest.mark.parametrize("host_id", [None, "bad-guid", OBJECT])
def test_opening_requires_independently_readable_wall_host(host_id):
    reader = MagicMock(side_effect=lambda oid, k: product(oid, "window", host_id=host_id))
    result = verify_bim_bake([OBJECT], expectation("window"), reader)
    assert result["pass"] is False


def test_shared_host_read_once_and_expected_host_mismatch_detected():
    reader = MagicMock(side_effect=lambda oid, k: product(oid, k, host_id=HOST))
    result = verify_bim_bake([OBJECT, SECOND], expectation("door", host_id=STYLE), reader)
    assert result["pass"] is False
    assert reader.call_count == 3
    assert len(result["hosts"]) == 1
    assert all("expected_host_id" in row["issues"][0] for row in result["objects"])


@pytest.mark.parametrize("kwargs", [
    {"expected_visualarq_kind": "roof"}, {"expected_visualarq_kind": []},
    {"expected_visualarq_kind": "wall", "expected_count": True},
    {"expected_visualarq_kind": "wall", "expected_count": 0},
    {"expected_visualarq_kind": "wall", "expected_count": 1.5},
    {"expected_visualarq_kind": "wall", "expected_style_id": "bad"},
    {"expected_visualarq_kind": "wall", "expected_host_id": HOST},
    {"expected_visualarq_kind": "door", "expected_host_id": "bad"},
    {"expected_style_id": STYLE}, {"expected_count": 1},
])
def test_invalid_contract_rejected_without_connection(kwargs):
    with patch("rhinoclaw.tools.bake_grasshopper.get_rhino_connection") as connect:
        result = json.loads(bake_grasshopper(None, "loaded", output_targets=TARGETS, **kwargs))
    assert result["success"] is False
    assert result["code"] == "INVALID_PARAMS"
    connect.assert_not_called()


def test_bim_requires_exact_targets_before_connection():
    with patch("rhinoclaw.tools.bake_grasshopper.get_rhino_connection") as connect:
        result = json.loads(bake_grasshopper(None, "loaded", expected_visualarq_kind="wall"))
    assert result["code"] == "INVALID_PARAMS"
    connect.assert_not_called()


def invoke_bake(readback, guarded=True, count=1):
    rhino = MagicMock()
    bake = {
        "baked_count": 1, "baked_objects": [{"id": OBJECT}], "layer": "BIM",
        "guarded_bake_aware": guarded, "bake_mode": "guarded_bake_aware",
        "bake_status": "success",
    }
    rhino.send_command.side_effect = [copy.deepcopy(bake), {
        "count": 1, "missing_count": 0, "results": [{"id": OBJECT}], "missing": [],
    }]
    with patch("rhinoclaw.tools.bake_grasshopper.get_rhino_connection", return_value=rhino), \
         patch("rhinoclaw.tools.bake_grasshopper.va_get_object", return_value=readback) as reader:
        response = json.loads(bake_grasshopper(
            None, "loaded", output_targets=TARGETS, layer="BIM",
            expected_visualarq_kind="wall", expected_count=count, expected_style_id=STYLE,
        ))
    return response, rhino, reader


def test_wrapper_demands_native_route_and_independent_semantics():
    result, rhino, reader = invoke_bake(product())
    assert result["success"] is True
    assert result["data"]["bim_verification"]["pass"] is True
    assert result["data"]["verification"]["pass"] is True
    assert rhino.send_command.call_args_list[0].args[1]["require_bake_aware"] is True
    reader.assert_called_once_with(None, object_id=OBJECT, expected_kind="wall")


@pytest.mark.parametrize("kwargs", [
    {"readback": product(kind="slab")}, {"readback": product(), "guarded": False},
    {"readback": product(), "count": 2},
])
def test_post_bake_failure_retains_ids_without_retry_or_cleanup(kwargs):
    result, rhino, _ = invoke_bake(**kwargs)
    assert result["success"] is False
    assert result["code"] == "PARTIAL_MUTATION"
    assert result["data"]["baked_objects"] == [{"id": OBJECT}]
    assert result["data"]["verification"]["pass"] is False
    assert [call.args[0] for call in rhino.send_command.call_args_list] == [
        "bake_grasshopper", "get_objects_info",
    ]


def test_csharp_semantic_guard_precedes_any_layer_mutation():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "rhinoclaw_plugin" /
              "Functions" / "GrasshopperApiOperations.cs").read_text(encoding="utf-8")
    body = source[source.index("public JObject BakeGrasshopper("):]
    assert body.index("if (requireBakeAware") < body.index("doc.Layers.Add(layer)")
    assert "geometry fallback is disabled" in body
