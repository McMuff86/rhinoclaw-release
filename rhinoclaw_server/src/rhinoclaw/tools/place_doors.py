import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.door_batch import run_doors_batch
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.gh_player import run_player_for_door
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def place_doors(
    ctx: Context,
    definition: str,
    items: List[Dict[str, Any]],
    defaults: Optional[Dict[str, Any]] = None,
    auto_group: bool = True,
    continue_on_error: bool = True,
    timeout_per_door: float = 120.0,
) -> str:
    """Place a batch of oriented doors from a GH definition into the document.

    Runs the door definition once per item through GrasshopperPlayer
    (prompt-feeding, the proven rhinoclaw_client mechanic), then post-processes the
    freshly created objects: move to `layer`, rotate by `rotation` around
    the placement point, group under the door's `id`. The per-door result
    reports the **real baked geometry** — `object_ids` from a before/after
    document diff and `baked_bbox` read back via `get_objects_info` — never
    the request parameters, so a judge can verify the placement without
    trusting this tool's own claims.

    Parameters:
    - definition: Windows path to the door `.gh` file
      (e.g. `C:/proj/Rahmentuer_UD5.gh`).
    - items: One dict per door. Natural floor-plan vocabulary (lowercase
      aliases accepted): `id` ("RT01"), `pt`/`point` ([x, y, z] or "x,y,z"),
      `rotation` (degrees around Z at the placement point), `lichtbreite`,
      `lichthoehe`, `rahmendicke`, `tuerstaerke`, `group`, `layer`,
      `wall_axis` ("x" | "y", judge metadata — echoed in the result, not
      sent to the player). Unknown keys pass through as GH prompt values.
    - defaults: Values merged under every item (e.g. {"lichthoehe": 2100}).
    - auto_group: Group each door's objects under its `id` when no explicit
      `group` is given (default true).
    - continue_on_error: Keep placing remaining doors when one fails.
    - timeout_per_door: Max seconds per GrasshopperPlayer run.

    Returns:
        {"success": true, "data": {
            "status": "success" | "partial",
            "total": N, "succeeded": n, "failed": m,
            "doors": [{"id", "status", "object_ids", "object_count",
                       "baked_bbox",   // [[xmin,ymin,zmin],[xmax,ymax,zmax]]
                                       // from get_objects_info — real geometry
                       "rotation_applied", "point", "width_requested",
                       "wall_axis", "group", "layer"}, ...]}}

    Example:
        place_doors(
            definition="C:/proj/Rahmentuer_UD5.gh",
            defaults={"lichthoehe": 2100},
            items=[
                {"id": "RT01", "pt": [0, 0, 0], "rotation": 0,
                 "lichtbreite": 900, "wall_axis": "x"},
                {"id": "RT02", "pt": [3500, 0, 0], "rotation": 90,
                 "lichtbreite": 800, "wall_axis": "y"},
            ],
        )

    Notes:
        - Requires Grasshopper available in the running Rhino (`mcpstart`).
        - Verify with `get_objects_info(ids)` / the upcoming
          `judge_door_placement`; the result's `baked_bbox` is the ground
          truth half of that loop.
        - Each underlying command is idempotency-key stamped, so a
          reconnect-retry mid-door cannot bake a door twice.
    """
    try:
        if not definition or not str(definition).lower().endswith(('.gh', '.ghx')):
            raise ValueError("definition must point to a .gh or .ghx file")
        if not isinstance(items, list) or not items:
            raise ValueError("items must be a non-empty list of door dicts")
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("every item must be a dict")

        rhino = get_rhino_connection()

        def runner(file_path: str, params: Dict[str, Any]) -> Dict[str, Any]:
            return run_player_for_door(rhino, file_path, params,
                                       timeout=timeout_per_door)

        batch = run_doors_batch(
            definition,
            items,
            runner=runner,
            defaults=defaults,
            auto_group=auto_group,
            continue_on_error=continue_on_error,
        )

        if batch.get('status') == 'error':
            return json.dumps(from_exception(
                RuntimeError(batch.get('message', 'door batch failed')),
                code=ErrorCode.RHINO_ERROR,
            ))

        return json.dumps(ok(
            message=(
                f"Placed {batch.get('succeeded', 0)}/{batch.get('total', 0)} "
                f"door(s) from {definition}"
            ),
            data=batch,
        ))
    except Exception as e:
        logger.error(f"Error placing doors: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
