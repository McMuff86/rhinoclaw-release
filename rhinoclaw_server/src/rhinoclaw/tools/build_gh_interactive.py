import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.tools.find_gh_component import _catalog
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.gh_critic import (
    bbox_dims,
    check_expectations,
    derive_bake_outputs,
)
from rhinoclaw.utils.gh_lint import lint_definition
from rhinoclaw.utils.gh_player import union_bbox
from rhinoclaw.utils.interaction_logger import interaction_logger
from rhinoclaw.utils.responses import from_exception, ok

# Bake attempts per call — the deterministic bake_output retry is cheap
# (one round-trip) but must never turn into a blind sweep.
_MAX_BAKE_ATTEMPTS = 3


def _build_attempt(rhino, file_path, components, wires, layer, bake_output,
                   material, description) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "file_path": file_path,
        "components": components,
        "wires": wires or [],
        "layer": layer,
        "bake_output": bake_output,
    }
    if material is not None:
        params["material"] = material
    if description is not None:
        params["description"] = description
    return rhino.send_command("build_and_bake_gh", params)


@mcp.tool()
def build_gh_interactive(
    ctx: Context,
    file_path: str,
    components: List[Dict[str, Any]],
    wires: Optional[List[Dict[str, Any]]] = None,
    layer: str = "GH_Bake",
    bake_output: Optional[str] = None,
    expect: Optional[Dict[str, Any]] = None,
    label: Optional[str] = None,
    iteration: int = 1,
    material: Optional[str] = None,
    description: Optional[str] = None,
    log_outcomes: bool = True,
) -> str:
    """ONE verified iteration of the GH authoring loop — lint, build+bake,
    inspect, measure, critique, log (NEXT-LEVEL 5.3).

    You (the agent) author the graph; this tool is the iteration engine
    that tells you deterministically what is wrong with it. Per call:

    1. **Lint** (offline, milliseconds): the `validate_gh_definition` rules —
       hallucinated GUIDs, bad ports, unbindable script outputs. Lint errors
       return immediately WITHOUT a Rhino round-trip (`stage_reached:"lint"`).
    2. **Build + bake**: `build_and_bake_gh` round-trip. When `bake_output`
       is omitted it is DERIVED from the component catalog (terminal
       component's geometry output — e.g. "B" for Center Box), and on a
       `no_geometry` result with `matched_outputs == 0` the next candidate
       is retried automatically (≤3 attempts) — one whole class of failures
       fixes itself inside the call.
    3. **Inspect** the written `.gh`: the headless verdict
       (`headless_solvable`, `script_component_count`) measured from the
       file on disk, not from the spec.
    4. **Measure**: `get_objects_info` on the baked ids → union bbox, dims.
       Claims never enter the verdict (the door-judge Goodhart rule).
    5. **Critique**: compares measured geometry against `expect` and turns
       every failure into an actionable hint.
    6. **Log**: one `graph_outcome` JSONL record — the corpus the recipe
       registry distills from.

    Recommended agent flow (mirrors the door loop recall → place → judge):
    `find_gh_component` (GUIDs/ports) → author spec → `build_gh_interactive`
    → read `hints` → refine the spec → call again with `iteration+1`.
    Target: `pass: true` in ≤3 iterations.

    Parameters:
    - file_path: Output `.gh` path (Windows path as seen by Rhino).
    - components / wires: The spec — same schema as `build_gh_definition`.
    - layer: Bake target layer (default "GH_Bake").
    - bake_output: Output nickname to bake. Omit to auto-derive from the
      catalog (recommended); pass explicitly to pin it.
    - expect: Optional measurable expectations:
      `{"min_count": 1, "dims_mm": [40,20,10], "bbox_min": [-20,-10,-5],
        "bbox_max": [20,10,5], "tolerance_mm": 1.0}` — all keys optional.
    - label: Stable name for this graph across iterations (recall key for
      the outcome corpus, e.g. "param_box").
    - iteration: 1-based loop counter — pass `iteration+1` on each refine.
    - log_outcomes: Write the `graph_outcome` record (default True).

    Returns:
        {"success": true, "data": {
            "pass": bool, "stage_reached": "lint"|"build"|"measure",
            "iteration": N, "label": "...",
            "lint": {"valid", "errors", "warnings"},
            "build": {"status", "baked_count", "baked_ids", "layer",
                      "bake_output_used", "attempts": [...], "diagnostics"},
            "inspect": {"headless_solvable", "script_component_count",
                        "object_count"} | null,
            "measured": {"bbox", "dims_mm", "count"} | null,
            "expect_check": {...} | null,
            "hints": ["actionable critique ...", ...]}}

    `pass` requires: lint clean, bake `status == "success"`, the written
    file `headless_solvable`, and every `expect` check within tolerance.
    """
    try:
        if not file_path or not file_path.lower().endswith(".gh"):
            raise ValueError("file_path is required and must end in .gh")
        if not isinstance(components, list) or not components:
            raise ValueError("components must be a non-empty list")
        iteration = max(1, int(iteration))

        catalog = _catalog()
        hints: List[str] = []

        def _verdict(stage: str, passed: bool, lint, build=None, inspect=None,
                     measured=None, expect_check=None) -> str:
            if log_outcomes:
                interaction_logger.log_graph_outcome({
                    "label": label,
                    "iteration": iteration,
                    "pass": passed,
                    "stage_reached": stage,
                    "lint_errors": len(lint["errors"]),
                    "build_status": (build or {}).get("status"),
                    "baked_count": (build or {}).get("baked_count", 0),
                    "bake_output_used": (build or {}).get("bake_output_used"),
                    "headless_solvable": (inspect or {}).get("headless_solvable"),
                    "expect_ok": (expect_check or {}).get("ok"),
                    "dims_mm": (measured or {}).get("dims_mm"),
                    "definition": file_path,
                })
            head = (f"Iteration {iteration}: "
                    + ("PASS" if passed else f"FAIL at stage '{stage}'"))
            return json.dumps(ok(
                message=head + (f" — {hints[0]}" if hints and not passed
                                else (f" — baked {(build or {}).get('baked_count', 0)}"
                                      f" object(s), headless-solvable, "
                                      f"{(expect_check or {}).get('checked', 0)}"
                                      f" expectation(s) met" if passed else "")),
                data={
                    "pass": passed,
                    "stage_reached": stage,
                    "iteration": iteration,
                    "label": label,
                    "lint": lint,
                    "build": build,
                    "inspect": inspect,
                    "measured": measured,
                    "expect_check": expect_check,
                    "hints": hints,
                },
            ))

        # ---- Stage 1: lint (offline — fail in milliseconds) ----
        lint = lint_definition(components, wires, catalog=catalog)
        hints.extend(lint["errors"])
        hints.extend(lint["warnings"])
        if not lint["valid"]:
            hints.append(
                "Fix the lint errors above, then call build_gh_interactive "
                f"again with iteration={iteration + 1} — no Rhino round-trip "
                "was spent on this attempt."
            )
            return _verdict("lint", False, lint)

        # ---- Stage 2: build + bake (catalog-derived output, auto-retry) ----
        rhino = get_rhino_connection()
        derived = derive_bake_outputs(components, wires, catalog=catalog)
        if bake_output is not None:
            candidates = [bake_output] + [c for c in derived
                                          if c.lower() != bake_output.lower()]
        else:
            candidates = derived or ["a"]
        candidates = candidates[:_MAX_BAKE_ATTEMPTS]

        attempts: List[Dict[str, Any]] = []
        result: Dict[str, Any] = {}
        used = candidates[0]
        for candidate in candidates:
            used = candidate
            result = _build_attempt(rhino, file_path, components, wires,
                                    layer, candidate, material, description)
            diag = result.get("diagnostics") or {}
            attempts.append({
                "bake_output": candidate,
                "status": result.get("status"),
                "matched_outputs": diag.get("matched_outputs"),
                "items_in_output": diag.get("items_in_output"),
            })
            if result.get("status") != "no_geometry":
                break  # success or build_errors — retrying outputs won't help
            if diag.get("matched_outputs", 0) > 0 \
                    and diag.get("items_in_output", 0) == 0:
                # The output exists but the solve produced no data — a
                # different nickname cannot fix that; stop and critique.
                break

        build = {
            "status": result.get("status"),
            "baked_count": result.get("baked_count", 0),
            "baked_ids": result.get("baked_ids", []),
            "layer": result.get("layer", layer),
            "bake_output_used": used,
            "attempts": attempts,
            "diagnostics": result.get("diagnostics"),
        }
        if len(attempts) > 1 and build["status"] == "success":
            hints.append(
                f"bake_output '{attempts[0]['bake_output']}' matched no "
                f"output; auto-retried with catalog-derived '{used}' — pass "
                f"bake_output='{used}' next time to save a round-trip."
            )

        if build["status"] != "success":
            diag = result.get("diagnostics") or {}
            if build["status"] == "build_errors":
                hints.append(
                    "The .gh had build errors — check component GUIDs and "
                    f"wires: {result.get('errors', result.get('message', ''))}"
                )
            elif diag.get("matched_outputs", 0) == 0:
                hints.append(
                    f"No component output matched bake_output "
                    f"{[a['bake_output'] for a in attempts]} — look the "
                    "component up with find_gh_component and pass its real "
                    "output nickname."
                )
            elif diag.get("items_in_output", 0) == 0:
                hints.append(
                    "The solve produced no data on the bake output. Script "
                    "components do NOT run headless on Rhino 8 — use SDK-"
                    "native components (find_gh_component) — or an input "
                    "wire/default is missing so the component never computed."
                )
            else:
                hints.append(
                    f"Output had {diag.get('items_in_output')} item(s) of "
                    f"type {diag.get('first_item_type')} but none were "
                    "bakeable — pick a geometry output, not a number/text."
                )
            return _verdict("build", False, lint, build)

        # ---- Stage 3: inspect the written file (headless verdict) ----
        inspect: Optional[Dict[str, Any]] = None
        try:
            raw = rhino.send_command("inspect_grasshopper_definition",
                                     {"file_path": file_path})
            inspect = {
                "headless_solvable": raw.get("headless_solvable"),
                "script_component_count": raw.get("script_component_count"),
                "object_count": raw.get("object_count"),
            }
            if inspect["headless_solvable"] is False:
                hints.append(
                    f"The written .gh contains "
                    f"{inspect['script_component_count']} script "
                    "component(s) — it baked now but will NOT solve "
                    "headless elsewhere (Compute/CI); replace scripts with "
                    "SDK-native components."
                )
        except Exception as e:  # degrade: inspection must not kill the loop
            logger.warning(f"inspect after bake failed: {e}")
            hints.append(f"Could not inspect the written .gh: {e}")

        # ---- Stage 4+5: measure baked geometry, critique vs expectations ----
        measured: Optional[Dict[str, Any]] = None
        bbox = None
        if build["baked_ids"]:
            info = rhino.send_command("get_objects_info",
                                      {"ids": list(build["baked_ids"])})
            bbox = union_bbox(info)
            measured = {
                "bbox": bbox,
                "dims_mm": bbox_dims(bbox),
                "count": (info or {}).get("count", 0),
            }

        expect_check = None
        if expect:
            expect_check = check_expectations(
                bbox, build["baked_count"], expect)
            hints.extend(expect_check["hints"])

        passed = (
            build["status"] == "success"
            and (inspect or {}).get("headless_solvable") is not False
            and (expect_check is None or expect_check["ok"])
        )
        return _verdict("measure", passed, lint, build, inspect,
                        measured, expect_check)

    except Exception as e:
        logger.error(f"build_gh_interactive failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
