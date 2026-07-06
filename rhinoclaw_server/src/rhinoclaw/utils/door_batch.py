"""Shared door-batch placement core (NEXT-LEVEL-PLAN workstream 1.3).

ONE module owns normalization, batching, and result projection for door
placement; the rhinoclaw_client CLI (`scripts/rhinoclaw_client/grasshopper.py`) and the
`place_doors` MCP tool both import it. The actual GrasshopperPlayer run is
injected as `runner(definition, params) -> dict`, so this module stays
transport-free and unit-testable without Rhino.

IMPORTANT: stdlib-only by design — `scripts/sync-skill.sh` copies this file
verbatim into the deployed OpenClaw skill, where the `rhinoclaw` package is
not installed.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("rhinoclaw.door_batch")

# User-facing lowercase keys → canonical names that the player runner
# understands. Lets callers write the natural floor-plan vocabulary
# ({"pt": [...], "rotation": 90, "lichtbreite": 900}) instead of the GH
# nicknames. `wall_axis` is judge metadata (NEXT-LEVEL-PLAN 2.1), consumed
# by the batch loop itself — it is never sent to the player.
DOOR_KEY_MAP = {
    'pt': 'Point', 'point': 'Point', 'punkt': 'Point', 'pos': 'Point',
    'rotation': 'Rotation', 'angle': 'Rotation', 'winkel': 'Rotation',
    'lichtbreite': 'Lichtbreite',
    'lichthoehe': 'Lichthoehe',
    'rahmendicke': 'Rahmendicke',
    'tuerstaerke': 'Tuerstaerke',
    'group': 'Group',
    'layer': 'Layer',
    'wall_axis': 'WallAxis', 'wallaxis': 'WallAxis', 'wandachse': 'WallAxis',
}


def normalize_door_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map user lowercase keys to canonical names. Unknown keys pass through."""
    out = {}
    for k, v in item.items():
        if k == 'id':
            continue
        out[DOOR_KEY_MAP.get(k.lower(), k)] = v
    return out


def parse_point(value) -> Optional[tuple]:
    """Accept 'x,y,z' strings or [x,y,z] sequences. Returns (x,y,z) or None."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return tuple(float(v) for v in value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(',')]
        if len(parts) == 3:
            try:
                return tuple(float(p) for p in parts)
            except ValueError:
                return None
    return None


def summarize_door_run(item_id: str, result: Dict[str, Any],
                       merged: Dict[str, Any],
                       wall_axis, width_requested) -> Dict[str, Any]:
    """Project a verbose player-run result into the per-door contract.

    `baked_bbox` comes from the runner's read-back of the freshly baked
    geometry (`get_objects_info` on the MCP path, `rs.BoundingBox` on the
    CLI path) — NEVER from the request parameters. That is the
    anti-self-grading rule the whole verification loop depends on.
    """
    baked_bbox = result.get('baked_bbox') or result.get('bbox')
    return {
        'id': item_id,
        'status': result.get('status'),
        'object_ids': result.get('created_guids', []),
        'object_count': result.get('objects_created', 0),
        'baked_bbox': baked_bbox,
        'bbox': baked_bbox,  # legacy rhinoclaw_client field name
        'layer': result.get('layer'),
        'group': result.get('group'),
        'rotation_applied': result.get('rotation_applied', 0),
        'point': merged.get('Point'),
        'width_requested': width_requested,
        'wall_axis': wall_axis,
    }


def run_doors_batch(definition: str, items: List[Dict[str, Any]],
                    runner: Callable[[str, Dict[str, Any]], Dict[str, Any]],
                    defaults: Optional[Dict[str, Any]] = None,
                    auto_group: bool = True,
                    continue_on_error: bool = True) -> Dict[str, Any]:
    """Place a batch of doors via the injected player `runner`.

    Each item is normalized, the GH definition runs once per door, and the
    resulting GUIDs are auto-grouped under the door's `id` (RT01, RT02, …)
    so a follow-up agent can address each door as a single selectable unit.
    The summary captures object_ids / baked_bbox / layer per door.
    """
    # Defaults speak the same lowercase vocabulary as the items.
    defaults = normalize_door_item(defaults or {})
    if not items:
        return {'status': 'error', 'message': 'No items provided'}

    results = []
    for i, item in enumerate(items):
        item_id = str(item.get('id', f'door_{i+1}'))
        merged = {**defaults, **normalize_door_item(item)}

        # Auto-group under the door's id unless the caller explicitly named one.
        if auto_group and 'Group' not in merged:
            merged['Group'] = item_id

        # Judge metadata: keep for the summary, never send to the player.
        wall_axis = merged.pop('WallAxis', None)
        width_requested = merged.get('Lichtbreite')

        logger.info(
            f"Door [{i+1}/{len(items)}] {item_id}: "
            f"pt={merged.get('Point', '?')} rot={merged.get('Rotation', 0)}°"
        )

        try:
            result = runner(definition, merged)
        except Exception as e:
            err = {'id': item_id, 'status': 'error', 'message': str(e)}
            if continue_on_error:
                results.append(err)
                continue
            return {'status': 'error', 'message': f'Failed at {item_id}: {e}',
                    'completed': results}

        results.append(
            summarize_door_run(item_id, result, merged, wall_axis, width_requested)
        )

    succeeded = sum(
        1 for r in results
        if r.get('status') == 'success' and r.get('object_count', 0) > 0
    )
    failed = len(results) - succeeded

    return {
        'status': 'success' if failed == 0 else 'partial',
        'definition': definition,
        'total': len(items),
        'succeeded': succeeded,
        'failed': failed,
        'doors': results,
    }
