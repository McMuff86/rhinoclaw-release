"""Tests for the GH spec linter (fail before the round-trip)."""
import json
from unittest.mock import MagicMock

from rhinoclaw.utils.gh_lint import lint_definition

EXTRUDE_GUID = "962034e9-cc27-4394-afc4-5c16e3447cf9"  # from the catalog


def _lint(components, wires=None):
    from rhinoclaw.tools.validate_gh_definition import validate_gh_definition
    return json.loads(validate_gh_definition(
        MagicMock(), components, wires))["data"]


def test_valid_native_spec_passes():
    data = _lint(
        [{"type": "slider", "name": "Width", "default": 200, "min": 10,
          "max": 1000},
         {"type": "sdk_component", "guid": EXTRUDE_GUID, "name": "Extr"}],
        [{"from": "Width", "to": "Extr", "to_input": "Direction"}],
    )
    assert data["valid"] is True
    assert data["errors"] == []
    assert data["warnings"] == []  # native-only: no headless warning


def test_hallucinated_guid_caught_with_lookup_hint():
    data = _lint([{"type": "sdk_component",
                   "guid": "12345678-dead-beef-0000-000000000000",
                   "name": "X"}])
    assert data["valid"] is False
    assert any("find_gh_component" in e for e in data["errors"])


def test_wrong_port_name_lists_known_ports():
    data = _lint(
        [{"type": "slider", "name": "W"},
         {"type": "sdk_component", "guid": EXTRUDE_GUID, "name": "Extr"}],
        [{"from": "W", "to": "Extr", "to_input": "Vector"}],  # heißt Direction
    )
    assert data["valid"] is False
    [err] = [e for e in data["errors"] if "no input 'Vector'" in e]
    assert "Direction" in err  # the fix is in the message


def test_wire_to_unknown_component_and_index_out_of_range():
    data = _lint(
        [{"type": "slider", "name": "W"},
         {"type": "sdk_component", "guid": EXTRUDE_GUID, "name": "Extr"}],
        [{"from": "W", "to": "Nope", "to_input": 0},
         {"from": "W", "to": "Extr", "to_input": 7}],
    )
    assert data["valid"] is False
    assert any("'Nope' does not exist" in e for e in data["errors"])
    assert any("out of range" in e for e in data["errors"])


def test_rh_out_script_output_is_an_error_and_headless_warns():
    data = _lint([{"type": "python3_script", "name": "S", "code": "a=1",
                   "inputs": ["Width"], "extra_outputs": ["RH_OUT:Frame"]}])
    assert data["valid"] is False
    assert any("RH_OUT" in e for e in data["errors"])
    assert any("headless" in w for w in data["warnings"])


def test_duplicate_names_and_missing_fields():
    data = _lint([
        {"type": "slider", "name": "A"},
        {"type": "slider", "name": "A"},
        {"type": "python3_script", "name": "S"},   # code fehlt
        {"type": "frobnicator", "name": "F"},      # unbekannter Typ
    ])
    assert data["valid"] is False
    assert any("duplicate" in e for e in data["errors"])
    assert any("missing required field 'code'" in e for e in data["errors"])
    assert any("unknown type" in e for e in data["errors"])


def test_wiring_into_a_slider_is_an_error():
    data = _lint(
        [{"type": "slider", "name": "A"}, {"type": "slider", "name": "B"}],
        [{"from": "A", "to": "B", "to_input": 0}],
    )
    assert data["valid"] is False
    assert any("accepts no wire inputs" in e for e in data["errors"])


def test_script_from_output_validated():
    data = _lint(
        [{"type": "python3_script", "name": "S", "code": "a=1",
          "extra_outputs": ["b"]},
         {"type": "preview", "name": "P"}],
        [{"from": "S", "from_output": "c", "to": "P", "to_input": "Geometry"}],
    )
    assert data["valid"] is False
    assert any("no output 'c'" in e for e in data["errors"])


def test_slider_default_outside_range_warns():
    data = _lint([{"type": "slider", "name": "W", "default": 5000,
                   "min": 0, "max": 100}])
    assert data["valid"] is True
    assert any("outside" in w for w in data["warnings"])


def test_guid_empty_catalog_entry_is_not_authorable():
    data = _lint([{
        "type": "sdk_component",
        "guid": "00000000-0000-0000-0000-000000000000",
        "name": "UnsafeBake",
    }])
    assert data["valid"] is False
    assert any("guid_empty" in error for error in data["errors"])


def test_ports_skipped_catalog_entry_is_not_authorable():
    guid = "22222222-2222-2222-2222-222222222222"
    catalog = {
        "components": [{
            "guid": guid,
            "name": "Synthetic skipped proxy",
            "ports_skipped": "synthetic introspection timeout",
        }],
    }
    data = lint_definition([{
        "type": "sdk_component",
        "guid": guid,
        "name": "Pipeline",
    }], catalog=catalog)
    assert data["valid"] is False
    assert any("ports_skipped" in error for error in data["errors"])


def test_lint_does_not_mutate_component_specs_with_catalog_internals():
    from copy import deepcopy

    from rhinoclaw.tools.find_gh_component import _catalog

    component = {
        "type": "sdk_component",
        "name": "Box",
        "guid": "28061aae-04fb-4cb5-ac45-16f3b66bc0a4",
    }
    components = [component]
    before = deepcopy(components)

    result = lint_definition(components, [], catalog=_catalog())

    assert result["valid"] is True
    assert components == before
    assert "_catalog" not in component


def test_instantiate_failure_and_missing_proof_are_not_authorable():
    failed_guid = "11111111-2222-3333-4444-555555555555"
    unverified_guid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    catalog = {"components": [
        {
            "guid": failed_guid,
            "name": "Failed",
            "instantiate_error": "CreateInstance raised FixtureError",
        },
        {"guid": unverified_guid, "name": "Unverified"},
    ]}
    result = lint_definition([
        {"type": "sdk_component", "guid": failed_guid, "name": "Failed"},
        {
            "type": "sdk_component",
            "guid": unverified_guid,
            "name": "Unverified",
        },
    ], catalog=catalog)

    assert result["valid"] is False
    assert any("instantiation_failed" in error for error in result["errors"])
    assert any(
        "instantiation_unverified" in error for error in result["errors"]
    )
