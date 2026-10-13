"""Distill judge-verified part-placement outcomes into recallable recipes.

Part-library sibling of ``recipe_distiller`` (doors): reads
``logs/interactions_*.jsonl``, keeps only records with a ``part_outcome``
whose ``pass`` is true (judge-measured — agent claims never reach the
corpus), and rebuilds ``logs/part_recipes.json`` keyed by
``part_id|context``. "Best" per key = lowest judge-measured
``worst_probe_mm``; ``confidence`` counts ALL passing records for the key.

Rebuild-on-read and pure Python (no Rhino, no LLM) — the recall side of
the loop must be deterministic: same corpus -> same registry.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("rhinoclaw.part_recipe_distiller")

PART_RECIPES_FILENAME = "part_recipes.json"


def part_recipe_key(part_id: str, context: Optional[str]) -> str:
    """Registry key: normalized part id + free-form context string."""
    pid = str(part_id or "unknown").strip().lower()
    ctx = str(context or "default").strip().lower()
    return f"{pid}|{ctx}"


def _iter_passing_part_outcomes(log_dir: Path):
    for log_file in sorted(log_dir.glob("interactions_*.jsonl")):
        try:
            with open(log_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    outcome = record.get("part_outcome")
                    if outcome and outcome.get("pass") is True:
                        yield record, outcome
        except OSError as e:
            logger.warning(f"Could not read {log_file}: {e}")


def distill_part_recipes(log_dir, recipes_path=None) -> Dict[str, Any]:
    """Rebuild the part-recipe registry from the outcome corpus.

    Returns the registry dict and (when writable) persists it as JSON next
    to the logs. Deterministic: same corpus -> same registry.
    """
    log_dir = Path(log_dir)
    recipes: Dict[str, Dict[str, Any]] = {}

    for record, outcome in _iter_passing_part_outcomes(log_dir):
        key = part_recipe_key(outcome.get("part_id"), outcome.get("context"))
        worst = outcome.get("worst_probe_mm")

        entry = recipes.get(key)
        if entry is None:
            entry = {
                "part_id": outcome.get("part_id"),
                "context": (outcome.get("context") or "default"),
                "target_frame": outcome.get("target_frame"),
                "xform": outcome.get("xform"),
                "worst_probe_mm": worst,
                "det": outcome.get("det"),
                "confidence": 0,
                "last_seen": record.get("timestamp"),
            }
            recipes[key] = entry

        entry["confidence"] += 1
        timestamp = record.get("timestamp")
        if timestamp and (entry["last_seen"] is None or timestamp > entry["last_seen"]):
            entry["last_seen"] = timestamp

        # "Best" = lowest judge-measured worst probe distance. None never wins.
        current = entry.get("worst_probe_mm")
        if worst is not None and (current is None or worst < current):
            entry.update({
                "target_frame": outcome.get("target_frame"),
                "xform": outcome.get("xform"),
                "worst_probe_mm": worst,
                "det": outcome.get("det"),
            })

    if recipes_path is None:
        recipes_path = log_dir / PART_RECIPES_FILENAME
    try:
        recipes_path = Path(recipes_path)
        recipes_path.parent.mkdir(parents=True, exist_ok=True)
        with open(recipes_path, "w", encoding="utf-8") as f:
            json.dump(recipes, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        logger.warning(f"Could not persist part recipes to {recipes_path}: {e}")

    return recipes


def lookup_part_recipe(recipes: Dict[str, Any], part_id: str,
                       context: Optional[str]) -> Optional[Dict[str, Any]]:
    """Deterministic recall: best recipe for (part_id, context) or None."""
    return recipes.get(part_recipe_key(part_id, context))
