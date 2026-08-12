"""Offline contracts for the GH runtime-catalog authoring gate."""

from pathlib import Path

import pytest

from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError
from rhinoclaw.utils.gh_catalog import require_catalog_verification


ROOT = Path(__file__).resolve().parents[2]
BUILDER = (
    ROOT / "rhinoclaw_plugin" / "Functions" / "GrasshopperDefinitionBuilder.cs"
)
SERVICE = (
    ROOT / "rhinoclaw_plugin" / "Functions" / "GrasshopperCatalogContract.cs"
)


def _verification(*, global_match=True, pass_value=True):
    return {
        "pass": pass_value,
        "schema_version": 1,
        "global_match": global_match,
        "scope": "full_catalog" if global_match else "used_components_only",
        "authoring_search_complete": global_match,
        "warning": None if global_match else "installed proxy catalog drifted",
        "issues": [] if pass_value else ["used component port mismatch"],
        "evidence": {
            "contract": {
                "schema_version": 1,
                "component_count": 2643 if global_match else 2534,
                "proxy_guid_sha256": (
                    "a" * 64 if global_match else "b" * 64
                ),
                "component_contract_sha256": "c" * 64,
            },
            "runtime": {
                "proxy_count": 2643,
                "proxy_guid_sha256": "a" * 64,
            },
            "used_component_count": 1,
            "used_components": [{
                "guid": "28061aae-04fb-4cb5-ac45-16f3b66bc0a4",
                "requested_instances": 1,
                "verified_instances": 1,
                "proxy_present": True,
                "create_instance_succeeded": True,
                "contract_match": pass_value,
            }],
        },
    }


def test_python_accepts_exact_global_runtime_contract():
    verification = _verification(global_match=True)

    assert require_catalog_verification({
        "status": "success",
        "catalog_verification": verification,
    }) is verification


def test_python_accepts_explicit_used_component_scope_on_global_drift():
    verification = _verification(global_match=False)

    accepted = require_catalog_verification({
        "status": "success",
        "catalog_verification": verification,
    })

    assert accepted["pass"] is True
    assert accepted["global_match"] is False
    assert accepted["scope"] == "used_components_only"
    assert accepted["authoring_search_complete"] is False
    assert accepted["warning"]


def test_python_rejects_used_component_mismatch():
    with pytest.raises(RhinoCommandError) as raised:
        require_catalog_verification({
            "status": "verification_failed",
            "catalog_verification": _verification(
                global_match=False, pass_value=False),
        })

    assert raised.value.error_code == ErrorCode.VERIFICATION_FAILED
    assert "used component port mismatch" in str(raised.value)


def test_python_rejects_old_plugin_success_without_verification():
    with pytest.raises(RhinoCommandError) as raised:
        require_catalog_verification({"status": "success"})

    assert raised.value.error_code == ErrorCode.VERIFICATION_FAILED
    assert "update/restart" in str(raised.value)


def test_python_rejects_contradictory_status_and_global_evidence():
    with pytest.raises(RhinoCommandError, match="result status contradicts"):
        require_catalog_verification({
            "status": "verification_failed",
            "catalog_verification": _verification(global_match=True),
        })

    contradictory = _verification(global_match=True)
    contradictory["evidence"]["runtime"]["proxy_guid_sha256"] = "d" * 64
    with pytest.raises(RhinoCommandError, match="global_match=true"):
        require_catalog_verification({
            "status": "success",
            "catalog_verification": contradictory,
        })


def test_python_rejects_incomplete_used_instance_evidence():
    incomplete = _verification(global_match=False)
    incomplete["evidence"]["used_components"][0]["verified_instances"] = 0

    with pytest.raises(RhinoCommandError, match="unverified used component"):
        require_catalog_verification({
            "status": "success",
            "catalog_verification": incomplete,
        })


def test_csharp_gate_hashes_live_proxies_and_compares_exact_ports():
    source = SERVICE.read_text(encoding="utf-8")

    assert "Instances.ComponentServer?.ObjectProxies?.ToList()" in source
    assert '.ToString("D").ToLowerInvariant()' in source
    assert ".OrderBy(value => value, StringComparer.Ordinal)" in source
    assert 'Encoding.UTF8.GetBytes(string.Join("\\n", values))' in source
    assert '["proxy_count"] = runtimeProxies.Count' in source
    assert '["proxy_guid_sha256"] = runtimeHash' in source
    assert "JToken.DeepEquals(expectedContract, runtimeContract)" in source
    for field in ('["n"] = port.Name', '["nn"] = port.NickName',
                  '["t"] = port.TypeName',
                  '["param_type"] = parameter.TypeName'):
        assert field in source


def test_builder_uses_verified_instance_and_gates_before_solve_publish():
    source = BUILDER.read_text(encoding="utf-8")
    author_start = source.index(
        "private GrasshopperBuildSession CreateGrasshopperDefinitionSession(")
    author_end = source.index(
        "private static GrasshopperSolveResult GrasshopperSolveNotRequested(",
        author_start,
    )
    author = source[author_start:author_end]
    creator_start = source.index("private IGH_DocumentObject CreateSdkComponent(")
    creator_end = source.index("// Custom Preview GUID", creator_start)
    creator = source[creator_start:creator_end]

    begin = author.index("GrasshopperCatalogVerificationSession.Begin(")
    document = author.index("GH_Document doc = new GH_Document()")
    complete = author.index("catalogVerification.Complete()")
    wire = author.index("WireComponents(objectMap, wire)")
    solve = author.index("SolveGrasshopperDefinitionOnce(doc)")
    publish = author.index("PublishGrasshopperDefinitionAtomically(doc, filePath)")
    assert begin < document < complete < wire < solve < publish
    assert "catalogVerification.CreateVerifiedSdkInstance(" in creator
    assert ".CreateInstance()" not in creator
    assert '["catalog_verification"] = catalogVerificationResult' in author


def test_csharp_failure_response_preserves_verification_evidence():
    service = SERVICE.read_text(encoding="utf-8")
    builder = BUILDER.read_text(encoding="utf-8")

    assert '["status"] = "verification_failed"' in service
    assert "ErrorCode.VERIFICATION_FAILED" in service
    assert '["catalog_verification"] = exception.Verification' in service
    assert builder.count(
        "catch (GrasshopperCatalogVerificationException ex)") == 2
    assert builder.count("return CatalogVerificationFailureResult(ex);") == 2


def test_primitive_recipe_registry_exports_and_forwards_same_guid_contract():
    source = BUILDER.read_text(encoding="utf-8")
    start = source.index("public JObject BuildAndBakeRecipe(")
    recipe = source[start:source.index("#endregion", start)]

    assert '["guid"] = kv.Value.Guid' in recipe
    assert '["bake_output"] = kv.Value.BakeOutput' in recipe
    contract_copy = recipe.index(
        'bakeParams["catalog_contract"] =')
    delegate = recipe.index(
        "return BuildAndBakeGrasshopperDefinition(bakeParams)")
    assert contract_copy < delegate
    assert 'parameters["catalog_contract"].DeepClone()' in recipe
