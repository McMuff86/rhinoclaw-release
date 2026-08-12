"""Shared authorability and provenance policy for the GH catalog.

Catalog v1 predates an explicit instantiation status.  A component is safe to
recommend for graph authoring only when its GUID is usable and the catalog
contains evidence that ``CreateInstance`` completed.  Port arrays (including
empty arrays) and ``param_type`` are the v1 success evidence; newer catalogs
may provide an explicit instantiation marker.

Keep this policy in one place: both lookup and lint must fail closed for the
same catalog facts.
"""

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError

_SUCCESS_STATUSES = {"ok", "success", "succeeded"}
_FAILURE_STATUSES = {"error", "failed", "failure", "hung", "timeout"}
CATALOG_CONTRACT_SCHEMA = 1


def _issue(code: str, message: str) -> Dict[str, str]:
    return {"code": code, "message": message}


def catalog_entry_issues(component: Dict[str, Any]) -> List[Dict[str, str]]:
    """Derive blocking authoring issues from a catalog entry.

    The result is intentionally derived instead of trusting a stored
    ``authorable`` flag.  Fatal facts such as ``Guid.Empty`` or a skipped
    instantiation can therefore never be overridden by stale catalog data.
    """
    issues: List[Dict[str, str]] = []

    raw_guid = component.get("guid")
    if not raw_guid:
        issues.append(_issue(
            "guid_missing",
            "The catalog entry has no component GUID.",
        ))
    else:
        try:
            guid = UUID(str(raw_guid))
        except (TypeError, ValueError, AttributeError):
            issues.append(_issue(
                "guid_invalid",
                "The catalog entry GUID is not a valid GUID.",
            ))
        else:
            if guid.int == 0:
                issues.append(_issue(
                    "guid_empty",
                    "Guid.Empty cannot identify a Grasshopper component.",
                ))

    instantiation_blocked = False
    if "ports_skipped" in component:
        issues.append(_issue(
            "ports_skipped",
            "Component instantiation/port introspection was skipped.",
        ))
        instantiation_blocked = True

    instantiate_error = (
        component.get("instantiate_error")
        or component.get("instantiation_error")
    )
    if instantiate_error:
        issues.append(_issue(
            "instantiation_failed",
            "The catalog generator could not instantiate this component.",
        ))
        instantiation_blocked = True

    instantiated = component.get("instantiated")
    raw_status = (
        component.get("instantiate_status")
        or component.get("instantiation_status")
    )
    status = str(raw_status).strip().lower() if raw_status is not None else None
    if instantiated is False or status in _FAILURE_STATUSES:
        if not instantiation_blocked:
            issues.append(_issue(
                "instantiation_failed",
                "The catalog records a failed component instantiation.",
            ))
        instantiation_blocked = True

    v1_success_evidence = any(
        key in component for key in ("in", "out", "param_type")
    )
    explicit_success = instantiated is True or status in _SUCCESS_STATUSES
    if not instantiation_blocked and not (v1_success_evidence or explicit_success):
        issues.append(_issue(
            "instantiation_unverified",
            "The catalog has no evidence that the component instantiated.",
        ))

    return issues


def catalog_entry_with_authorability(
    component: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a copy decorated with stable ``authorable`` and ``issues``."""
    issues = catalog_entry_issues(component)
    return {**component, "authorable": not issues, "issues": issues}


def _sha256_lines(values: Iterable[str]) -> str:
    payload = "\n".join(values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def catalog_contract(
    catalog: Dict[str, Any],
    used_component_guids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Return deterministic catalog provenance for runtime drift checks.

    ``proxy_guid_sha256`` is deliberately cheap for the Rhino plugin to
    recompute from ``ComponentServer.ObjectProxies`` before authoring. The
    stronger component-contract digest covers ordered ports and metadata. For
    a concrete build, ``used_components`` carries the exact catalog records
    that the runtime must compare after instantiating only those components.
    """
    if not isinstance(catalog, dict):
        raise ValueError("catalog must be an object")
    components = catalog.get("components")
    if not isinstance(components, list):
        raise ValueError("catalog.components must be a list")

    ordered = sorted(
        (component for component in components if isinstance(component, dict)),
        key=lambda component: str(component.get("guid") or "").lower(),
    )
    proxy_guids = [
        str(component.get("guid") or "").lower()
        for component in ordered
    ]
    canonical_components = [
        json.dumps(component, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True)
        for component in ordered
    ]

    requested = {
        str(guid).strip().lower()
        for guid in (used_component_guids or [])
        if str(guid).strip()
    }
    by_guid = {
        str(component.get("guid") or "").lower(): component
        for component in ordered
    }
    missing = sorted(requested - set(by_guid))
    if missing:
        raise ValueError(
            "used component GUIDs missing from catalog: " + ", ".join(missing)
        )

    meta = catalog.get("meta") if isinstance(catalog.get("meta"), dict) else {}
    return {
        "schema_version": CATALOG_CONTRACT_SCHEMA,
        "component_count": len(ordered),
        "proxy_guid_sha256": _sha256_lines(proxy_guids),
        "component_contract_sha256": _sha256_lines(canonical_components),
        "source": {
            "rhino_version": meta.get("rhino_version"),
            "generated": meta.get("generated"),
            "introspection": meta.get("source"),
        },
        "used_components": [by_guid[guid] for guid in sorted(requested)],
    }


def authoring_catalog_contract(
    catalog: Dict[str, Any],
    components: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the runtime contract for SDK components in one graph spec."""
    used_guids = []
    for component in components:
        if not isinstance(component, dict):
            continue
        component_type = str(component.get("type") or "").strip().lower()
        if component_type not in {"sdk", "sdk_component"}:
            continue
        guid = component.get("guid")
        if guid:
            used_guids.append(str(guid))
    return catalog_contract(catalog, used_guids)


def require_catalog_verification(
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Require the plugin's post-instantiation catalog evidence.

    A transport-level success from an older plugin is not authoring evidence:
    that plugin may have published or baked against a different component
    runtime.  Callers therefore fail closed unless the complete v1 result is
    present and internally consistent.  Global catalog drift is accepted only
    in the explicit ``used_components_only`` scope chosen by the plugin.
    """
    response = dict(result) if isinstance(result, dict) else {}
    verification = response.get("catalog_verification")
    issues: List[str] = []

    if not isinstance(verification, dict):
        issues.append(
            "plugin response lacks catalog_verification; update/restart the "
            "RhinoClaw plugin before authoring Grasshopper definitions"
        )
    else:
        if verification.get("schema_version") != CATALOG_CONTRACT_SCHEMA:
            issues.append(
                "catalog_verification.schema_version is not supported"
            )
        if verification.get("pass") is not True:
            plugin_issues = verification.get("issues")
            if isinstance(plugin_issues, list) and plugin_issues:
                issues.extend(str(issue) for issue in plugin_issues)
            else:
                issues.append("plugin catalog_verification.pass is not true")
        elif response.get("status") in {"verification_failed", "error"}:
            issues.append(
                "plugin result status contradicts catalog_verification.pass=true"
            )

        global_match = verification.get("global_match")
        scope = verification.get("scope")
        search_complete = verification.get("authoring_search_complete")
        if not isinstance(global_match, bool):
            issues.append("catalog_verification.global_match must be boolean")
        if global_match is True:
            if scope != "full_catalog" or search_complete is not True:
                issues.append(
                    "a global catalog match requires scope=full_catalog and "
                    "authoring_search_complete=true"
                )
        elif global_match is False:
            if scope != "used_components_only" or search_complete is not False:
                issues.append(
                    "catalog drift requires scope=used_components_only and "
                    "authoring_search_complete=false"
                )
            warning = verification.get("warning")
            if not isinstance(warning, str) or not warning.strip():
                issues.append(
                    "catalog drift requires an explicit warning"
                )

        evidence = verification.get("evidence")
        contract = evidence.get("contract") \
            if isinstance(evidence, dict) else None
        runtime = evidence.get("runtime") if isinstance(evidence, dict) else None
        used = evidence.get("used_components") \
            if isinstance(evidence, dict) else None
        if not isinstance(evidence, dict):
            issues.append("catalog_verification.evidence must be an object")
        elif (
            not isinstance(runtime, dict)
            or not isinstance(runtime.get("proxy_count"), int)
            or isinstance(runtime.get("proxy_count"), bool)
            or not _is_sha256(runtime.get("proxy_guid_sha256"))
        ):
            issues.append(
                "catalog_verification.evidence.runtime lacks a valid proxy "
                "count/hash"
            )
        if (
            not isinstance(contract, dict)
            or contract.get("schema_version") != CATALOG_CONTRACT_SCHEMA
            or not isinstance(contract.get("component_count"), int)
            or isinstance(contract.get("component_count"), bool)
            or not _is_sha256(contract.get("proxy_guid_sha256"))
            or not _is_sha256(contract.get("component_contract_sha256"))
        ):
            issues.append(
                "catalog_verification.evidence.contract is incomplete"
            )
        contract_runtime_shape_valid = (
            isinstance(contract, dict)
            and isinstance(runtime, dict)
            and isinstance(contract.get("component_count"), int)
            and not isinstance(contract.get("component_count"), bool)
            and isinstance(runtime.get("proxy_count"), int)
            and not isinstance(runtime.get("proxy_count"), bool)
            and _is_sha256(contract.get("proxy_guid_sha256"))
            and _is_sha256(runtime.get("proxy_guid_sha256"))
        )
        if contract_runtime_shape_valid:
            count_match = (
                contract["component_count"] == runtime["proxy_count"]
            )
            hash_match = (
                contract["proxy_guid_sha256"].lower()
                == runtime["proxy_guid_sha256"].lower()
            )
            if global_match is True and not (count_match and hash_match):
                issues.append(
                    "global_match=true contradicts runtime proxy count/hash"
                )
            if global_match is False and count_match and hash_match:
                issues.append(
                    "global_match=false contradicts identical proxy count/hash"
                )
        if not isinstance(used, list):
            issues.append(
                "catalog_verification.evidence.used_components must be a list"
            )
        else:
            used_count = evidence.get("used_component_count")
            if (
                not isinstance(used_count, int)
                or isinstance(used_count, bool)
                or used_count != len(used)
            ):
                issues.append(
                    "catalog_verification used-component count is inconsistent"
                )
            for component in used:
                flags_valid = isinstance(component, dict) and all(
                    component.get(field) is True for field in (
                        "proxy_present", "create_instance_succeeded",
                        "contract_match",
                    ))
                requested = component.get("requested_instances") \
                    if isinstance(component, dict) else None
                verified = component.get("verified_instances") \
                    if isinstance(component, dict) else None
                counts_valid = (
                    isinstance(requested, int)
                    and not isinstance(requested, bool)
                    and requested > 0
                    and isinstance(verified, int)
                    and not isinstance(verified, bool)
                    and verified == requested
                )
                if not flags_valid or not counts_valid:
                    issues.append(
                        "catalog_verification contains an unverified used "
                        "component"
                    )

    if issues:
        raise RhinoCommandError(
            "Grasshopper catalog verification failed: " + "; ".join(issues),
            error_code=ErrorCode.VERIFICATION_FAILED,
            response=response,
        )
    return verification


def catalog_verification_failure_data(
    exc: RhinoCommandError,
    *,
    mutation_attempted: bool,
) -> Dict[str, Any]:
    """Preserve plugin gate evidence in an MCP-level error response."""
    response = exc.response if isinstance(exc.response, dict) else {}
    verification = response.get("catalog_verification")
    if isinstance(verification, dict):
        mutation_scope = "pre_solve_pre_publish_gate"
    elif mutation_attempted:
        mutation_scope = "unknown_old_plugin_response"
    else:
        mutation_scope = "read_only_registry_preflight"
    return {
        "catalog_verification": verification,
        "plugin_response": response,
        "mutation_attempted": mutation_attempted,
        "mutation_scope": mutation_scope,
    }


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value.lower())
