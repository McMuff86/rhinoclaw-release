"""Source and pure-function gates for the scratch GH catalog generator."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "rhinoclaw_server" / "scripts" / "generate_gh_catalog.py"


def _module():
    spec = importlib.util.spec_from_file_location("generate_gh_catalog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_assemble_catalog_is_complete_sorted_hashed_and_atomic(tmp_path):
    generator = _module()
    jsonl = tmp_path / "work" / "gh_components.jsonl"
    jsonl.parent.mkdir()
    entries = [
        {
            "guid": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "name": "B",
            "cat": "Test",
            "ports_skipped": "instantiation hangs",
        },
        {
            "guid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "name": "A",
            "cat": "Test",
            "instantiated": True,
            "in": [{"n": "X", "nn": "x", "t": "Number"}],
            "out": [],
        },
    ]
    jsonl.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries),
        encoding="utf-8",
    )
    output = tmp_path / "static" / "catalog.json"

    catalog = generator._assemble_catalog(
        jsonl,
        output,
        rhino_version="8.test",
        expected_count=2,
    )

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == catalog
    assert [entry["name"] for entry in catalog["components"]] == ["A", "B"]
    assert catalog["meta"]["component_count"] == 2
    assert catalog["meta"]["ports_skipped_guids"] == [
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    ]
    assert len(catalog["meta"]["proxy_guid_sha256"]) == 64
    assert len(catalog["meta"]["component_contract_sha256"]) == 64
    assert list(output.parent.glob(".*.tmp")) == []


def test_assemble_catalog_refuses_incomplete_or_duplicate_jsonl(tmp_path):
    generator = _module()
    jsonl = tmp_path / "catalog.jsonl"
    entry = {"guid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "name": "A"}
    jsonl.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    try:
        generator._assemble_catalog(
            jsonl, tmp_path / "out.json", rhino_version="8", expected_count=2
        )
    except ValueError as exc:
        assert "live runtime has 2 proxies" in str(exc)
    else:
        raise AssertionError("incomplete JSONL was accepted")

    jsonl.write_text(
        json.dumps(entry) + "\n" + json.dumps(entry) + "\n",
        encoding="utf-8",
    )
    try:
        generator._assemble_catalog(
            jsonl, tmp_path / "out.json", rhino_version="8", expected_count=2
        )
    except ValueError as exc:
        assert "duplicate catalog GUID" in str(exc)
    else:
        raise AssertionError("duplicate GUID was accepted")


def test_pending_marker_only_skips_an_unwritten_proxy(tmp_path):
    generator = _module()
    marker = tmp_path / "marker.txt"
    marker.write_text("5|ABCDEF|Risky Component", encoding="utf-8")

    assert generator._pending_marker_guid(marker, 5) == "abcdef"
    assert generator._pending_marker_guid(marker, 6) is None


def test_generator_has_no_user_path_or_fixed_proxy_total():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "YourName" not in source
    assert "total = 2639" not in source
    assert "expected_count" in source
    assert "os.replace(temp_name, output_path)" in source
    assert "catalog_contract(catalog)" in source


def test_remote_chunk_records_exactly_one_line_for_broken_proxy_metadata():
    generator = _module()
    chunk = generator._CHUNK_CODE

    assert "entry = {'proxy_index': index}" in chunk
    assert "'descriptor_error':" in chunk
    assert "'obsolete_read_error'" in chunk
    assert "'serialization_error':" in chunk
    assert "out_file.write(encoded + '\\n')" in chunk
    assert "marker_file.write(str(index) + '|' + guid_text)" in chunk
    assert "entry.get('name', guid_text)" not in chunk
    assert "JsonConvert.SerializeObject(entry)" in chunk
    assert "clr.AddReference('Newtonsoft.Json')" in chunk
    assert "except BaseException as exc:" in chunk
    assert "Exactly one line per proxy" in chunk
    assert "except:\n            errors += 1\n        index += 1" not in chunk
