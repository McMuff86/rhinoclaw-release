"""Independent, read-only BIM acceptance for exact Grasshopper bake batches.

Native BakeAware execution preserves custom products, but is not evidence of
their BIM identity. Only subsequent VisualARQ product reads supply that evidence.
"""

import json
from typing import Any, Callable, Optional
from uuid import UUID


BIM_KINDS = {"wall", "slab", "space", "door", "window"}


def _guid(value: Any) -> Optional[str]:
    try:
        parsed = UUID(value) if isinstance(value, str) else None
        return str(parsed) if parsed is not None and parsed.int else None
    except (ValueError, AttributeError):
        return None


def validate_bim_expectation(kind, count, style_id, host_id, targets):
    if kind is None:
        if any(value is not None for value in (count, style_id, host_id)):
            raise ValueError("BIM count/style/host expectations require expected_visualarq_kind")
        return None
    if not isinstance(kind, str) or kind not in BIM_KINDS:
        raise ValueError("expected_visualarq_kind must be wall, slab, space, door or window")
    if not targets:
        raise ValueError("BIM verification requires exact output_targets, not component names")
    if count is not None and (
        not isinstance(count, int) or isinstance(count, bool) or count <= 0
    ):
        raise ValueError("expected_count must be a positive integer")
    for field, value in (("expected_style_id", style_id), ("expected_host_id", host_id)):
        if value is not None and _guid(value) is None:
            raise ValueError(f"{field} must be a non-empty GUID")
    if host_id is not None and kind not in {"door", "window"}:
        raise ValueError("expected_host_id is only supported for doors and windows")
    return {"kind": kind, "count": count, "style_id": _guid(style_id),
            "host_id": _guid(host_id)}


def verify_bim_bake(
    baked_ids: list[str], expectation: dict, read_product: Callable,
) -> dict:
    """Read every exact product and opening host; never delete or re-bake.

    The injected reader is va_get_object, including its runtime classification,
    style and domain readback completeness checks. Exceptions become evidence
    so already-created GUIDs are not lost on a timeout or absent VisualARQ API.
    """
    issues = []
    objects = []
    hosts = {}
    kind = expectation["kind"]
    expected_count = expectation["count"]
    if expected_count is not None and len(baked_ids) != expected_count:
        issues.append(f"Expected {expected_count} {kind} products, read {len(baked_ids)} bake IDs")

    def read(object_id, expected_kind):
        try:
            response = json.loads(read_product(object_id, expected_kind))
            data = response.get("data") or {}
            snapshot = data.get("object") if isinstance(data, dict) else None
            problems = []
            if response.get("success") is not True:
                problems.append(response.get("message") or "VisualARQ readback failed")
            if not isinstance(snapshot, dict):
                problems.append("No VisualARQ product snapshot returned")
            else:
                if _guid(snapshot.get("id")) != object_id:
                    problems.append("Readback object GUID differs from requested GUID")
                classifications = snapshot.get("classifications")
                if (snapshot.get("kind") != expected_kind
                        or not isinstance(classifications, list)
                        or expected_kind not in classifications):
                    problems.append(f"Object is not a verified VisualARQ {expected_kind}")
                if (snapshot.get("classification_complete") is not True
                        or snapshot.get("classification_errors") != []
                        or snapshot.get("readback_complete") is not True
                        or snapshot.get("readback_errors") != []):
                    problems.append("VisualARQ classification or domain readback is incomplete")
                if _guid(snapshot.get("style_id")) is None:
                    problems.append("Product has no readable VisualARQ style GUID")
            return {"id": object_id, "pass": not problems, "issues": problems,
                    "readback": response}, snapshot
        except Exception as exc:
            return {"id": object_id, "pass": False, "issues": [str(exc)],
                    "readback": None}, None

    for object_id in baked_ids:
        row, snapshot = read(object_id, kind)
        if isinstance(snapshot, dict):
            if (expectation["style_id"] is not None
                    and _guid(snapshot.get("style_id")) != expectation["style_id"]):
                row["issues"].append("Product style differs from expected_style_id")
            if kind in {"door", "window"}:
                host_id = _guid(snapshot.get("host_id"))
                if host_id is None:
                    row["issues"].append("Opening has no unique readable host GUID")
                else:
                    if expectation["host_id"] is not None and host_id != expectation["host_id"]:
                        row["issues"].append("Opening host differs from expected_host_id")
                    if host_id not in hosts:
                        hosts[host_id], _ = read(host_id, "wall")
                    if not hosts[host_id]["pass"]:
                        row["issues"].append("Opening host is not a verified active VisualARQ wall")
        row["pass"] = not row["issues"]
        issues.extend(f"{object_id}: {problem}" for problem in row["issues"])
        objects.append(row)

    if not baked_ids:
        issues.append("No baked products to verify")
    return {
        "pass": not issues, "expectation": expectation, "issues": issues,
        "objects": objects, "hosts": list(hosts.values()),
        "scope": "exact_baked_product_identity_style_domain_readback_and_opening_hosts",
        "unmeasured": ["opening_host_cut", "building_level_membership",
                       "ifc_roundtrip", "visualarq_private_state_rollback"],
        "failure_policy": "retain_objects_no_automatic_retry_or_cleanup",
    }
