"""Tests for the GH component catalog + lookup (ground truth for authoring)."""
import json
from unittest.mock import MagicMock


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


def test_canonical_number_slider_guid():
    data = _search(query="Number Slider")["data"]
    best = data["matches"][0]
    # The canonical, version-stable GUID agents must use for sliders.
    assert best["guid"] == "57da07bd-ecab-415d-9d86-af36d7073abc"


def test_extrude_lookup_returns_ports():
    data = _search(query="Extrude")["data"]
    best = data["matches"][0]
    assert best["name"] == "Extrude"
    in_names = {p["n"] for p in best["in"]}
    assert {"Base", "Direction"} <= in_names
    assert best["out"][0]["t"] == "Geometry"


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
