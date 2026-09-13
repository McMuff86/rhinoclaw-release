"""Asset discovery and independent readback checks for ``insert_rahmentuer``."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable, Optional

from rhinoclaw.config import get_settings


ENTRY_FILE = "rahmentuer.py"
HELPER_FILE = "block_hardware.py"
DEFAULT_WORKSPACE_FOLDER = "Rahmentuer_Neu_Preview_Agent"

HARDWARE_FILES = {
    "sfs_he18ei30": "SFS_HE18EI30-M10X1X30-FIX V3.3dm",
    "sudmetall_topspeed": "Sudmetall_TopSpeed_32.51.6600_RZ.3dm",
    "glutz_topaz": "GLUTZ Topaz 5632C_5332C V2.3dm",
    "glutz_treplane": "Glutz Treplane 1834 mit Schliessblech V2.3dm",
}


class RahmentuerAssetError(Exception):
    """The parametric door scripts or selected hardware are unavailable."""


def required_asset_names(overrides: dict[str, Any]) -> tuple[str, ...]:
    """Return every source/hardware file required by this concrete request."""
    names = [ENTRY_FILE, HELPER_FILE]
    if overrides.get("sfs_enabled", True):
        key = str(overrides.get("sfs_hardware_key", "sfs_he18ei30"))
        try:
            names.append(HARDWARE_FILES[key])
        except KeyError as exc:
            raise RahmentuerAssetError(
                f"Unsupported sfs_hardware_key '{key}' for insert_rahmentuer."
            ) from exc
    if overrides.get("glutz_enabled", True):
        for setting, default in (
            ("schloss_key", "glutz_treplane"),
            ("druecker_key", "sudmetall_topspeed"),
        ):
            key = str(overrides.get(setting, default))
            try:
                names.append(HARDWARE_FILES[key])
            except KeyError as exc:
                raise RahmentuerAssetError(
                    f"Unsupported {setting} '{key}' for insert_rahmentuer."
                ) from exc
    return tuple(dict.fromkeys(names))


def _default_roots() -> Iterable[Path]:
    home = Path.home()
    yield home / ".RhinoClaw" / DEFAULT_WORKSPACE_FOLDER
    yield home / "repos" / "RhinoClaw"
    yield home / "source" / "repos" / "RhinoClaw"
    yield Path.cwd()
    # Development checkout: utils -> rhinoclaw -> src -> server -> repo.
    yield Path(__file__).resolve().parents[4]


def resolve_asset_root(
    overrides: dict[str, Any],
    explicit: Optional[str] = None,
) -> Path:
    """Resolve one complete asset root; incomplete candidates never pass."""
    configured = get_settings().rahmentuer_root
    if explicit:
        candidates = [Path(explicit).expanduser()]
        source = "asset_root"
    elif configured is not None:
        candidates = [configured]
        source = "RHINOCLAW_RAHMENTUER_ROOT"
    else:
        candidates = list(_default_roots())
        source = "default search"

    required = required_asset_names(overrides)
    checked: list[str] = []
    for candidate in candidates:
        try:
            root = candidate.resolve()
        except OSError:
            checked.append(str(candidate))
            continue
        missing = [name for name in required if not (root / name).is_file()]
        checked.append(
            f"{root} (missing: {', '.join(missing)})" if missing else str(root)
        )
        if not missing:
            return root

    raise RahmentuerAssetError(
        f"No complete Rahmentuer asset root from {source}. Checked: "
        + "; ".join(checked)
        + ". Pass asset_root or set RHINOCLAW_RAHMENTUER_ROOT."
    )


def _point3(value: Any) -> Optional[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    return result if all(math.isfinite(item) for item in result) else None


def _bbox(value: Any) -> Optional[tuple[list[float], list[float]]]:
    if isinstance(value, dict):
        minimum = _point3(value.get("min"))
        maximum = _point3(value.get("max"))
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        minimum = _point3(value[0])
        maximum = _point3(value[1])
    else:
        return None
    if minimum is None or maximum is None:
        return None
    if any(maximum[i] < minimum[i] for i in range(3)):
        return None
    return minimum, maximum


def _close(a: float, b: float, tolerance: float = 0.01) -> bool:
    return abs(a - b) <= tolerance


def verify_rahmentuer_readback(
    *,
    builder: dict[str, Any],
    object_readback: dict[str, Any],
    definition_readback: dict[str, Any],
    block_name: str,
    insert_point: list[float],
    lichtbreite: float,
    lichthoehe: float,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Judge the new block using separate document/definition readbacks."""
    instance_id = str(builder.get("instance_id") or "")
    objects = object_readback.get("results") or []
    object_row = objects[0] if len(objects) == 1 else None
    definitions = definition_readback.get("definitions") or []
    exact_definitions = [row for row in definitions if row.get("name") == block_name]
    definition = exact_definitions[0] if len(exact_definitions) == 1 else None
    object_bbox = _bbox(object_row.get("bounding_box")) if object_row else None
    definition_bbox = _bbox(definition.get("bbox")) if definition else None
    attributes = object_row.get("attributes") if object_row else {}
    attributes = attributes if isinstance(attributes, dict) else {}

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, actual: Any = None, expected: Any = None) -> None:
        checks.append({
            "name": name,
            "pass": bool(passed),
            "actual": actual,
            "expected": expected,
        })

    check("builder_instance_id", bool(instance_id), instance_id, "GUID")
    check(
        "instance_resolved_once",
        object_readback.get("count") == 1 and object_readback.get("missing_count") == 0,
        {"count": object_readback.get("count"),
         "missing_count": object_readback.get("missing_count")},
        {"count": 1, "missing_count": 0},
    )
    check(
        "instance_identity",
        bool(object_row)
        and str(object_row.get("id") or "").lower() == instance_id.lower(),
        object_row.get("id") if object_row else None,
        instance_id,
    )
    check(
        "instance_name",
        bool(object_row) and object_row.get("name") == block_name,
        object_row.get("name") if object_row else None,
        block_name,
    )
    check(
        "instance_type",
        bool(object_row) and "instance" in str(object_row.get("type") or "").lower(),
        object_row.get("type") if object_row else None,
        "InstanceReference",
    )
    check(
        "erp_prefix",
        attributes.get("TEILNR_PREFIX") == block_name
        and attributes.get("TEILNR_PREFIX_SOURCE") == block_name,
        {"TEILNR_PREFIX": attributes.get("TEILNR_PREFIX"),
         "TEILNR_PREFIX_SOURCE": attributes.get("TEILNR_PREFIX_SOURCE")},
        block_name,
    )
    check("definition_resolved_once", len(exact_definitions) == 1,
          len(exact_definitions), 1)
    expected_parts = builder.get("parts")
    check(
        "definition_part_count",
        bool(definition)
        and isinstance(expected_parts, int)
        and expected_parts >= 4
        and definition.get("object_count") == expected_parts,
        definition.get("object_count") if definition else None,
        expected_parts,
    )
    check(
        "definition_instance_count",
        bool(definition) and definition.get("instance_count") == 1,
        definition.get("instance_count") if definition else None,
        1,
    )
    check("world_bbox_valid", object_bbox is not None,
          object_row.get("bounding_box") if object_row else None, "finite bbox")
    check("definition_bbox_valid", definition_bbox is not None,
          definition.get("bbox") if definition else None, "finite bbox")

    expected_width = (
        lichtbreite
        + float(overrides.get("rahmenbreite_l", 120.0))
        + float(overrides.get("rahmenbreite_r", 100.0))
    )
    expected_height = lichthoehe + float(overrides.get("rahmenbreite_o", 80.0))
    if definition_bbox is not None:
        def_min, def_max = definition_bbox
        dims = [def_max[i] - def_min[i] for i in range(3)]
        check("outer_width", _close(dims[0], expected_width), dims[0], expected_width)
        check("outer_height", _close(dims[2], expected_height), dims[2], expected_height)
    else:
        check("outer_width", False, None, expected_width)
        check("outer_height", False, None, expected_height)

    if object_bbox is not None and definition_bbox is not None:
        obj_min, obj_max = object_bbox
        def_min, def_max = definition_bbox
        translated = all(
            _close(obj_min[i], def_min[i] + insert_point[i])
            and _close(obj_max[i], def_max[i] + insert_point[i])
            for i in range(3)
        )
        check(
            "insertion_translation",
            translated,
            {"world": [obj_min, obj_max], "definition": [def_min, def_max]},
            insert_point,
        )
    else:
        check("insertion_translation", False, None, insert_point)

    failed = [item["name"] for item in checks if not item["pass"]]
    return {
        "pass": not failed,
        "failed_checks": failed,
        "checks": checks,
        "instance": object_row,
        "definition": definition,
    }
