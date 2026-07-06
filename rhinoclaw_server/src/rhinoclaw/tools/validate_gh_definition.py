import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import logger, mcp
from rhinoclaw.tools.find_gh_component import _catalog
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.gh_lint import lint_definition
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def validate_gh_definition(
    ctx: Context,
    components: List[Dict[str, Any]],
    wires: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Lint a build_gh_definition spec BEFORE building — fail in
    milliseconds, not after a round-trip.

    Pure offline check (no Rhino call) of the exact `components`/`wires`
    you would pass to `build_gh_definition` / `build_and_bake_gh`:

    - unknown component types, missing required fields, duplicate names
    - **SDK GUIDs verified against the introspected component catalog**
      (the find_gh_component ground truth) + obsolete flags
    - wires to nonexistent components, unknown input/output port names,
      out-of-range indices
    - script I/O rules: identifiers only, never `RH_OUT:*` (can't bind)
    - headless reality: warns when script components are present
      (they don't solve headless on Rhino 8)

    Recommended flow: `find_gh_component` (look up GUIDs/ports) →
    `validate_gh_definition` (this) → `build_gh_definition` /
    `build_and_bake_gh`.

    Returns:
        {"success": true, "data": {"valid": true|false,
            "errors": [...], "warnings": [...],
            "component_count": N, "wire_count": M}}

    `valid: false` means the build WILL produce a broken/empty definition
    — fix the listed errors first.
    """
    try:
        if not isinstance(components, list):
            raise ValueError("components must be a list")
        result = lint_definition(components, wires, catalog=_catalog())
        n_err = len(result["errors"])
        n_warn = len(result["warnings"])
        return json.dumps(ok(
            message=("Definition spec is valid"
                     + (f" ({n_warn} warning(s))" if n_warn else "")
                     ) if result["valid"]
            else f"Spec INVALID: {n_err} error(s), {n_warn} warning(s)",
            data={**result,
                  "component_count": len(components),
                  "wire_count": len(wires or [])},
        ))
    except Exception as e:
        logger.error(f"Error validating GH definition spec: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
