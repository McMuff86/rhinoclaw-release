"""GrasshopperPlayer runner over the MCP server's plugin connection.

Port of the proven rhinoclaw_client mechanic (`scripts/rhinoclaw_client/grasshopper.py`):
prompt-feeding loop + GUID before/after diff + post-processing
(layer → rotation → group). Used by the `place_doors` MCP tool.

One deliberate difference from the CLI: `baked_bbox` is read back via the
plugin's `get_objects_info` on the freshly created GUIDs — real baked
geometry, NEVER derived from the request parameters (the anti-self-grading
rule from NEXT-LEVEL-PLAN; the domain judge consumes this value).

Every `send_command` is idempotency-key stamped by `RhinoConnection`, so a
reconnect-retry mid-door cannot bake twice.
"""
import json
import logging
import re
import time
from typing import Any, Dict, Optional

from rhinoclaw.utils.door_batch import parse_point

logger = logging.getLogger("rhinoclaw.gh_player")

_PRINT_PREFIX = "Script successfully executed! Print output: "

# Keys consumed by the runner itself instead of being sent to the
# GrasshopperPlayer prompt loop. UD5-style definitions only expose `Pt` as
# a placement input, so orientation, grouping, and layer routing are
# applied as post-processing on the freshly-created GUIDs.
_CONTROL_KEYS = {'Rotation', 'Group', 'Layer'}


def parse_prompt(prompt: str) -> tuple:
    """Parse a GrasshopperPlayer prompt into (parameter_name, default_value).

    Examples:
        "Lichthoehe <2100>" -> ("Lichthoehe", "2100")
        "Get Point ( Undo )" -> ("Point", None)
        "RahmenbreiteL <120> ( Undo )" -> ("RahmenbreiteL", "120")
        "Bandseite:" -> ("Bandseite", None)
        "Get String ( Undo )" -> ("Get String", None)
    """
    match = re.match(r'([A-Za-z_][A-Za-z0-9_ ]*?)\s*<([^>]+)>', prompt)
    if match:
        return match.group(1).strip(), match.group(2)

    if 'Point' in prompt:
        return 'Point', None

    if 'Get String' in prompt or 'String' in prompt:
        return 'Get String', None

    match = re.match(r'([A-Za-z_][A-Za-z0-9_äöüÄÖÜ]*)\s*[\(:]', prompt)
    if match:
        return match.group(1).strip(), None

    match = re.match(r'^([A-Za-z_][A-Za-z0-9_äöüÄÖÜ]*)\s*$', prompt.strip().rstrip(':'))
    if match:
        return match.group(1).strip(), None

    return None, None


def _exec_print(rhino, code: str) -> str:
    """Run python in Rhino, return whatever was printed (stdout) as a string."""
    raw = rhino.send_command('execute_rhinoscript_python_code', {'code': code})
    if isinstance(raw, str):
        if raw.startswith(_PRINT_PREFIX):
            return raw[len(_PRINT_PREFIX):].strip()
        return raw.strip()
    if isinstance(raw, dict):
        nested = raw.get('output', raw.get('result', ''))
        if isinstance(nested, str):
            if nested.startswith(_PRINT_PREFIX):
                return nested[len(_PRINT_PREFIX):].strip()
            return nested.strip()
        return str(nested or '').strip()
    return ''


def _get_all_object_ids(rhino) -> set:
    code = (
        "import rhinoscriptsyntax as rs\n"
        "ids = rs.AllObjects()\n"
        "print(','.join(str(i) for i in ids) if ids else '')\n"
    )
    output = _exec_print(rhino, code)
    if output:
        return {tok for tok in (s.strip() for s in output.split(',')) if tok}
    return set()


def _rhino_file_exists(rhino, file_path: str) -> Optional[bool]:
    """Ask Rhino whether it can see `file_path`. None = indeterminate.

    The check runs IN Rhino because the server may live in WSL and cannot
    judge Windows paths itself. (IronPython 2.7: no `exist_ok` etc. —
    plain os.path.exists only.)
    """
    code = (
        "import os\n"
        f"print('1' if os.path.exists({json.dumps(file_path)}) else '0')\n"
    )
    try:
        out = _exec_print(rhino, code)
    except Exception:
        return None
    if out == '1':
        return True
    if out == '0':
        return False
    return None


def _start_player(rhino, file_path: str) -> bool:
    escaped_path = file_path.replace('\\', '\\\\')
    code = (
        "import Rhino\n"
        f'cmd = \'_-GrasshopperPlayer "{escaped_path}"\'\n'
        "Rhino.RhinoApp.SendKeystrokes(cmd + chr(13), True)\n"
    )
    try:
        rhino.send_command('execute_rhinoscript_python_code', {'code': code})
        return True
    except Exception as e:
        logger.error(f"Failed to start GrasshopperPlayer: {e}")
        return False


def _get_current_prompt(rhino) -> str:
    result = rhino.send_command('get_command_history', {'lines': 1})
    if isinstance(result, dict):
        return result.get('command_prompt', '')
    return ''


def _send_input(rhino, text: str) -> None:
    escaped = text.replace('"', '\\"')
    code = f'import Rhino; Rhino.RhinoApp.SendKeystrokes("{escaped}" + chr(13), True)'
    rhino.send_command('execute_rhinoscript_python_code', {'code': code})


def _set_objects_layer(rhino, guids, layer_name: str) -> bool:
    """Move GUIDs onto `layer_name`, creating the layer if missing."""
    if not guids or not layer_name:
        return False
    code = (
        "import rhinoscriptsyntax as rs\n"
        f"guids = {json.dumps(list(guids))}\n"
        f"layer = {json.dumps(layer_name)}\n"
        "if not rs.IsLayer(layer):\n"
        "    rs.AddLayer(layer)\n"
        "moved = 0\n"
        "for g in guids:\n"
        "    try:\n"
        "        rs.ObjectLayer(g, layer); moved += 1\n"
        "    except Exception:\n"
        "        pass\n"
        "print(moved)\n"
    )
    out = _exec_print(rhino, code)
    return bool(out) and out.isdigit() and int(out) > 0


def _rotate_objects_zaxis(rhino, guids, pivot, angle_deg: float) -> bool:
    """Rotate the given GUIDs around `pivot` (x,y,z) on the world XY plane."""
    if not guids or not angle_deg or pivot is None:
        return False
    code = (
        "import rhinoscriptsyntax as rs\n"
        f"guids = {json.dumps(list(guids))}\n"
        f"pivot = ({pivot[0]}, {pivot[1]}, {pivot[2]})\n"
        f"angle = {float(angle_deg)}\n"
        "rs.RotateObjects(guids, pivot, angle)\n"
        "print('OK')\n"
    )
    return _exec_print(rhino, code) == 'OK'


def _add_objects_to_group(rhino, guids, group_name: str):
    """Place GUIDs in a named group (creates it if needed). Returns the name."""
    if not guids or not group_name:
        return None
    code = (
        "import rhinoscriptsyntax as rs\n"
        f"guids = {json.dumps(list(guids))}\n"
        f"name = {json.dumps(group_name)}\n"
        "if not rs.IsGroup(name):\n"
        "    rs.AddGroup(name)\n"
        "rs.AddObjectsToGroup(guids, name)\n"
        "print(name)\n"
    )
    out = _exec_print(rhino, code)
    return out or group_name


def union_bbox(objects_info: Dict[str, Any]) -> Optional[list]:
    """Axis-aligned union of `get_objects_info` bounding boxes.

    Returns [[xmin, ymin, zmin], [xmax, ymax, zmax]] or None.
    """
    mins, maxs = [], []
    for entry in (objects_info or {}).get('results', []):
        box = (entry.get('geometry_details') or {}).get('bounding_box')
        if not box:
            continue
        mins.append(box.get('min'))
        maxs.append(box.get('max'))
    if not mins:
        return None
    return [
        [min(v[i] for v in mins) for i in range(3)],
        [max(v[i] for v in maxs) for i in range(3)],
    ]


def run_player_for_door(rhino, file_path: str, params: Dict[str, Any],
                        timeout: float = 120.0, sleep=time.sleep) -> Dict[str, Any]:
    """Run a door definition through GrasshopperPlayer with post-processing.

    `rhino` is a connection object exposing `send_command(type, params)`
    (normally `get_rhino_connection()`). `sleep` is injectable for tests.
    """
    params = dict(params or {})

    # Pull post-processing controls out before the prompt loop.
    control_params = {k: params.pop(k) for k in list(params) if k in _CONTROL_KEYS}
    rotation_deg = 0.0
    if 'Rotation' in control_params:
        try:
            rotation_deg = float(control_params['Rotation'])
        except (TypeError, ValueError):
            logger.warning(
                f"Invalid Rotation '{control_params['Rotation']}' — ignoring"
            )
    group_name = control_params.get('Group')
    target_layer = control_params.get('Layer')

    # Fail fast on a missing definition — otherwise the prompt loop runs
    # blind into the full timeout and reports an empty "success".
    if _rhino_file_exists(rhino, file_path) is False:
        raise FileNotFoundError(
            f"Definition not found by Rhino: {file_path} — the path must be "
            "visible to the WINDOWS Rhino process (e.g. C:/Users/...), not a "
            "WSL path."
        )

    # Pre-load GH parameter metadata for smart prompt matching.
    gh_param_map: Dict[str, Dict[str, Any]] = {}
    try:
        meta = rhino.send_command('load_grasshopper_definition',
                                  {'file_path': file_path})
        for p in (meta or {}).get('parameters', []):
            nick = (p.get('nickname') or p.get('name') or '').strip()
            if not nick:
                continue
            key = nick.lower()
            # Prefer entries with actual values (NumberSlider over Number).
            if key not in gh_param_map or p.get('value') is not None:
                gh_param_map[key] = {
                    'name': nick,
                    'type': p.get('type', ''),
                    'value': p.get('value'),
                }
        defid = (meta or {}).get('definition_id')
        if defid:
            rhino.send_command('unload_grasshopper_definition',
                               {'definition_id': defid})
    except Exception as e:
        logger.warning(f"Could not pre-load GH parameters: {e}")

    # Snapshot object IDs before the run.
    track_objects = True
    before_ids: set = set()
    try:
        before_ids = _get_all_object_ids(rhino)
    except Exception as e:
        logger.warning(f"Could not snapshot objects before run: {e}")
        track_objects = False

    if not _start_player(rhino, file_path):
        return {'status': 'error', 'message': 'Failed to start GrasshopperPlayer'}

    sleep(1.0)

    # Prompt loop — feed values, accept defaults for unknown prompts.
    last_prompt = ''
    prompts_handled = []
    start_time = time.monotonic()

    while time.monotonic() - start_time < timeout:
        prompt = _get_current_prompt(rhino)

        if prompt == last_prompt:
            sleep(0.2)
            continue
        last_prompt = prompt

        if prompt.strip() == 'Command':
            if prompts_handled:
                logger.info("GrasshopperPlayer finished")
                break
            sleep(0.5)
            continue

        param_name, default_value = parse_prompt(prompt)

        if param_name:
            if param_name == 'Point' and 'Point' in params:
                pt = params['Point']
                if isinstance(pt, (list, tuple)):
                    value = f"{pt[0]},{pt[1]},{pt[2]}"
                else:
                    value = str(pt)
            elif param_name in params:
                value = str(params[param_name])
            elif param_name == 'Point':
                value = "0,0,0"
            else:
                value = ""  # accept the definition's default
        else:
            stripped = prompt.strip().rstrip(':').strip()
            stripped = re.sub(r'\s*\(\s*Undo\s*\)\s*', '', stripped).strip()
            if not stripped or stripped == 'Command':
                sleep(0.2)
                continue

            matched_key = next(
                (k for k in params if k.lower() == stripped.lower()), None
            )
            if matched_key:
                param_name = stripped
                value = str(params[matched_key])
            else:
                gh_info = gh_param_map.get(stripped.lower())
                if gh_info:
                    param_name = gh_info['name']
                    default = gh_info.get('value')
                    value = str(default) if default is not None else ""
                else:
                    param_name = stripped
                    value = ""

        _send_input(rhino, value)
        prompts_handled.append({
            'name': param_name,
            'value': value if value else (default_value or ''),
            'was_custom': param_name in params,
        })
        sleep(0.3)

    # GUID diff → the freshly created objects.
    new_ids: list = []
    if track_objects:
        try:
            new_ids = sorted(_get_all_object_ids(rhino) - before_ids)
            logger.info(f"Objects created: {len(new_ids)}")
        except Exception as e:
            logger.warning(f"Could not calculate object diff: {e}")

    # Post-processing: layer first (keeps rotate/group aligned with the
    # target), then rotation around the placement point, then grouping.
    rotation_applied = 0.0
    group_applied = None
    layer_applied = None
    baked_bbox = None

    if new_ids:
        if target_layer:
            try:
                if _set_objects_layer(rhino, new_ids, target_layer):
                    layer_applied = target_layer
            except Exception as e:
                logger.warning(f"Failed to move objects to layer '{target_layer}': {e}")

        if rotation_deg:
            pivot = parse_point(params.get('Point')) or (0.0, 0.0, 0.0)
            try:
                if _rotate_objects_zaxis(rhino, new_ids, pivot, rotation_deg):
                    rotation_applied = rotation_deg
            except Exception as e:
                logger.warning(f"Failed to rotate objects by {rotation_deg}°: {e}")

        if group_name:
            try:
                group_applied = _add_objects_to_group(rhino, new_ids, group_name)
            except Exception as e:
                logger.warning(f"Failed to group as '{group_name}': {e}")

        # Read the REAL baked geometry back — the judge consumes this, so it
        # must come from the document, never from the request parameters.
        try:
            info = rhino.send_command('get_objects_info', {'ids': list(new_ids)})
            baked_bbox = union_bbox(info)
        except Exception as e:
            logger.warning(f"Could not read baked bbox via get_objects_info: {e}")

    # 'no_geometry' (instead of a hollow 'success') when the player ran but
    # demonstrably produced nothing — the batch summary counts it as failed
    # and the agent sees WHY a door has no object_ids.
    status = 'success'
    if track_objects and not new_ids:
        status = 'no_geometry'

    return {
        'status': status,
        'file': file_path,
        'prompts_handled': prompts_handled,
        'objects_created': len(new_ids) if track_objects else 0,
        'created_guids': new_ids,
        'rotation_applied': rotation_applied,
        'group': group_applied,
        'layer': layer_applied,
        'baked_bbox': baked_bbox,
    }
