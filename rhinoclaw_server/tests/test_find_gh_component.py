"""Tests for the GH component catalog + lookup (ground truth for authoring)."""
import json
from unittest.mock import MagicMock

import pytest


def _search(**kwargs):
    from rhinoclaw.tools.find_gh_component import find_gh_component
    return json.loads(find_gh_component(MagicMock(), **kwargs))


def test_catalog_structure_gate():
    """CI gate: the shipped catalog parses and is substantial."""
    from rhinoclaw.tools.find_gh_component import _catalog

    catalog = _catalog()
    components = catalog["components"]
    assert len(components) > 2000
    with_ports = sum(1 for c in components if "in" in c)
    assert with_ports / len(components) > 0.8  # ports are the value
    assert catalog["meta"]["component_count"] == len(components)
    # every entry has the core identity fields
    sample = components[0]
    for key in ("guid", "name", "cat"):
        assert key in sample


def test_catalog_contract_is_deterministic_and_runtime_checkable():
    from rhinoclaw.tools.find_gh_component import _catalog
    from rhinoclaw.utils.gh_catalog import catalog_contract

    catalog = _catalog()
    first = catalog_contract(catalog)
    second = catalog_contract({
        "meta": dict(catalog["meta"]),
        "components": list(reversed(catalog["components"])),
    })

    assert first == second
    assert first["schema_version"] == 1
    assert first["component_count"] == len(catalog["components"])
    assert len(first["proxy_guid_sha256"]) == 64
    assert len(first["component_contract_sha256"]) == 64
    assert first["used_components"] == []


def test_catalog_contract_selects_exact_used_components_and_fails_closed():
    from rhinoclaw.tools.find_gh_component import _catalog
    from rhinoclaw.utils.gh_catalog import catalog_contract

    slider_guid = "57DA07BD-ECAB-415D-9D86-AF36D7073ABC"
    contract = catalog_contract(_catalog(), [slider_guid])

    assert [entry["guid"].lower() for entry in contract["used_components"]] == [
        slider_guid.lower()
    ]
    with pytest.raises(ValueError, match="missing from catalog"):
        catalog_contract(
            _catalog(), ["11111111-2222-3333-4444-555555555555"]
        )


def test_authoring_catalog_contract_ignores_builtins_and_selects_sdk():
    from rhinoclaw.tools.find_gh_component import _catalog
    from rhinoclaw.utils.gh_catalog import authoring_catalog_contract

    contract = authoring_catalog_contract(_catalog(), [
        {"type": "slider", "name": "Width"},
        {
            "type": "sdk_component",
            "name": "Box",
            "guid": "28061aae-04fb-4cb5-ac45-16f3b66bc0a4",
        },
    ])

    assert [entry["guid"] for entry in contract["used_components"]] == [
        "28061aae-04fb-4cb5-ac45-16f3b66bc0a4"
    ]


def test_canonical_number_slider_guid():
    data = _search(query="Number Slider")["data"]
    best = data["matches"][0]
    # The canonical, version-stable GUID agents must use for sliders.
    assert best["guid"] == "57da07bd-ecab-415d-9d86-af36d7073abc"
    assert data["catalog"]["runtime_validation"] == \
        "required_before_authoring"
    assert len(data["catalog"]["proxy_guid_sha256"]) == 64


def test_extrude_lookup_returns_ports():
    data = _search(query="Extrude")["data"]
    best = data["matches"][0]
    assert best["name"] == "Extrude"
    in_names = {p["n"] for p in best["in"]}
    assert {"Base", "Direction"} <= in_names
    assert best["out"][0]["t"] == "Geometry"
    assert best["authorable"] is True
    assert best["issues"] == []


def test_description_search_and_category_filter():
    data = _search(query="solid difference", category="Intersect")["data"]
    assert any("Difference" in m["name"] for m in data["matches"])
    assert all(m["cat"] == "Intersect" for m in data["matches"])


def test_obsolete_excluded_by_default():
    data = _search(query="slider", limit=50)["data"]
    assert all(not m.get("obsolete") for m in data["matches"])


def test_miss_returns_hint_and_categories():
    data = _search(query="zzz-gibts-nicht-xyz")["data"]
    assert data["matches"] == []
    assert "hint" in data
    assert "Curve" in data["categories"]


def test_empty_query_rejected():
    result = _search(query="  ")
    assert result["success"] is False


def test_csg_query_prefers_canonical_solid_difference():
    """'boolean difference' must rank Solid Difference above plugin
    components with longer names (token match + shorter-name tie-break)."""
    data = _search(query="solid difference")["data"]
    assert data["matches"][0]["name"] == "Solid Difference"


def test_guid_empty_bake_objects_is_not_recommended():
    data = _search(query="Bake Objects", limit=20)["data"]
    assert data["matches"][0]["guid"] == (
        "952406ae-3c7c-4bec-9f73-13b48f514fcf"
    )
    assert all(
        match["guid"] != "00000000-0000-0000-0000-000000000000"
        for match in data["matches"]
    )
    assert data["excluded_unauthorable"] >= 1

    diagnostic = _search(
        query="Bake Objects", limit=20, include_unauthorable=True,
    )["data"]
    zero_guid = next(
        match for match in diagnostic["matches"]
        if match["guid"] == "00000000-0000-0000-0000-000000000000"
    )
    assert zero_guid["authorable"] is False
    assert "guid_empty" in {issue["code"] for issue in zero_guid["issues"]}


def test_ports_skipped_component_is_filtered_or_clearly_marked(monkeypatch):
    import rhinoclaw.tools.find_gh_component as finder

    skipped_guid = "11111111-2222-4333-8444-555555555555"
    monkeypatch.setattr(finder, "_catalog_cache", {
        "meta": {"component_count": 1, "generated": "test"},
        "components": [{
            "guid": skipped_guid,
            "name": "VisualARQ Pipeline",
            "nick": "VARQAll",
            "cat": "Params",
            "sub": "Architectural objects",
            "desc": "Get all VisualARQ objects in document",
            "ports_skipped": "instantiation hangs",
        }],
    })
    data = _search(query="VisualARQ Pipeline", limit=20)["data"]
    assert all(match["guid"] != skipped_guid for match in data["matches"])
    assert data["excluded_unauthorable"] >= 1

    diagnostic = _search(
        query="VisualARQ Pipeline", limit=20, include_unauthorable=True,
    )["data"]
    skipped = next(
        match for match in diagnostic["matches"]
        if match["guid"] == skipped_guid
    )
    assert skipped["authorable"] is False
    assert "ports_skipped" in {
        issue["code"] for issue in skipped["issues"]
    }


def test_instantiate_failure_is_fail_closed(monkeypatch):
    import rhinoclaw.tools.find_gh_component as finder

    failed_guid = "11111111-2222-3333-4444-555555555555"
    monkeypatch.setattr(finder, "_catalog_cache", {
        "meta": {"component_count": 1, "generated": "test"},
        "components": [{
            "guid": failed_guid,
            "name": "Failed Fixture",
            "nick": "Failed",
            "cat": "Test",
            "desc": "fixture",
            "instantiate_error": "CreateInstance raised FixtureError",
        }],
    })

    data = _search(query="Failed Fixture")["data"]
    assert data["matches"] == []
    assert data["excluded_unauthorable"] == 1

    diagnostic = _search(
        query="Failed Fixture", include_unauthorable=True,
    )["data"]["matches"][0]
    assert diagnostic["authorable"] is False
    assert [issue["code"] for issue in diagnostic["issues"]] == [
        "instantiation_failed",
    ]
