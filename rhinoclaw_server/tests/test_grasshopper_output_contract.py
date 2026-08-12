"""Contracts for lossless Grasshopper output identity and Data Trees."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT / "rhinoclaw_plugin" / "Functions" /
    "GrasshopperApiOperations.cs"
)


def test_csharp_output_reader_preserves_identity_paths_and_nulls():
    source = SOURCE.read_text(encoding="utf-8")

    assert 'schema_version = 2' in source
    assert '["component_instance_id"] = component.InstanceGuid.ToString()' \
        in source
    assert '["output_instance_id"] = output.InstanceGuid.ToString()' \
        in source
    assert '["paths"] = paths' in source
    assert '["indices"] = new JArray(path.Indices)' in source
    assert '["items"] = branchItems' in source
    assert 'valueToken = JValue.CreateNull()' in source
    assert 'val ?? "null"' not in source
    assert 'if (outputs.ContainsKey(key))\n                        continue;' \
        not in source


def test_csharp_output_targets_resolve_before_bake_mutation():
    source = SOURCE.read_text(encoding="utf-8")
    bake_start = source.index("public JObject BakeGrasshopper")
    output_start = source.index("public JObject GetGrasshopperOutputs")
    bake_source = source[bake_start:output_start]

    assert "ResolveGhBakeTargets(" in bake_source
    assert bake_source.index("ResolveGhBakeTargets(") < \
        bake_source.index("// Get or create target layer")
    assert "component_names and output_targets are mutually exclusive" \
        in source
    assert "ResolveExactGhOutputTargets" in source
    assert '["component_instance_id"] =' in bake_source
    assert '["output_instance_id"] = output.InstanceGuid.ToString()' \
        in bake_source


def test_csharp_output_reader_covers_standalone_params_and_exact_targets():
    source = SOURCE.read_text(encoding="utf-8")

    assert "else if (obj is IGH_Param standaloneOutput" in source
    assert "EnumerateGhOutputs(ghDoc, true)" in source
    assert '"output_names and output_targets are mutually exclusive"' \
        in source
    assert 'target.IsStandalone\n                ? "standalone_parameter"' \
        in source
    assert '["output_instance_id"] = standaloneOutput.InstanceGuid.ToString()' \
        in source


def test_python_wrapper_retains_v2_tree_and_disambiguated_outputs():
    from rhinoclaw.tools.get_grasshopper_outputs import (
        get_grasshopper_outputs,
    )

    first = {
        "key": "A.R",
        "legacy_key": "A.R",
        "key_disambiguated": False,
        "component": "A",
        "component_instance_id": "component-1",
        "output": "R",
        "output_instance_id": "output-1",
        "access": "tree",
        "values": [[1.0, None], [2.0]],
        "paths": [
            {
                "path": "{0;2}",
                "indices": [0, 2],
                "count": 2,
                "values": [1.0, None],
                "items": [
                    {"index": 0, "value": 1.0, "is_null": False},
                    {"index": 1, "value": None, "is_null": True},
                ],
            },
            {
                "path": "{3}",
                "indices": [3],
                "count": 1,
                "values": [2.0],
                "items": [
                    {"index": 0, "value": 2.0, "is_null": False},
                ],
            },
        ],
        "path_count": 2,
        "count": 3,
    }
    second_key = "A.R [component-2/output-2]"
    payload = {
        "definition_id": "definition-1",
        "schema_version": 2,
        "outputs": {
            "A.R": first,
            second_key: {
                **first,
                "key": second_key,
                "key_disambiguated": True,
                "component_instance_id": "component-2",
                "output_instance_id": "output-2",
            },
        },
        "output_count": 2,
        "identity": "component_instance_id + output_instance_id",
    }
    rhino = MagicMock()
    rhino.send_command.return_value = payload

    with patch(
        "rhinoclaw.tools.get_grasshopper_outputs.get_rhino_connection",
        return_value=rhino,
    ):
        result = json.loads(get_grasshopper_outputs(
            MagicMock(), "definition-1"))

    assert result["success"] is True
    data = result["data"]
    assert data["schema_version"] == 2
    assert data["output_count"] == 2
    assert list(data["outputs"]) == ["A.R", second_key]
    assert data["outputs"]["A.R"]["paths"][0]["indices"] == [0, 2]
    assert data["outputs"]["A.R"]["paths"][0]["values"][1] is None
    assert data["outputs"][second_key]["key_disambiguated"] is True
