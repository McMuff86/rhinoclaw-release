import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "rhinoclaw_plugin" / "Functions" / "GrasshopperCatalogContract.cs"
SERVER = ROOT / "rhinoclaw_plugin" / "RhinoClawServer.cs"
GUID = "28061aae-04fb-4cb5-ac45-16f3b66bc0a4"
ROLES = [{
    "role": "native wall and slab solids",
    "family": "native",
    "name": "Center Box",
    "guid": GUID,
    "inputs": [
        "0|Base|B|Plane",
        "1|X|X|Number",
        "2|Y|Y|Number",
        "3|Z|Z|Number",
    ],
    "outputs": ["0|Box|B|Box"],
}]


def _port(index, name, nickname, type_name):
    return {
        "index": index,
        "n": name,
        "nn": nickname,
        "t": type_name,
        "access": "item",
        "optional": False,
        "runtime_type": "Grasshopper.Kernel.IGH_Param",
    }


def _plugin_result():
    proxy_guids = [GUID]
    proxy_hash = hashlib.sha256("\n".join(proxy_guids).encode()).hexdigest()
    return {
        "status": "success",
        "role_count": 1,
        "runtime_identity": {
            "rhino_version": "9.0.26223.12303",
            "grasshopper": {
                "version": "9.0.26223.12303",
                "file_version": "9.0.26223.12303",
            },
            "rhinoclaw": {"version": "0.7.12.0"},
            "visualarq_assemblies": [{
                "name": "GhVa30",
                "version": "0.0.0.0",
                "file_version": "3.11.0.15030",
            }],
            "process_id": 42,
            "process_start_ticks": 100,
        },
        "catalog_verification": {
            "pass": True,
            "schema_version": 1,
            "global_match": True,
            "catalog_port_inventory_complete": False,
            "scope": "used_components_only",
            "authoring_search_complete": False,
            "warning": "two proxies have skipped port introspection",
            "issues": [],
            "evidence": {
                "contract": {
                    "schema_version": 1,
                    "component_count": 1,
                    "proxy_guid_sha256": proxy_hash,
                    "component_contract_sha256": "a" * 64,
                    "ports_skipped_guids": [
                        "11111111-1111-4111-8111-111111111111"
                    ],
                },
                "runtime": {
                    "proxy_count": 1,
                    "proxy_guid_sha256": proxy_hash,
                    "proxy_guids": proxy_guids,
                },
                "used_component_count": 1,
                "used_components": [{
                    "guid": GUID,
                    "requested_instances": 1,
                    "verified_instances": 1,
                    "proxy_present": True,
                    "create_instance_succeeded": True,
                    "identity_match": True,
                    "contract_match": True,
                    "runtime_component": {
                        "guid": GUID,
                        "name": "Center Box",
                        "proxy_type": "Grasshopper.Kernel.GH_CompiledObjectProxy",
                        "exposure": "primary",
                        "obsolete": False,
                        "runtime_type": "BoxComponents.Component_CenterBox",
                        "assembly": {"name": "BoxComponents"},
                        "in": [
                            _port(0, "Base", "B", "Plane"),
                            _port(1, "X", "X", "Number"),
                            _port(2, "Y", "Y", "Number"),
                            _port(3, "Z", "Z", "Number"),
                        ],
                        "out": [_port(0, "Box", "B", "Box")],
                    },
                }],
            },
        },
    }


def _run(result=None, **kwargs):
    from rhinoclaw.tools.verify_gh_component_contract import (
        verify_gh_component_contract,
    )

    rhino = MagicMock()
    rhino.send_command.return_value = result or _plugin_result()
    contract = {
        "schema_version": 1,
        "component_count": 1,
        "proxy_guid_sha256": "b" * 64,
        "component_contract_sha256": "c" * 64,
        "ports_skipped_guids": [],
        "used_components": [{"guid": GUID}],
    }
    with (
        patch(
            "rhinoclaw.tools.verify_gh_component_contract._expected_contract",
            return_value=contract,
        ),
        patch(
            "rhinoclaw.tools.verify_gh_component_contract.get_rhino_connection",
            return_value=rhino,
        ),
    ):
        response = json.loads(verify_gh_component_contract(
            None,
            ROLES,
            expected_runtime={
                "rhino_version": "9.0.26223.12303",
                "visualarq_version": "3.11.0.15030",
                "rhinoclaw_version": "0.7.12.0",
            },
            **kwargs,
        ))
    return response, rhino, contract


def test_exact_role_runtime_verification_passes_with_raw_inventory():
    response, rhino, contract = _run()

    assert response["success"] is True
    assert response["data"]["exact_roles_verified"] is True
    assert response["data"]["full_catalog_search_verified"] is False
    assert response["data"]["proxy_inventory"]["pass"] is True
    assert response["data"]["runtime_verification"]["pass"] is True
    rhino.send_command.assert_called_once_with(
        "verify_gh_component_contract",
        {"catalog_contract": contract},
        timeout=120.0,
    )


def test_full_catalog_requirement_rejects_truthful_skipped_port_scope():
    response, _rhino, _contract = _run(require_full_catalog=True)

    assert response["success"] is False
    assert response["code"] == "VERIFICATION_FAILED"
    assert "catalog-wide authoring search is not complete" in response["data"][
        "issues"
    ]


def test_raw_proxy_hash_tamper_is_rejected():
    result = _plugin_result()
    result["catalog_verification"]["evidence"]["runtime"][
        "proxy_guids"
    ] = ["3581f42a-9592-4549-bd6b-1c0fc39d067b"]
    response, _rhino, _contract = _run(result)

    assert response["success"] is False
    assert response["code"] == "VERIFICATION_FAILED"
    assert response["data"]["proxy_inventory"]["pass"] is False


def test_complete_raw_proxy_inventory_can_retain_diagnostic_guid_empty():
    result = _plugin_result()
    values = ["00000000-0000-0000-0000-000000000000", GUID]
    runtime = result["catalog_verification"]["evidence"]["runtime"]
    runtime["proxy_guids"] = values
    runtime["proxy_count"] = len(values)
    runtime["proxy_guid_sha256"] = hashlib.sha256(
        "\n".join(values).encode()
    ).hexdigest()
    contract = result["catalog_verification"]["evidence"]["contract"]
    contract["component_count"] = len(values)
    contract["proxy_guid_sha256"] = runtime["proxy_guid_sha256"]

    response, _rhino, _contract = _run(result)

    assert response["success"] is True
    assert response["data"]["proxy_inventory"]["count"] == 2


def test_duplicate_guid_fails_before_rhino():
    from rhinoclaw.tools.verify_gh_component_contract import (
        verify_gh_component_contract,
    )

    duplicate = copy.deepcopy(ROLES[0])
    duplicate["role"] = "second role"
    with patch(
        "rhinoclaw.tools.verify_gh_component_contract.get_rhino_connection"
    ) as connection:
        response = json.loads(verify_gh_component_contract(
            None, ROLES + [duplicate]
        ))

    assert response["success"] is False
    assert response["code"] == "INVALID_PARAMS"
    assert "duplicate GUID" in response["message"]
    connection.assert_not_called()


def test_native_read_only_handler_is_dispatched_and_records_detailed_ports():
    service = SERVICE.read_text(encoding="utf-8")
    server = SERVER.read_text(encoding="utf-8")

    assert "public JObject VerifyGrasshopperComponentContract(" in service
    assert "SnapshotStableRuntimeProxyGuids" in service
    assert 'runtime["proxy_guids"]' in service
    assert '["identity_match"] = identityMatch' in service
    assert '["access"] = port.Access.ToString().ToLowerInvariant()' in service
    assert '["optional"] = port.Optional' in service
    assert '["verify_gh_component_contract"] =' in server
    assert "this.handler.VerifyGrasshopperComponentContract" in server
