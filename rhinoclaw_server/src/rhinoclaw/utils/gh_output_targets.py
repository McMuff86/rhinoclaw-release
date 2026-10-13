"""Validation for canonical Grasshopper component/output target pairs."""

from typing import Any
from uuid import UUID


def validate_output_targets(value: Any) -> list[dict[str, str]]:
    """Return canonical target pairs or raise ``ValueError`` fail-closed."""
    if not isinstance(value, list) or not value:
        raise ValueError("output_targets must be a non-empty list")

    canonical: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    required = {"component_instance_id", "output_instance_id"}
    for index, target in enumerate(value):
        if not isinstance(target, dict):
            raise ValueError(f"output_targets[{index}] must be an object")
        if set(target) != required:
            raise ValueError(
                f"output_targets[{index}] must contain exactly "
                "component_instance_id and output_instance_id"
            )
        ids: dict[str, str] = {}
        for field in sorted(required):
            try:
                parsed = UUID(str(target[field]))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError(
                    f"output_targets[{index}].{field} must be a GUID"
                ) from exc
            if parsed.int == 0:
                raise ValueError(
                    f"output_targets[{index}].{field} must not be empty"
                )
            ids[field] = str(parsed)
        key = (ids["component_instance_id"], ids["output_instance_id"])
        if key in seen:
            raise ValueError(f"output_targets[{index}] duplicates an earlier target")
        seen.add(key)
        canonical.append(ids)
    return canonical
