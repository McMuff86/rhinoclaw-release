"""Read-only live verification of closed Grasshopper component-role sets."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.tools.find_gh_component import _catalog
from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError
from rhinoclaw.utils.gh_catalog import (
    catalog_contract,
    catalog_verification_failure_data,
    require_catalog_verification,
)
from rhinoclaw.utils.responses import error, from_exception, ok


_MAX_ROLES = 500
_RUNTIME_FIELDS = {
    "rhino_version",
    "visualarq_version",
    "grasshopper_version",
    "rhinoclaw_version",
}


def _canonical_guid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty GUID string")
    try:
        guid = UUID(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid GUID") from exc
    if guid.int == 0:
        raise ValueError(f"{field} cannot be Guid.Empty")
    return str(guid)


def _port(value: Any, index: int, field: str) -> Dict[str, Any]:
    if isinstance(value, str):
        parts = value.split("|", 3)
        if len(parts) != 4:
            raise ValueError(
                f"{field}[{index}] must use index|name|nickname|type"
            )
        try:
            encoded_index = int(parts[0])
        except ValueError as exc:
            raise ValueError(f"{field}[{index}] has a non-integer index") from exc
        if encoded_index != index:
            raise ValueError(
                f"{field}[{index}] encodes index {encoded_index}, expected {index}"
            )
        name, nickname, type_name = parts[1:]
        access = None
        optional = None
    elif isinstance(value, dict):
        encoded_index = value.get("index", index)
        if encoded_index != index:
            raise ValueError(
                f"{field}[{index}].index must equal its array position"
            )
        name = value.get("name", value.get("n"))
        nickname = value.get("nickname", value.get("nn"))
        type_name = value.get("type", value.get("t"))
        access = value.get("access")
        optional = value.get("optional")
    else:
        raise ValueError(f"{field}[{index}] must be a port object or string")
    for label, item in (
        ("name", name),
        ("nickname", nickname),
        ("type", type_name),
    ):
        if not isinstance(item, str) or not item:
            raise ValueError(f"{field}[{index}].{label} must be a non-empty string")
    if access is not None and access not in {"item", "list", "tree"}:
        raise ValueError(f"{field}[{index}].access must be item, list, or tree")
    if optional is not None and not isinstance(optional, bool):
        raise ValueError(f"{field}[{index}].optional must be boolean")
    return {
        "n": name,
        "nn": nickname,
        "t": type_name,
        "expected_access": access,
        "expected_optional": optional,
    }


def _normalize_roles(roles: Any) -> List[Dict[str, Any]]:
    if not isinstance(roles, list) or not 1 <= len(roles) <= _MAX_ROLES:
        raise ValueError(f"roles must contain between 1 and {_MAX_ROLES} items")
    normalized = []
    names = set()
    guids = set()
    for index, value in enumerate(roles):
        if not isinstance(value, dict):
            raise ValueError(f"roles[{index}] must be an object")
        unknown = set(value) - {
            "role", "family", "name", "guid", "inputs", "outputs",
        }
        if unknown:
            raise ValueError(
                f"roles[{index}] contains unknown field(s): "
                + ", ".join(sorted(unknown))
            )
        role = value.get("role")
        name = value.get("name")
        family = value.get("family")
        if not isinstance(role, str) or not role.strip():
            raise ValueError(f"roles[{index}].role must be a non-empty string")
        if role.casefold() in names:
            raise ValueError(f"roles contains duplicate role {role!r}")
        names.add(role.casefold())
        if not isinstance(name, str) or not name:
            raise ValueError(f"roles[{index}].name must be a non-empty string")
        if family is not None and (
            not isinstance(family, str) or not family.strip()
        ):
            raise ValueError(f"roles[{index}].family must be a non-empty string")
        guid = _canonical_guid(value.get("guid"), f"roles[{index}].guid")
        if guid in guids:
            raise ValueError(f"roles contains duplicate GUID {guid}")
        guids.add(guid)
        inputs = value.get("inputs")
        outputs = value.get("outputs")
        if not isinstance(inputs, list) or not isinstance(outputs, list):
            raise ValueError(
                f"roles[{index}].inputs and outputs must be arrays"
            )
        normalized.append({
            "role": role.strip(),
            "family": family.strip() if isinstance(family, str) else None,
            "name": name,
            "guid": guid,
            "in": [
                _port(port, port_index, f"roles[{index}].inputs")
                for port_index, port in enumerate(inputs)
            ],
            "out": [
                _port(port, port_index, f"roles[{index}].outputs")
                for port_index, port in enumerate(outputs)
            ],
        })
    return normalized


def _normalize_expected_runtime(value: Any) -> Dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("expected_runtime must be an object")
    unknown = set(value) - _RUNTIME_FIELDS
    if unknown:
        raise ValueError(
            "expected_runtime contains unknown field(s): "
            + ", ".join(sorted(unknown))
        )
    result = {}
    for field, expected in value.items():
        if not isinstance(expected, str) or not expected.strip():
            raise ValueError(f"expected_runtime.{field} must be a non-empty string")
        result[field] = expected.strip()
    return result


def _expected_contract(roles: List[Dict[str, Any]]) -> Dict[str, Any]:
    catalog = _catalog()
    contract = catalog_contract(catalog, [role["guid"] for role in roles])
    catalog_by_guid = {
        item["guid"].lower(): dict(item)
        for item in contract["used_components"]
    }
    used = []
    for role in roles:
        item = catalog_by_guid[role["guid"]]
        item.update({
            "role": role["role"],
            "family": role["family"],
            "name": role["name"],
            "in": [
                {key: port[key] for key in ("n", "nn", "t")}
                for port in role["in"]
            ],
            "out": [
                {key: port[key] for key in ("n", "nn", "t")}
                for port in role["out"]
            ],
        })
        item.pop("param_type", None)
        used.append(item)
    contract["used_components"] = sorted(used, key=lambda item: item["guid"])
    return contract


def _sha256_lines(values: List[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def _runtime_versions(identity: Dict[str, Any]) -> Dict[str, Any]:
    grasshopper = identity.get("grasshopper") or {}
    rhinoclaw = identity.get("rhinoclaw") or {}
    visualarq = identity.get("visualarq_assemblies") or []
    va_versions = sorted({
        version
        for assembly in visualarq if isinstance(assembly, dict)
        for version in (
            assembly.get("file_version"),
            assembly.get("product_version"),
            assembly.get("version"),
        )
        if isinstance(version, str) and version
    })
    return {
        "rhino_version": identity.get("rhino_version"),
        "grasshopper_version": (
            grasshopper.get("file_version")
            or grasshopper.get("product_version")
            or grasshopper.get("version")
        ),
        "rhinoclaw_version": rhinoclaw.get("version"),
        "visualarq_versions": va_versions,
    }


def _verify_runtime(
    identity: Any,
    expected: Dict[str, str],
) -> Dict[str, Any]:
    if not isinstance(identity, dict):
        return {"pass": False, "checks": [], "issues": [
            "plugin response lacks runtime_identity"
        ]}
    observed = _runtime_versions(identity)
    checks = []
    for field, requested in expected.items():
        actual = observed.get(field)
        if field == "visualarq_version":
            actual = observed["visualarq_versions"]
            passed = requested in actual
        else:
            passed = actual == requested
        checks.append({
            "field": field,
            "pass": passed,
            "expected": requested,
            "actual": actual,
        })
    return {
        "pass": all(check["pass"] for check in checks),
        "checks": checks,
        "issues": [
            f"{check['field']} differs from the required runtime"
            for check in checks if not check["pass"]
        ],
        "observed": observed,
    }


def _verify_raw_proxy_inventory(verification: Dict[str, Any]) -> Dict[str, Any]:
    evidence = verification.get("evidence") or {}
    runtime = evidence.get("runtime") or {}
    values = runtime.get("proxy_guids")
    issues = []
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        issues.append("runtime proxy_guids must be a string array")
        values = []
    canonical = []
    for index, value in enumerate(values):
        try:
            canonical.append(str(UUID(value)))
        except (TypeError, ValueError, AttributeError):
            issues.append(f"proxy_guids[{index}] is not a GUID")
    if canonical != sorted(canonical):
        issues.append("runtime proxy_guids are not canonically sorted")
    if len(set(canonical)) != len(canonical):
        issues.append("runtime proxy_guids contain duplicates")
    if runtime.get("proxy_count") != len(canonical):
        issues.append("runtime proxy_count differs from raw proxy_guids")
    if runtime.get("proxy_guid_sha256") != _sha256_lines(canonical):
        issues.append("runtime proxy_guid_sha256 is not raw-inventory-derived")
    return {
        "pass": not issues,
        "count": len(canonical),
        "sha256": _sha256_lines(canonical),
        "issues": issues,
    }


def _verify_role_details(
    roles: List[Dict[str, Any]],
    verification: Dict[str, Any],
) -> Dict[str, Any]:
    evidence = verification.get("evidence") or {}
    used = evidence.get("used_components")
    if not isinstance(used, list):
        return {"pass": False, "roles": [], "issues": [
            "used-component evidence is missing"
        ]}
    by_guid = {
        item.get("guid"): item
        for item in used if isinstance(item, dict)
    }
    results = []
    issues = []
    for role in roles:
        item = by_guid.get(role["guid"])
        runtime = item.get("runtime_component") if isinstance(item, dict) else None
        role_issues = []
        if not isinstance(item, dict):
            role_issues.append("runtime evidence is missing")
        elif item.get("identity_match") is not True:
            role_issues.append("runtime identity did not match")
        if not isinstance(runtime, dict):
            role_issues.append("runtime component detail is missing")
            runtime = {}
        else:
            for field in (
                "guid", "name", "proxy_type", "exposure", "obsolete",
                "runtime_type", "assembly", "in", "out",
            ):
                if field not in runtime:
                    role_issues.append(f"runtime component lacks {field}")
            if runtime.get("obsolete") is not False:
                role_issues.append("runtime proxy is obsolete")
            for side, expected_ports in (("in", role["in"]), ("out", role["out"])):
                actual_ports = runtime.get(side)
                if not isinstance(actual_ports, list) or len(actual_ports) != len(
                    expected_ports
                ):
                    role_issues.append(f"runtime {side} detail count differs")
                    continue
                for index, (expected_port, actual_port) in enumerate(
                    zip(expected_ports, actual_ports)
                ):
                    if not isinstance(actual_port, dict):
                        role_issues.append(f"runtime {side}[{index}] is invalid")
                        continue
                    if actual_port.get("index") != index:
                        role_issues.append(f"runtime {side}[{index}] index differs")
                    if not isinstance(actual_port.get("access"), str):
                        role_issues.append(f"runtime {side}[{index}] lacks access")
                    if not isinstance(actual_port.get("optional"), bool):
                        role_issues.append(f"runtime {side}[{index}] lacks optional")
                    requested_access = expected_port["expected_access"]
                    requested_optional = expected_port["expected_optional"]
                    if (
                        requested_access is not None
                        and actual_port.get("access") != requested_access
                    ):
                        role_issues.append(f"runtime {side}[{index}] access differs")
                    if (
                        requested_optional is not None
                        and actual_port.get("optional") is not requested_optional
                    ):
                        role_issues.append(f"runtime {side}[{index}] optional differs")
        result = {
            "role": role["role"],
            "family": role["family"],
            "guid": role["guid"],
            "name": role["name"],
            "pass": not role_issues,
            "issues": role_issues,
            "runtime_component": runtime,
        }
        results.append(result)
        issues.extend(f"{role['role']}: {issue}" for issue in role_issues)
    return {"pass": not issues, "roles": results, "issues": issues}


@mcp.tool()
def verify_gh_component_contract(
    ctx: Context,
    roles: List[Dict[str, Any]],
    expected_runtime: Optional[Dict[str, str]] = None,
    require_full_catalog: bool = False,
) -> str:
    """Verify exact Grasshopper component roles against the loaded runtime.

    Each role declares ``role``, ``name``, ``guid``, ordered ``inputs`` and
    ordered ``outputs``. Ports may be objects or compact
    ``index|name|nickname|type`` strings. The plugin instantiates that exact
    proxy once, compares exact port identity, records catalog-v2 runtime
    metadata, disposes it, and never creates a graph or mutates Rhino.

    ``expected_runtime`` can pin Rhino, VisualARQ, Grasshopper and RhinoClaw
    versions. A globally matching catalog that contains deliberately skipped
    proxies remains ``used_components_only``; set ``require_full_catalog``
    only when catalog-wide port introspection is genuinely complete.
    """
    try:
        normalized_roles = _normalize_roles(roles)
        normalized_runtime = _normalize_expected_runtime(expected_runtime)
        if not isinstance(require_full_catalog, bool):
            raise ValueError("require_full_catalog must be boolean")
        contract = _expected_contract(normalized_roles)
        rhino = get_rhino_connection()
        result = rhino.send_command(
            "verify_gh_component_contract",
            {"catalog_contract": contract},
            timeout=120.0,
        )
        verification = require_catalog_verification(result)
        proxy_inventory = _verify_raw_proxy_inventory(verification)
        role_verification = _verify_role_details(normalized_roles, verification)
        runtime_verification = _verify_runtime(
            result.get("runtime_identity"), normalized_runtime
        )
        issues = []
        issues.extend(proxy_inventory["issues"])
        issues.extend(role_verification["issues"])
        issues.extend(runtime_verification["issues"])
        if result.get("role_count") != len(normalized_roles):
            issues.append("plugin role_count differs from requested roles")
        if require_full_catalog and verification.get(
            "authoring_search_complete"
        ) is not True:
            issues.append("catalog-wide authoring search is not complete")
        payload = {
            "role_count": len(normalized_roles),
            "exact_roles_verified": not role_verification["issues"],
            "full_catalog_search_verified": verification.get(
                "authoring_search_complete"
            ) is True,
            "catalog_verification": verification,
            "proxy_inventory": proxy_inventory,
            "role_verification": role_verification,
            "runtime_identity": result.get("runtime_identity"),
            "runtime_verification": runtime_verification,
            "issues": issues,
        }
        if issues:
            return json.dumps(error(
                "Grasshopper component-role runtime verification failed",
                code=ErrorCode.VERIFICATION_FAILED,
                data=payload,
            ))
        return json.dumps(ok(
            message=(
                f"Verified {len(normalized_roles)} exact Grasshopper runtime "
                f"component role(s) without document mutation"
            ),
            data=payload,
        ))
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))
    except RhinoCommandError as exc:
        logger.error("Grasshopper component contract failed: %s", exc)
        if exc.error_code == ErrorCode.VERIFICATION_FAILED:
            return json.dumps(error(
                str(exc),
                code=ErrorCode.VERIFICATION_FAILED,
                data=catalog_verification_failure_data(
                    exc, mutation_attempted=False
                ),
            ))
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
    except Exception as exc:
        logger.error("Grasshopper component contract failed: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
