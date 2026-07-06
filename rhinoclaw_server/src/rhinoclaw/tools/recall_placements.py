import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.interaction_logger import interaction_logger
from rhinoclaw.utils.recipe_distiller import distill, lookup
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def recall_placements(
    ctx: Context,
    door_type: str,
    wall_axis: str,
) -> str:
    """Recall the best judge-verified parameters for a door placement.

    The read side of the self-improving loop. Distills the outcome corpus
    (`logs/interactions_*.jsonl`, judge-verified `placement_outcome` records
    with `pass: true`) into `logs/door_recipes.json` and returns the best
    known recipe for `(door_type, wall_axis)` — "best" = lowest
    judge-measured `off_center_mm`, never an agent claim.

    **Deterministic lookup, no LLM call.** Cold start returns
    `found: false` with a hint to use defaults.

    Agent flow (see AGENTS.md): `recall_placements` → seed the request →
    `place_doors` → `judge_door_placement` (logs outcomes) → next recall
    starts from the best verified answer.

    Parameters:
    - door_type: The door definition — a path or filename
      (e.g. "Rahmentuer_UD5.gh"; matched on the lowercase basename).
    - wall_axis: "x" or "y" — the wall axis the opening lies on.

    Returns:
        found: {"success": true, "data": {"found": true,
            "rotation": 90, "width": 800, "off_center_mm": 3.5,
            "confidence": 2, "last_seen": "..."}}
        miss:  {"success": true, "data": {"found": false,
            "hint": "no prior passing placement — use defaults"}}
    """
    try:
        if not door_type:
            raise ValueError("door_type is required")
        if not wall_axis:
            raise ValueError("wall_axis is required ('x' or 'y')")

        # Re-distill on every call: the corpus is small JSONL and this keeps
        # the registry consistent with the latest judge verdicts.
        log_dir = interaction_logger._log_dir
        recipes = distill(log_dir)
        recipe = lookup(recipes, door_type, wall_axis)

        if recipe is None:
            return json.dumps(ok(
                message=f"No prior passing placement for "
                        f"({door_type}, {wall_axis})",
                data={
                    "found": False,
                    "door_type": door_type,
                    "wall_axis": wall_axis,
                    "known_keys": sorted(recipes.keys()),
                    "hint": "no prior passing placement — use defaults, then "
                            "judge_door_placement(log_outcomes=True) so the "
                            "next attempt can recall it",
                },
            ))

        return json.dumps(ok(
            message=f"Best verified placement for ({recipe['door_type']}, "
                    f"{recipe['wall_axis']}): rotation {recipe['rotation']}, "
                    f"width {recipe['width']} "
                    f"(off_center {recipe['off_center_mm']} mm, "
                    f"confidence {recipe['confidence']})",
            data={"found": True, **recipe},
        ))
    except Exception as e:
        logger.error(f"Error recalling placements: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
