"""Distill judge-verified placement outcomes into recallable recipes (3.1).

Reads ``logs/interactions_*.jsonl``, keeps only records with a
``placement_outcome`` whose ``pass`` is true (judge-measured — agent claims
never reach the corpus), and upserts ``logs/door_recipes.json`` keyed by
``(door_type, wall_axis)``. "Best" per key = lowest judge-measured
``off_center_mm``; ``confidence`` counts ALL passing records for the key.

Pure Python, no Rhino, no LLM — the recall side of the loop must be
deterministic (NEXT-LEVEL-PLAN 3.1/3.2).
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("rhinoclaw.recipe_distiller")

RECIPES_FILENAME = "door_recipes.json"


def door_type_from_definition(definition: Optional[str]) -> str:
    """Normalize a definition path to its recall key (basename, lowercase)."""
    if not definition:
        return "unknown"
    return Path(str(definition).replace("\\", "/")).name.lower()


def recipe_key(door_type: str, wall_axis: Optional[str]) -> str:
    return f"{door_type}|{(wall_axis or 'unknown').lower()}"


def _iter_passing_outcomes(log_dir: Path):
    for log_file in sorted(log_dir.glob("interactions_*.jsonl")):
        try:
            with open(log_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    outcome = record.get("placement_outcome")
                    if outcome and outcome.get("pass") is True:
                        yield record, outcome
        except OSError as e:
            logger.warning(f"Could not read {log_file}: {e}")


def distill(log_dir, recipes_path=None) -> Dict[str, Any]:
    """Rebuild the recipe registry from the outcome corpus.

    Returns the registry dict and (when ``recipes_path`` or the default
    location is writable) persists it as JSON. Deterministic: same corpus →
    same registry.
    """
    log_dir = Path(log_dir)
    recipes: Dict[str, Dict[str, Any]] = {}

    for record, outcome in _iter_passing_outcomes(log_dir):
        door_type = door_type_from_definition(outcome.get("definition"))
        key = recipe_key(door_type, outcome.get("wall_axis"))
        off_center = outcome.get("off_center_mm")

        entry = recipes.get(key)
        if entry is None:
            entry = {
                "door_type": door_type,
                "wall_axis": (outcome.get("wall_axis") or "unknown").lower(),
                "rotation": outcome.get("rotation_applied"),
                "width": outcome.get("width_requested"),
                "off_center_mm": off_center,
                "confidence": 0,
                "last_seen": record.get("timestamp"),
            }
            recipes[key] = entry

        entry["confidence"] += 1
        timestamp = record.get("timestamp")
        if timestamp and (entry["last_seen"] is None or timestamp > entry["last_seen"]):
            entry["last_seen"] = timestamp

        # "Best" = lowest judge-measured off-center. None never wins.
        current = entry.get("off_center_mm")
        if off_center is not None and (current is None or off_center < current):
            entry.update({
                "rotation": outcome.get("rotation_applied"),
                "width": outcome.get("width_requested"),
                "off_center_mm": off_center,
            })

    if recipes_path is None:
        recipes_path = log_dir / RECIPES_FILENAME
    try:
        recipes_path = Path(recipes_path)
        recipes_path.parent.mkdir(parents=True, exist_ok=True)
        with open(recipes_path, "w", encoding="utf-8") as f:
            json.dump(recipes, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        logger.warning(f"Could not persist recipes to {recipes_path}: {e}")

    return recipes


def lookup(recipes: Dict[str, Any], door_type: str,
           wall_axis: Optional[str]) -> Optional[Dict[str, Any]]:
    """Deterministic recall: best recipe for (door_type, wall_axis) or None."""
    return recipes.get(recipe_key(door_type_from_definition(door_type), wall_axis))
