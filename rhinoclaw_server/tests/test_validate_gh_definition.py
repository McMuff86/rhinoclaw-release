"""Tests for the GH spec linter (fail before the round-trip)."""
import json
from unittest.mock import MagicMock

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
