import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.interaction_logger import interaction_logger
from rhinoclaw.utils.part_recipe_distiller import (
    distill_part_recipes,
    lookup_part_recipe,
)
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def recall_part_placements(
    ctx: Context,
    part_id: str,
    context: Optional[str] = None,
) -> str:
    """Recall the best judge-verified placement for a library part.

    The read side of the part-library loop. Distills the outcome corpus
    (`logs/interactions_*.jsonl`, judge-verified `part_outcome` records
    with `pass: true`) into `logs/part_recipes.json` and returns the best
    known recipe for `part_id|context` — "best" = lowest judge-measured
    `worst_probe_mm`, never an agent claim. The recipe carries the
    verified `target_frame` (9-double world plane) and the measured
    `xform` (16 doubles), ready to reuse with insert_library_part.

    **Deterministic lookup, no LLM call.** Cold start returns
    `found: false` with a hint to place + judge first.

    Agent flow: `recall_part_placements` -> seed insert_library_part ->
    `judge_part_placement` (logs outcomes) -> next recall starts from the
    best verified answer.

    Parameters:
    - part_id: Library part id (e.g. "kauls/aufnahmeelement-band-stumpf-vx").
    - context: Free-form placement context chosen at judge time
      (e.g. "door-right-900"; default "default").

    Returns:
        found: {"success": true, "data": {"found": true, "target_frame":
            [...9...], "xform": [...16...], "worst_probe_mm": 0.02,
            "confidence": 3, "last_seen": "..."}}
        miss:  {"success": true, "data": {"found": false,
            "known_keys": [...], "hint": "..."}}
    """
    try:
        if not part_id:
            raise ValueError("part_id is required")

        # Re-distill on every call: the corpus is small JSONL and this keeps
        # the registry consistent with the latest judge verdicts.
        log_dir = interaction_logger._log_dir
        recipes = distill_part_recipes(log_dir)
        recipe = lookup_part_recipe(recipes, part_id, context)

        if recipe is None:
            return json.dumps(ok(
                message=f"No prior passing placement for "
                        f"({part_id}, {context or 'default'})",
                data={
                    "found": False,
                    "part_id": part_id,
                    "context": context or "default",
                    "known_keys": sorted(recipes.keys()),
                    "hint": "no prior passing placement — place with "
                            "insert_library_part, then "
                            "judge_part_placement(log_outcomes=True) so "
                            "the next attempt can recall it",
                },
            ))

        return json.dumps(ok(
            message=f"Best verified placement for ({recipe['part_id']}, "
                    f"{recipe['context']}): worst probe "
                    f"{recipe['worst_probe_mm']} mm, "
                    f"confidence {recipe['confidence']}",
            data={"found": True, **recipe},
        ))
    except Exception as e:
        logger.error(f"Error recalling part placements: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
