import json
from typing import Any, Dict

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def inspect_grasshopper_definition(
    ctx: Context,
    file_path: str,
    include_components: bool = False,
    only_player_inputs: bool = False,
) -> str:
    """Inspect a Grasshopper definition file without solving it.

    Loads the .gh / .ghx file, walks its objects, and returns metadata
    about every input the agent can drive, every output it can read, and
    the overall component count. Stateless: the document is disposed
    immediately after introspection. Use this before
    `run_grasshopper` / `load_grasshopper_definition` to learn the
    parameter surface of an unfamiliar definition.

    Parameters:
    - file_path: Absolute path to the .gh or .ghx file.
    - include_components: When True, include a `components_by_type`
      summary listing how many of each GH object type the document
      contains. Off by default to keep responses compact.
    - only_player_inputs: When True, return only the **logical** Player
      inputs. Sliders / panels / toggles / value-lists wired directly
      into a prompt parameter are merged INTO that prompt — their
      `value` becomes the prompt's `default`, slider min/max/decimals
      land on the prompt — instead of being listed as separate inputs.
      Internal helper sliders that don't feed any prompt are dropped.
      A definition with 21 internal sliders and 4 player prompts
      typically collapses to 4 inputs.

    Returns:
        JSON with keys:
        - `file_path`, `file_name`, `object_count`
        - `input_count`, `output_count`
        - `inputs`: list of dicts. Common keys: `name`, `nickname`,
          `kind` (`prompt` | `slider` | `toggle` | `panel` |
          `value_list` | `param`), `type`, `is_player_input` (bool),
          `component_guid`.
          Prompts (Get-Integer / Get-Number / Get-Point / Get-String /
          Get-Boolean / Get-Curve / …) additionally carry `prompt`
          text, `presets` list, and — if a default-value source is
          wired in — `value` / `default` plus `min` / `max` /
          `decimals` (for slider-backed prompts) and a small
          `default_source` summary linking back to the upstream
          control.
          Sliders that act as a prompt's default source carry
          `is_prompt_default_source: true` and `feeds_prompt_guid`
          pointing at the prompt they belong to.
        - `outputs`: list of unconnected output ports
          (`name`, `nickname`, `type`, `component_name`, `is_script`).
        - `groups`: list of `{nickname, member_count, member_nicknames}` —
          relevant for the Compute Platform `RH_OUT:<Name>` group contract.
        - `script_component_count` + `headless_solvable`: script components
          (Python3/GhPython/C#) don't solve in headless GH on Rhino 8, so
          `headless_solvable` is true only for native-only definitions —
          check this BEFORE a `build_and_bake_gh` / `bake_grasshopper`
          round-trip.
        - `script_components`: per script component `{name, nickname, guid,
          type, outputs}` — script output names must stay valid script
          variable names (never `RH_OUT:*`).
        - `components_by_type` (only if `include_components=True`):
          list of `{type, count}`, sorted descending.

    Example:
        inspect_grasshopper_definition(
            file_path="C:/proj/Door.gh",
            only_player_inputs=True,
        )
    """
    try:
        rhino = get_rhino_connection()
        params: Dict[str, Any] = {"file_path": file_path}
        if include_components:
            params["include_components"] = True
        if only_player_inputs:
            params["only_player_inputs"] = True

        result = rhino.send_command("inspect_grasshopper_definition", params)
        return json.dumps(ok(
            message=f"Inspected {result.get('file_name', file_path)}: "
                    f"{result.get('input_count', 0)} inputs, "
                    f"{result.get('output_count', 0)} outputs",
            data=result,
        ))
    except Exception as e:
        logger.error(f"Error inspecting Grasshopper definition: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
