import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.tools.find_gh_component import _catalog
from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError
from rhinoclaw.utils.gh_bake_verification import (
    canonical_nonempty_guids,
    cleanup_reported_baked_objects,
    summarize_baked_geometry,
    verify_active_object_readback,
    verify_object_properties_readback,
)
from rhinoclaw.utils.gh_critic import (
    bbox_dims,
    check_expectations,
    derive_bake_outputs,
    mass_properties_requested,
    validate_expectations,
)
from rhinoclaw.utils.gh_catalog import (
    authoring_catalog_contract,
    catalog_verification_failure_data,
    require_catalog_verification,
)
from rhinoclaw.utils.gh_lint import lint_definition
from rhinoclaw.utils.gh_player import union_bbox
from rhinoclaw.utils.interaction_logger import interaction_logger
from rhinoclaw.utils.responses import error, from_exception, ok

# Bake attempts per call — the deterministic bake_output retry is cheap
# (one round-trip) but must never turn into a blind sweep.
_MAX_BAKE_ATTEMPTS = 3


def _authoring_evidence(result: Dict[str, Any]) -> Dict[str, Any]:
    """Expose the plugin's one-document author/solve diagnostics unchanged."""
    build_result = result.get("build_result")
    authoring = build_result if isinstance(build_result, dict) else {}
    return {
        "build_result": build_result,
        "solution": authoring.get("solution"),
        "runtime_messages": authoring.get("runtime_messages"),
        "publication": authoring.get("publication"),
        "session_cleanup": authoring.get("session_cleanup"),
        "catalog_verification": result.get("catalog_verification"),
    }


def _clean_runtime_messages_verified(build: Dict[str, Any]) -> bool:
    """Prove that the one authoring solve reported a complete empty inventory."""
    solution = build.get("solution")
    messages = build.get("runtime_messages")
    if not isinstance(solution, dict) or not isinstance(messages, list):
        return False
    count = solution.get("runtime_message_count")
    counts = solution.get("runtime_message_counts")
    if (
        solution.get("runtime_messages_collected") is not True
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count != len(messages)
        or not isinstance(counts, dict)
    ):
        return False
    normalized_counts = []
    for level in ("remark", "warning", "error"):
        value = counts.get(level)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return False
        normalized_counts.append(value)
    return count == 0 and sum(normalized_counts) == count


def _build_attempt(rhino, file_path, components, wires, layer, bake_output,
                   material, description, catalog) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "file_path": file_path,
        "components": components,
        "wires": wires or [],
        "layer": layer,
        "bake_output": bake_output,
        "catalog_contract": authoring_catalog_contract(catalog, components),
    }
    if material is not None:
        params["material"] = material
    if description is not None:
        params["description"] = description
    result = rhino.send_command("build_and_bake_gh", params)
    require_catalog_verification(result)
    return result


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
    cleanup_on_failure: bool = True,
) -> str:
    """ONE authoring/critic iteration — lint, build+bake, inspect, measure,
    critique, cleanup and log (NEXT-LEVEL 5.3).

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
    4. **Measure**: exact active-GUID `get_objects_info` readback, plus
       independent `get_object_properties` when mass properties are requested.
       Claims never enter the verdict (the door-judge Goodhart rule).
    5. **Critique**: keeps solved, baked and verified separate; compares the
       measured geometry against `expect` and turns every failure into a hint.
    6. **Cleanup**: a failed iteration deletes only its verified bake GUIDs
       by default, then proves their absence. Incomplete ownership evidence is
       `PARTIAL_MUTATION`, never a claimed rollback.
    7. **Log**: one `graph_outcome` JSONL record — the corpus the recipe
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
      `{"min_count": 1, "dims_mm": [40,20,10], "all_valid": true,
        "all_solid": true, "total_volume": 8000,
        "topology": {"face_count": 6}, "layer": "GH_Bake"}`.
      Supported semantic checks include measured geometry/object types,
      validity, closed/solid, complete volume/area totals and aggregate
      face/edge/vertex topology. Unknown keys fail before the Rhino call.
    - label: Stable name for this graph across iterations (recall key for
      the outcome corpus, e.g. "param_box").
    - iteration: 1-based loop counter — pass `iteration+1` on each refine.
    - log_outcomes: Write the `graph_outcome` record (default True).
    - cleanup_on_failure: Delete this iteration's reported bake GUIDs after a
      failed verdict and independently prove absence (default True). False is
      an explicit diagnostic opt-out and reports retained mutation.

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
            "expect_check": {...} | null, "states": {
              "solved": {...}, "baked": {...}, "verified": {...}},
            "cleanup": {...} | null,
            "hints": ["actionable critique ...", ...]}}

    `pass` requires: lint clean, bake `status == "success"`, the written
    file's static `headless_solvable` assessment, and every supplied `expect`
    check within tolerance. Only `states.verified.pass`, not a contract-free
    top-level pass, denotes verification against explicit intent.
    """
    rhino = None
    cleanup_candidate_ids: List[str] = []
    cleanup_scope_complete = False
    mutation_attempted = False

    try:
        if not file_path or not file_path.lower().endswith(".gh"):
            raise ValueError("file_path is required and must end in .gh")
        if not isinstance(components, list) or not components:
            raise ValueError("components must be a non-empty list")
        if not isinstance(cleanup_on_failure, bool):
            raise ValueError("cleanup_on_failure must be a boolean")
        iteration = max(1, int(iteration))

        catalog = _catalog()
        hints: List[str] = []

        def _states(build=None, inspect=None, measured=None,
                    expect_check=None) -> Dict[str, Any]:
            build = build or {}
            diagnostics = build.get("diagnostics") or {}
            matched = diagnostics.get("matched_outputs")
            items = diagnostics.get("items_in_output")
            solved_pass = (
                build.get("status") == "success"
                and isinstance(matched, int) and not isinstance(matched, bool)
                and matched > 0
                and isinstance(items, int) and not isinstance(items, bool)
                and items > 0
            )
            baked_pass = (
                build.get("status") == "success"
                and (build.get("verification") or {}).get("pass") is True
            )
            readback_pass = (measured or {}).get("verification", {}).get(
                "pass") is True
            contract_supplied = (expect_check or {}).get(
                "contract_supplied") is True
            verified_pass = (
                readback_pass
                and contract_supplied
                and (expect_check or {}).get("ok") is True
            )
            if measured is None:
                verified_status = "not_reached"
            elif verified_pass:
                verified_status = "verified"
            elif not readback_pass:
                verified_status = "readback_failed"
            elif not contract_supplied:
                verified_status = "no_contract"
            else:
                verified_status = "contract_failed"
            return {
                "solved": {
                    "pass": solved_pass,
                    "evidence": "matched output contained solved data"
                    if solved_pass else "no authoritative solved-output evidence",
                    "clean_runtime_messages_verified":
                        _clean_runtime_messages_verified(build),
                },
                "baked": {
                    "pass": baked_pass,
                    "reported_count": build.get("baked_count"),
                    "mutation_report_verified": baked_pass,
                },
                "verified": {
                    "pass": verified_pass,
                    "status": verified_status,
                    "active_readback_pass": readback_pass,
                    "contract_supplied": contract_supplied,
                    "check_count": (expect_check or {}).get("checked", 0),
                    "semantic_check_count": (expect_check or {}).get(
                        "semantic_checked", 0),
                    "scope": [
                        check.get("check")
                        for check in (expect_check or {}).get("checks", [])
                    ],
                },
                "headless_assessment": {
                    "pass": (inspect or {}).get("headless_solvable") is True,
                    "basis": (inspect or {}).get(
                        "headless_solvable_basis",
                        "static_script_component_scan",
                    ),
                    "empirical_probe": (inspect or {}).get(
                        "empirical_probe", False),
                },
            }

        def _cleanup_failed_iteration(stage: str) -> Optional[Dict[str, Any]]:
            if stage == "lint" or not mutation_attempted:
                return None
            if not cleanup_on_failure:
                retained = list(cleanup_candidate_ids)
                return {
                    "requested": False,
                    "attempted": False,
                    "scope": "reported_baked_objects_only",
                    "scope_complete": False,
                    "target_ids": retained,
                    "deleted_ids": [],
                    "absence_verified": not retained,
                    "pass": not retained and cleanup_scope_complete,
                    "retained_ids": retained,
                    "reason": "cleanup_on_failure=false",
                    "unmeasured_or_retained": [
                        "reported baked objects",
                        "bake layer and material table changes",
                        "written Grasshopper definition file",
                    ],
                }
            if cleanup_candidate_ids:
                return cleanup_reported_baked_objects(
                    rhino,
                    cleanup_candidate_ids,
                    scope_complete=cleanup_scope_complete,
                )
            return {
                "requested": True,
                "attempted": False,
                "scope": "reported_baked_objects_only",
                "scope_complete": cleanup_scope_complete,
                "target_ids": [],
                "deleted_ids": [],
                "absence_verified": cleanup_scope_complete,
                "pass": cleanup_scope_complete,
                "reason": "no reported baked object GUIDs",
                "unmeasured_or_retained": [
                    "bake layer and material table changes",
                    "written Grasshopper definition file",
                ],
            }

        def _verdict(stage: str, passed: bool, lint, build=None, inspect=None,
                     measured=None, expect_check=None) -> str:
            cleanup = None if passed else _cleanup_failed_iteration(stage)
            states = _states(build, inspect, measured, expect_check)
            failure_code = None
            if not passed:
                failure_code = ErrorCode.VERIFICATION_FAILED
                if cleanup is not None and cleanup.get("pass") is not True:
                    failure_code = ErrorCode.PARTIAL_MUTATION
                    hints.append(
                        "Failed-iteration cleanup is incomplete or its ownership "
                        "scope is unproven; do not retry until the retained Rhino "
                        "state has been inspected."
                    )
                elif cleanup is not None and cleanup.get("attempted"):
                    hints.append(
                        "The failed iteration's reported baked objects were "
                        "deleted and their absence was independently verified."
                    )
            if log_outcomes:
                interaction_logger.log_graph_outcome({
                    "label": label,
                    "iteration": iteration,
                    "pass": passed,
                    "stage_reached": stage,
                    "lint_errors": len(lint["errors"]),
                    "build_status": (build or {}).get("status"),
                    "baked_count": (measured or {}).get(
                        "count", (build or {}).get("baked_count", 0)),
                    "bake_output_used": (build or {}).get("bake_output_used"),
                    "headless_solvable": (inspect or {}).get("headless_solvable"),
                    "expect_ok": (expect_check or {}).get("ok"),
                    "solved": states["solved"]["pass"],
                    "baked": states["baked"]["pass"],
                    "verified": states["verified"]["pass"],
                    "semantic_check_count": states["verified"][
                        "semantic_check_count"],
                    "cleanup_pass": (cleanup or {}).get("pass"),
                    "dims_mm": (measured or {}).get("dims_mm"),
                    "definition": file_path,
                })
            head = (f"Iteration {iteration}: "
                    + ("PASS" if passed else f"FAIL at stage '{stage}'"))
            if passed and states["verified"]["pass"]:
                tail = (
                    f" — verified {(measured or {}).get('count', 0)} object(s) "
                    f"against {states['verified']['check_count']} expectation(s)"
                )
            elif passed:
                tail = (
                    f" — conformance pass for {(measured or {}).get('count', 0)} "
                    "active object(s); verified=false because no explicit "
                    "expect contract was supplied"
                )
            else:
                tail = f" — {hints[0]}" if hints else ""
            data = {
                "pass": passed,
                "stage_reached": stage,
                "iteration": iteration,
                "label": label,
                "lint": lint,
                "build": build,
                "inspect": inspect,
                "measured": measured,
                "expect_check": expect_check,
                "states": states,
                "cleanup": cleanup,
                "failure_code": failure_code,
                "hints": hints,
            }
            if failure_code == ErrorCode.PARTIAL_MUTATION:
                return json.dumps(error(
                    head + tail,
                    code=ErrorCode.PARTIAL_MUTATION,
                    data=data,
                ))
            return json.dumps(ok(message=head + tail, data=data))

        # ---- Stage 1: lint (offline — fail in milliseconds) ----
        lint = lint_definition(components, wires, catalog=catalog)
        expectation_errors = validate_expectations(expect)
        if expectation_errors:
            lint["errors"].extend(expectation_errors)
            lint["valid"] = False
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
            # A timeout can happen after Rhino mutated. Mark the attempt before
            # crossing the transport boundary so the outer exception path does
            # not accidentally report a clean failure.
            mutation_attempted = True
            result = _build_attempt(rhino, file_path, components, wires,
                                    layer, candidate, material, description,
                                    catalog)
            if not isinstance(result, dict):
                raise TypeError("build_and_bake_gh response must be an object")
            # Salvage every valid reported ownership ID immediately. Any later
            # schema/diagnostic exception can still clean that known subset.
            cleanup_candidate_ids, _ = canonical_nonempty_guids(
                result.get("baked_ids", []),
                field_name="baked_ids",
            )
            diag = result.get("diagnostics") or {}
            if not isinstance(diag, dict):
                raise TypeError("build diagnostics must be an object")
            attempts.append({
                "bake_output": candidate,
                "status": result.get("status"),
                "matched_outputs": diag.get("matched_outputs"),
                "items_in_output": diag.get("items_in_output"),
                **_authoring_evidence(result),
            })
            if result.get("status") != "no_geometry":
                break  # success or build_errors — retrying outputs won't help
            # A no-geometry response carrying any possible mutation evidence is
            # inconsistent. Never hide that behind a second bake attempt.
            if result.get("baked_ids") or result.get("baked_count") not in (0, None):
                break
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
            **_authoring_evidence(result),
        }
        if len(attempts) > 1 and build["status"] == "success":
            hints.append(
                f"bake_output '{attempts[0]['bake_output']}' matched no "
                f"output; auto-retried with catalog-derived '{used}' — pass "
                f"bake_output='{used}' next time to save a round-trip."
            )

        raw_baked_ids = build["baked_ids"]
        report_ids, report_issues = canonical_nonempty_guids(
            raw_baked_ids, field_name="baked_ids")
        reported_count = build["baked_count"]
        if (
            not isinstance(reported_count, int)
            or isinstance(reported_count, bool)
            or reported_count < 0
        ):
            report_issues.append(
                "baked_count must be a non-negative integer")
        elif isinstance(raw_baked_ids, list) \
                and reported_count != len(raw_baked_ids):
            report_issues.append(
                "baked_count does not equal len(baked_ids)")

        cleanup_candidate_ids = report_ids
        if build["status"] != "success":
            zero_mutation_report = (
                reported_count == 0
                and (
                    build["status"] == "build_errors"
                    or (isinstance(raw_baked_ids, list) and not raw_baked_ids)
                )
            )
            cleanup_scope_complete = (
                build["status"] in {"build_errors", "no_geometry"}
                and zero_mutation_report
                and not report_issues
            )
            build["verification"] = {
                "pass": cleanup_scope_complete,
                "issues": report_issues,
                "canonical_baked_ids": report_ids,
                "zero_geometry_report": zero_mutation_report,
            }
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
            if report_issues or not cleanup_scope_complete:
                hints.append(
                    "The failed build's mutation report does not prove an empty "
                    "ownership set; any retry requires document inspection."
                )
            return _verdict("build", False, lint, build)

        if reported_count == 0:
            report_issues.append(
                "successful build-and-bake reported no Rhino objects")
        cleanup_scope_complete = not report_issues
        build["verification"] = {
            "pass": not report_issues,
            "issues": report_issues,
            "canonical_baked_ids": report_ids,
        }
        if report_issues:
            hints.append(
                "The build-and-bake mutation report is inconsistent: "
                + "; ".join(report_issues)
                + ". Reported GUIDs will be cleaned best-effort, but the "
                "ownership scope cannot be claimed complete."
            )
            return _verdict("build", False, lint, build)
        build["baked_ids"] = report_ids

        # ---- Stage 3: inspect the written file (headless verdict) ----
        inspect: Optional[Dict[str, Any]] = None
        try:
            raw = rhino.send_command("inspect_grasshopper_definition",
                                     {"file_path": file_path})
            inspect = {
                "headless_solvable": raw.get("headless_solvable"),
                "script_component_count": raw.get("script_component_count"),
                "object_count": raw.get("object_count"),
                "headless_solvable_basis": "static_script_component_scan",
                "empirical_probe": False,
            }
            if inspect["headless_solvable"] is False:
                hints.append(
                    f"The written .gh contains "
                    f"{inspect['script_component_count']} script "
                    "component(s) — it baked now but will NOT solve "
                    "headless elsewhere (Compute/CI); replace scripts with "
                    "SDK-native components."
                )
        except Exception as e:
            logger.warning(f"inspect after bake failed: {e}")
            hints.append(
                "Could not verify that the written .gh is headless-solvable: "
                f"{e}. Treat this iteration as failed; inspect the file "
                "successfully before accepting or deploying it."
            )

        # ---- Stage 4+5: measure baked geometry, critique vs expectations ----
        measured: Optional[Dict[str, Any]] = None
        bbox = None
        info = None
        properties_raw = None
        properties: List[Dict[str, Any]] = []
        readback_ids: List[str] = []
        active_readback_issues: List[str] = []
        property_readback_issues: List[str] = []
        try:
            info = rhino.send_command(
                "get_objects_info", {"ids": list(build["baked_ids"])})
            readback_ids, active_readback_issues = verify_active_object_readback(
                info, build["baked_ids"])
            if not active_readback_issues:
                bbox = union_bbox(info)
                if bbox is None:
                    active_readback_issues.append(
                        "active baked objects have no measurable bounding box")
        except Exception as readback_error:
            active_readback_issues.append(
                "active object readback failed: " + str(readback_error))

        if not active_readback_issues and mass_properties_requested(expect):
            try:
                properties_raw = rhino.send_command(
                    "get_object_properties",
                    {"object_ids": list(build["baked_ids"])},
                )
                properties, property_readback_issues = \
                    verify_object_properties_readback(
                        properties_raw, build["baked_ids"])
            except Exception as property_error:
                property_readback_issues.append(
                    "mass-property readback failed: " + str(property_error)
                )

        semantics = summarize_baked_geometry(info, properties)
        readback_issues = active_readback_issues + property_readback_issues
        measured = {
            "bbox": bbox,
            "dims_mm": bbox_dims(bbox),
            "count": len(readback_ids) if not active_readback_issues else 0,
            "active_ids": readback_ids,
            "readback": info,
            "property_readback": properties_raw,
            "semantics": semantics,
            "verification": {
                "pass": not readback_issues,
                "issues": readback_issues,
                "active_readback_pass": not active_readback_issues,
                "mass_property_readback_required": mass_properties_requested(
                    expect),
                "mass_property_readback_pass": not property_readback_issues
                if mass_properties_requested(expect) else None,
            },
        }
        if readback_issues:
            hints.append(
                "The bake claim could not be verified against active Rhino "
                "objects: " + "; ".join(readback_issues)
                + ". The iteration fails closed and its reported bake GUIDs "
                "enter cleanup."
            )

        expect_check = None
        if expect:
            expect_check = check_expectations(
                bbox, measured["count"], expect, semantics)
            hints.extend(expect_check["hints"])

        passed = (
            build["status"] == "success"
            and (inspect or {}).get("headless_solvable") is True
            and measured["verification"]["pass"] is True
            and (expect_check is None or expect_check["ok"])
        )
        return _verdict("measure", passed, lint, build, inspect,
                        measured, expect_check)

    except Exception as e:
        logger.error(f"build_gh_interactive failed: {e}")
        if (
            isinstance(e, RhinoCommandError)
            and e.error_code == ErrorCode.VERIFICATION_FAILED
        ):
            failure_data = catalog_verification_failure_data(
                e, mutation_attempted=mutation_attempted)
            failure_data.update({
                "pass": False,
                "stage_reached": "build",
                "failure_code": ErrorCode.VERIFICATION_FAILED,
            })
            return json.dumps(error(
                "Grasshopper authoring stopped because the runtime catalog "
                "could not be verified",
                code=ErrorCode.VERIFICATION_FAILED,
                data=failure_data,
            ))
        if mutation_attempted:
            if cleanup_on_failure and rhino is not None \
                    and cleanup_candidate_ids:
                cleanup = cleanup_reported_baked_objects(
                    rhino,
                    cleanup_candidate_ids,
                    scope_complete=cleanup_scope_complete,
                )
            else:
                cleanup = {
                    "requested": cleanup_on_failure,
                    "attempted": False,
                    "scope_complete": False,
                    "target_ids": list(cleanup_candidate_ids),
                    "deleted_ids": [],
                    "absence_verified": False,
                    "pass": False,
                    "reason": "exception left no complete cleanup ownership set",
                }
            code = ErrorCode.RHINO_ERROR \
                if cleanup.get("pass") is True else ErrorCode.PARTIAL_MUTATION
            return json.dumps(error(
                "Grasshopper iteration raised after a mutation attempt",
                code=code,
                data={
                    "exception": str(e),
                    "cleanup": cleanup,
                    "failure_code": code,
                },
            ))
        code = ErrorCode.INVALID_PARAMS if isinstance(e, ValueError) \
            else ErrorCode.RHINO_ERROR
        return json.dumps(from_exception(e, code=code))
