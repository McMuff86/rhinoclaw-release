import copy
import json
from unittest.mock import patch

import pytest

from rhinoclaw.tools.visualarq_bim import (
    _critique,
    _finalize_snapshot,
    _snapshot_delta,
    _validate_expectations,
    _validate_snapshot,
    va_bim_snapshot,
    va_critique_bim,
)


def _source_verification():
    return {
        "hierarchy": {"pass": True},
        "styles": {"read_complete": True},
        "objects": {
            "scan_complete": True,
            "truncated": False,
            "matched_count": 0,
            "returned_count": 0,
        },
        "product_level_contract": {
            "authoritative_link_available": False,
        },
    }


def _raw_snapshot(*, buildings=None, levels=None, styles=None, objects=None):
    return {
        "document": {
            "runtime_serial_number": 42,
            "units": "Millimeters",
            "absolute_tolerance": 0.01,
        },
        "visualarq": {"version": "3.11.0.15030"},
        "buildings": buildings or [],
        "levels": levels or [],
        "styles": styles or [],
        "visualarq_objects": objects or [],
        "source_verification": _source_verification(),
    }


def _house_state():
    level_id = "10000000-0000-0000-0000-000000000001"
    building_id = "20000000-0000-0000-0000-000000000001"
    style_id = "30000000-0000-0000-0000-000000000001"
    wall_id = "40000000-0000-0000-0000-000000000001"
    building = {
        "id": building_id,
        "name": "RHINOCLAW_HOUSE_V1",
        "elevation": 0.0,
        "level_ids": [level_id],
        "readback_complete": True,
    }
    level = {
        "id": level_id,
        "name": "Ground",
        "elevation": 0.0,
        "owner_building_id": building_id,
        "owner_building_name": "RHINOCLAW_HOUSE_V1",
        "readback_complete": True,
    }
    style = {
        "id": style_id,
        "name": "RC_HOUSE_EXT_350",
        "inventory_method": "GetAllWallStyleIds",
        "component_ids": ["50000000-0000-0000-0000-000000000001"],
        "readback_complete": True,
    }
    wall = {
        "id": wall_id,
        "kind": "wall",
        "name": "W01",
        "style_id": style_id,
        "style_name": "RC_HOUSE_EXT_350",
        "height": 2750.0,
        "thickness": 350.0,
        "alignment": {"name": "Center", "value": 1},
        "path": {
            "start": [0.0, 0.0, 0.0],
            "end": [5000.0, 0.0, 0.0],
            "length": 5000.0,
        },
        "quantity": {
            "source": "instance_definition_solid_geometry",
            "volume": 4_812_500_000.0,
            "volume_verified": True,
        },
        "geometry": {
            "bbox_min": [0.0, -175.0, 0.0],
            "bbox_max": [5000.0, 175.0, 2750.0],
        },
        "readback_complete": True,
    }
    return building, level, style, wall


def test_snapshot_hashes_are_entity_derived_and_tamper_detected():
    snapshot = _finalize_snapshot(_raw_snapshot())
    assert snapshot["complete"] is True
    assert snapshot["baseline_eligibility"]["measured_state_comparison"] is True
    assert snapshot["baseline_eligibility"]["gh02_promotion"] is False
    assert _validate_snapshot(snapshot, "snapshot") is snapshot

    tampered = copy.deepcopy(snapshot)
    tampered["inventory_hashes"]["levels"] = "0" * 64
    with pytest.raises(ValueError, match="not inventory-derived"):
        _validate_snapshot(tampered, "snapshot")

    tampered = copy.deepcopy(snapshot)
    tampered["baseline_eligibility"]["gh02_promotion"] = True
    with pytest.raises(ValueError, match="not evidence-derived"):
        _validate_snapshot(tampered, "snapshot")

    tampered = copy.deepcopy(snapshot)
    tampered["verification"]["source"]["hierarchy"][
        "mutation_baseline_complete"
    ] = True
    with pytest.raises(ValueError, match="source_verification_sha256"):
        _validate_snapshot(tampered, "snapshot")


def test_delta_and_semantic_critic_cover_hierarchy_style_metrics_and_datum():
    baseline = _finalize_snapshot(_raw_snapshot())
    building, level, style, wall = _house_state()
    current = _finalize_snapshot(
        _raw_snapshot(
            buildings=[building],
            levels=[level],
            styles=[style],
            objects=[wall],
        )
    )
    delta = _snapshot_delta(baseline, current)
    assert delta["baseline_unchanged"] is True
    assert delta["categories"]["visualarq_objects"]["added_ids"] == [wall["id"]]

    expectations = _validate_expectations(
        {
            "scope": "added",
            "exact_counts": {
                "buildings": 1,
                "levels": 1,
                "styles": 1,
                "visualarq_objects": 1,
                "objects_by_kind": {"wall": 1},
            },
            "buildings": [
                {
                    "name": "RHINOCLAW_HOUSE_V1",
                    "elevation": 0.0,
                    "level_names": ["Ground"],
                }
            ],
            "levels": [
                {
                    "name": "Ground",
                    "elevation": 0.0,
                    "building_name": "RHINOCLAW_HOUSE_V1",
                }
            ],
            "styles": [
                {"name": "RC_HOUSE_EXT_350", "kind": "wall", "component_count": 1}
            ],
            "visualarq_objects": [
                {
                    "kind": "wall",
                    "name": "W01",
                    "style_name": "RC_HOUSE_EXT_350",
                    "height": 2750.0,
                    "thickness": 350.0,
                    "volume": 4_812_500_000.0,
                    "alignment": "centered",
                    "datum_level_name": "Ground",
                    "path_start": [0.0, 0.0, 0.0],
                    "path_end": [5000.0, 0.0, 0.0],
                }
            ],
        },
        baseline_present=True,
    )
    verdict = _critique(current, expectations, baseline)
    assert verdict["pass"] is True
    assert verdict["failed_checks"] == []
    assert verdict["level_semantics"]["authoritative_object_link_available"] is False


def test_critic_refuses_to_invent_authoritative_product_level_link():
    baseline = _finalize_snapshot(_raw_snapshot())
    building, level, style, wall = _house_state()
    current = _finalize_snapshot(
        _raw_snapshot(
            buildings=[building], levels=[level], styles=[style], objects=[wall]
        )
    )
    expectations = _validate_expectations(
        {
            "scope": "added",
            "visualarq_objects": [
                {
                    "kind": "wall",
                    "authoritative_level_id": level["id"],
                }
            ],
        },
        baseline_present=True,
    )
    verdict = _critique(current, expectations, baseline)
    assert verdict["pass"] is False
    assert verdict["failed_checks"] == [
        "semantic_match.visualarq_objects"
    ]


def test_critic_can_require_and_reject_incomplete_gh02_level_inventory():
    baseline = _finalize_snapshot(_raw_snapshot())
    expectations = _validate_expectations(
        {
            "scope": "added",
            "require_promotion_baseline": True,
            "exact_counts": {"visualarq_objects": 0},
        },
        baseline_present=True,
    )
    verdict = _critique(baseline, expectations, baseline)
    assert verdict["pass"] is False
    assert verdict["failed_checks"] == ["gh02_promotion_baseline"]


def test_unverified_wall_formula_is_only_gross_volume():
    building, level, style, wall = _house_state()
    wall["quantity"]["volume_verified"] = False
    wall["quantity"]["volume"] = None
    snapshot = _finalize_snapshot(
        _raw_snapshot(
            buildings=[building], levels=[level], styles=[style], objects=[wall]
        )
    )
    metrics = snapshot["entities"]["visualarq_objects"][0]["metrics"]
    assert metrics["volume"] is None
    assert metrics["volume_verified"] is False
    assert metrics["gross_volume"] == 4_812_500_000.0


def test_snapshot_tool_returns_verification_failure_for_incomplete_inventory():
    incomplete = _finalize_snapshot(_raw_snapshot())
    incomplete["complete"] = False
    incomplete["verification"]["issues"] = ["object scan failed"]
    with patch(
        "rhinoclaw.tools.visualarq_bim.get_rhino_connection",
        return_value=object(),
    ), patch(
        "rhinoclaw.tools.visualarq_bim._capture_snapshot",
        return_value=incomplete,
    ):
        response = json.loads(va_bim_snapshot(None))
    assert response["success"] is False
    assert response["code"] == "VERIFICATION_FAILED"


def test_critique_tool_rejects_unknown_expectation_before_rhino():
    with patch("rhinoclaw.tools.visualarq_bim._capture_snapshot") as capture:
        response = json.loads(
            va_critique_bim(None, {"visual_guess": True})
        )
    assert response["success"] is False
    assert response["code"] == "INVALID_PARAMS"
    capture.assert_not_called()
