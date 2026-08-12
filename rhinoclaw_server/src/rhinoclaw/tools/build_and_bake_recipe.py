import json
from typing import Any, Dict, Optional
from uuid import UUID

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.tools.build_gh_interactive import build_gh_interactive
from rhinoclaw.tools.find_gh_component import _catalog
from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError
from rhinoclaw.utils.gh_catalog import (
    catalog_verification_failure_data,
    catalog_contract,
    require_catalog_verification,
)
from rhinoclaw.utils.gh_recipes import COMPOSITION_RECIPES, list_compositions
from rhinoclaw.utils.responses import error, from_exception, ok


def _primitive_catalog_contract(rhino, recipe: str) -> Dict[str, Any]:
    """Resolve one primitive through the plugin's single-source registry."""
    registry = rhino.send_command("build_and_bake_recipe", {"recipe": "list"})
    recipes = registry.get("recipes") if isinstance(registry, dict) else None
    entry = recipes.get(recipe) if isinstance(recipes, dict) else None
    if not isinstance(entry, dict):
        available = sorted(recipes) if isinstance(recipes, dict) else []
        raise ValueError(
            f"Unknown primitive recipe '{recipe}'. Available: {available}"
        )

    raw_guid = entry.get("guid")
    try:
        guid = str(UUID(str(raw_guid)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RhinoCommandError(
            "Primitive recipe registry lacks a valid component GUID; "
            "update/restart the RhinoClaw plugin",
            error_code=ErrorCode.VERIFICATION_FAILED,
            response=registry,
        ) from exc

    try:
        return catalog_contract(_catalog(), [guid])
    except ValueError as exc:
        raise RhinoCommandError(
            f"Primitive recipe '{recipe}' uses component {guid}, which is "
            f"not authorable from the active catalog: {exc}",
            error_code=ErrorCode.VERIFICATION_FAILED,
            response=registry,
        ) from exc


@mcp.tool()
def build_and_bake_recipe(
    ctx: Context,
    recipe: str,
    file_path: str = "",
    params: Optional[Dict[str, float]] = None,
    layer: str = "GH_Bake",
    material: Optional[str] = None,
) -> str:
    """Build + solve + bake a parametric graph from a verified native recipe.

    Two registries behind one entry point, both SDK-native (solve headless,
    unlike `python3_script` components):

    - **Primitives** (`box`/`sphere`/`cylinder`/`cone`) — live in the
      plugin, work identically over MCP and raw TCP.
    - **Compositions** (`rect_extrude`/`box_difference`/`box_array`/
      `box_orient`) — multi-component graphs from `utils/gh_recipes.py`,
      instantiated from the component catalog and run through the FULL
      verified loop (`build_gh_interactive`): lint → bake → re-measure →
      judge against the recipe's own computed expectation (dims/corners/
      count derived from your params). The response carries the loop's
      verdict — check `data.pass`, not just the bake status.

    Parameters:
    - recipe: a recipe name, or `list` for both registries + their
      parameter names (no `.gh` needed; compositions list offline).
    - file_path: output `.gh` path (must end in `.gh`; required unless `list`).
    - params: numeric overrides, e.g. `{"x":40,"y":20,"z":10}` (box),
      `{"x":400,"y":200,"height":100}` (rect_extrude),
      `{"count":4,"step":150}` (box_array). Composition box params are
      HALF-extents (Center Box semantics).
    - layer / material: bake target.

    Returns: `{"success": true, "data": {... baked_count, baked_ids, status ...}}`,
    for compositions the full loop verdict `{pass, measured, expect_check,
    hints, recipe ...}`, or `{... recipes: {...}}` for `list`.

    Note: the primitive registry requires a plugin build with the
    `build_and_bake_recipe` command (RhinoClaw 0.5.0+). On older plugins
    primitives error with UNKNOWN_COMMAND; compositions still work (they
    only need `build_and_bake_gh`).
    """
    is_list = recipe == "list"
    primitive_run_attempted = False
    if not is_list:
        if not file_path:
            return json.dumps(from_exception(
                ValueError("file_path is required"), code=ErrorCode.INVALID_PARAMS))
        if not file_path.lower().endswith(".gh"):
            return json.dumps(from_exception(
                ValueError("file_path must be a .gh file"), code=ErrorCode.INVALID_PARAMS))

    # --- composition recipes: instantiate + run the verified loop ---
    if recipe in COMPOSITION_RECIPES:
        try:
            spec = COMPOSITION_RECIPES[recipe].instantiate(params)
        except ValueError as e:
            return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
        raw = build_gh_interactive(
            ctx,
            file_path=file_path,
            components=spec["components"],
            wires=spec["wires"],
            layer=layer,
            expect=spec["expect"],
            label=f"recipe:{recipe}",
            material=material,
        )
        result = json.loads(raw)
        if isinstance(result.get("data"), dict):
            result["data"]["recipe"] = {"name": recipe, "kind": "composition",
                                        "params": spec["params"]}
            result["message"] = f"Recipe '{recipe}': {result['message']}"
        return json.dumps(result)

    try:
        compositions = list_compositions()
        if is_list:
            # Plugin registry is best-effort — compositions list offline.
            plugin_recipes: Dict[str, Any] = {}
            plugin_error = None
            try:
                rhino = get_rhino_connection()
                result = rhino.send_command("build_and_bake_recipe",
                                            {"recipe": "list"})
                plugin_recipes = result.get("recipes", {})
            except Exception as e:
                plugin_error = str(e)
            merged = {**plugin_recipes, **compositions}
            data: Dict[str, Any] = {"recipes": merged}
            if plugin_error:
                data["plugin_registry_error"] = plugin_error
            return json.dumps(ok(
                message=f"{len(merged)} recipes available "
                        f"({len(compositions)} composition, "
                        f"{len(plugin_recipes)} primitive)",
                data=data,
            ))

        rhino = get_rhino_connection()
        primitive_contract = _primitive_catalog_contract(rhino, recipe)
        cmd: Dict[str, Any] = {"recipe": recipe, "file_path": file_path,
                               "layer": layer,
                               "catalog_contract": primitive_contract}
        if params:
            cmd["params"] = params
        if material is not None:
            cmd["material"] = material

        primitive_run_attempted = True
        result = rhino.send_command("build_and_bake_recipe", cmd)
        require_catalog_verification(result)
        return json.dumps(ok(
            message=f"Recipe '{recipe}' → {result.get('baked_count', 0)} object(s) "
                    f"on layer '{result.get('layer', layer)}' (status={result.get('status')})",
            data=result,
        ))
    except Exception as e:
        logger.error(f"build_and_bake_recipe failed: {e}")
        if (
            isinstance(e, RhinoCommandError)
            and e.error_code == ErrorCode.VERIFICATION_FAILED
        ):
            return json.dumps(error(
                str(e),
                code=ErrorCode.VERIFICATION_FAILED,
                data=catalog_verification_failure_data(
                    e, mutation_attempted=primitive_run_attempted),
            ))
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
