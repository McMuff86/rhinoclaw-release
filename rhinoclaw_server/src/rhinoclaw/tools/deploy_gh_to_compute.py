import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok

# A script output socket binds to a script variable by its Name/NickName.
# `RH_OUT:Frame` contains `:`→ not a valid Python identifier → the output
# silently stays empty. See docs/learnings/grasshopper-automation.md
# ("Keep Script Output Variables Separate from RH_OUT Groups").
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WSL_MOUNT_RE = re.compile(r"^/mnt/([a-zA-Z])/(.*)$")


def _json_response(payload: Dict[str, Any]) -> str:
    return json.dumps(payload)


def _to_rhino_path(path: Path) -> str:
    """Translate a WSL `/mnt/<drive>/…` path to `<Drive>:/…` for the plugin."""
    # On Windows, str(Path(...)) yields backslashes — normalise to forward
    # slashes so the mount pattern matches and the result is identical on
    # every host (the plugin accepts both separators).
    text = str(path).replace("\\", "/")
    match = _WSL_MOUNT_RE.match(text)
    if match:
        return f"{match.group(1).upper()}:/{match.group(2)}"
    return text


def _validate_inspection(
    inspection: Dict[str, Any],
    metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check an inspect_grasshopper_definition result against the Compute contract.

    Pure function (unit-testable without Rhino). Encodes the RH_OUT learning:
    - ERROR: a script component output is named `RH_OUT:*` (or any non-
      identifier) — the script variable can never bind, solves return an
      empty tree with no warning.
    - WARNING: no `RH_OUT` group found — the Compute Platform detects
      outputs via group nicknames, so this definition would publish nothing.
    - WARNING: a `.meta.json` output name has no matching `RH_OUT` group.
    """
    errors = []
    warnings = []

    for comp in inspection.get("script_components") or []:
        comp_label = comp.get("nickname") or comp.get("name") or "script"
        for output in comp.get("outputs") or []:
            variable = output.get("nickname") or output.get("name") or ""
            if "RH_OUT" in variable:
                errors.append(
                    f"Script component '{comp_label}' has output '{variable}': "
                    "script outputs bind to script variables by name, and "
                    f"'{variable}' is not a valid identifier — the output will "
                    "stay empty. Rename the script output to a plain variable "
                    "(e.g. 'a' or 'Frame') and put the public name on a group: "
                    "script output → Geometry param → group nicknamed "
                    "'RH_OUT:<Name>'."
                )
            elif variable and not _IDENTIFIER_RE.match(variable):
                warnings.append(
                    f"Script component '{comp_label}' output '{variable}' is not "
                    "a valid script variable name — the assignment may not bind."
                )

    group_nicknames = None
    if "groups" in inspection:
        group_nicknames = [
            (group.get("nickname") or "")
            for group in inspection.get("groups") or []
        ]
        rh_out_groups = [n for n in group_nicknames if "RH_OUT" in n]
        if not rh_out_groups:
            warnings.append(
                "No group with an 'RH_OUT' nickname found — the Compute "
                "Platform detects outputs via RH_OUT:<Name> group nicknames, "
                "so this definition would publish no outputs."
            )
    else:
        warnings.append(
            "Plugin did not report groups (pre-0.5.1 plugin?) — RH_OUT group "
            "check skipped."
        )

    if metadata and group_nicknames is not None:
        for meta_output in metadata.get("outputs") or []:
            name = meta_output.get("name") if isinstance(meta_output, dict) else None
            if name and name.startswith("RH_OUT") and name not in group_nicknames:
                warnings.append(
                    f".meta.json declares output '{name}' but no group with "
                    "that nickname exists in the definition."
                )

    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": warnings,
        "script_component_count": inspection.get("script_component_count"),
        "headless_solvable": inspection.get("headless_solvable"),
    }


def _run_validation(
    source: Path,
    metadata: Optional[Dict[str, Any]],
    copy_existing_metadata: bool,
) -> Dict[str, Any]:
    """Inspect the source definition via the plugin; degrade to 'skipped'."""
    effective_metadata = metadata
    if effective_metadata is None and copy_existing_metadata:
        source_meta = source.with_suffix(".meta.json")
        if source_meta.exists():
            try:
                with open(source_meta, encoding="utf-8") as mf:
                    effective_metadata = json.load(mf)
            except (OSError, json.JSONDecodeError):
                effective_metadata = None

    try:
        rhino = get_rhino_connection()
        inspection = rhino.send_command(
            "inspect_grasshopper_definition",
            {"file_path": _to_rhino_path(source)},
        )
    except Exception as exc:  # connection down, path invisible to Rhino, …
        return {
            "status": "skipped",
            "reason": f"inspect_grasshopper_definition unavailable: {exc}",
            "errors": [],
            "warnings": [],
        }

    return _validate_inspection(inspection, effective_metadata)


def _resolve_definitions_dir(compute_project_dir: Optional[str]) -> Path:
    if compute_project_dir:
        root = Path(compute_project_dir).expanduser().resolve()
        return root if root.name == "definitions" else root / "definitions"

    env_root = os.getenv("RHINO_COMPUTE_PLATFORM_DIR")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        return root if root.name == "definitions" else root / "definitions"

    candidates = [
        Path.home() / "projects" / "rhino-compute-platform" / "definitions",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()

    raise ValueError(
        "Compute definitions directory not found. Pass compute_project_dir or set RHINO_COMPUTE_PLATFORM_DIR."
    )


def _safe_target_path(definitions_dir: Path, target_name: str) -> Path:
    if not target_name or Path(target_name).name != target_name:
        raise ValueError("target_name must be a filename, not a path")
    if Path(target_name).suffix.lower() not in {".gh", ".ghx"}:
        raise ValueError("target_name must end with .gh or .ghx")

    target_path = (definitions_dir / target_name).resolve()
    try:
        target_path.relative_to(definitions_dir.resolve())
    except ValueError as exc:
        raise ValueError("target path must stay inside the definitions directory") from exc
    return target_path


def _write_metadata(
    source_path: Path,
    target_path: Path,
    metadata: Optional[Dict[str, Any]],
    copy_existing_metadata: bool,
    overwrite: bool,
) -> tuple[Optional[Path], str]:
    meta_path = target_path.with_suffix(".meta.json")

    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        if meta_path.exists() and not overwrite:
            raise FileExistsError(f"Metadata already exists: {meta_path}")
        with open(meta_path, "w", encoding="utf-8") as mf:
            json.dump(metadata, mf, indent=2)
            mf.write("\n")
        return meta_path, "inline"

    if copy_existing_metadata:
        source_meta = source_path.with_suffix(".meta.json")
        if source_meta.exists():
            if meta_path.exists() and not overwrite:
                raise FileExistsError(f"Metadata already exists: {meta_path}")
            shutil.copy2(source_meta, meta_path)
            return meta_path, "sidecar"

    return None, "none"


def _preflight_metadata_target(
    source_path: Path,
    target_path: Path,
    metadata: Optional[Dict[str, Any]],
    copy_existing_metadata: bool,
    overwrite: bool,
) -> None:
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        json.dumps(metadata)
        if target_path.with_suffix(".meta.json").exists() and not overwrite:
            raise FileExistsError(f"Metadata already exists: {target_path.with_suffix('.meta.json')}")
        return

    if copy_existing_metadata and source_path.with_suffix(".meta.json").exists():
        if target_path.with_suffix(".meta.json").exists() and not overwrite:
            raise FileExistsError(f"Metadata already exists: {target_path.with_suffix('.meta.json')}")


@mcp.tool()
def deploy_gh_to_compute(
    ctx: Context,
    source_path: str,
    compute_project_dir: Optional[str] = None,
    target_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    copy_existing_metadata: bool = True,
    overwrite: bool = True,
    validate: bool = True,
    force: bool = False,
) -> str:
    """Deploy a Grasshopper definition to the Rhino Compute Platform.

    Copies a `.gh` or `.ghx` file into the Compute Platform's managed
    `definitions/` directory so `/definitions`, `/definitions/{name}/manifest`,
    `/solve`, and the browser viewer can use it. If `metadata` is provided, it
    is written as `{definition}.meta.json`; otherwise an adjacent source
    sidecar is copied when present.

    Before copying, the definition is validated against the Compute output
    contract via `inspect_grasshopper_definition` (requires a live Rhino
    connection; degrades to `validation.status = "skipped"` without one):
    - ERROR (blocks deploy unless `force`): a script component output is
      named `RH_OUT:*` — the script variable can never bind, so solves
      return an empty tree. Keep the script output a plain variable and put
      `RH_OUT:<Name>` on the output *group*.
    - WARNING: no `RH_OUT` group nickname found / `.meta.json` outputs that
      match no group.

    Parameters:
    - source_path: Existing `.gh` or `.ghx` file to deploy.
    - compute_project_dir: Compute Platform project root or its definitions dir.
      Optional when `RHINO_COMPUTE_PLATFORM_DIR` is set or
      `~/projects/rhino-compute-platform/definitions` exists.
    - target_name: Optional filename in `definitions/`. Defaults to source name.
    - metadata: Optional manifest sidecar object matching the Compute Platform
      `.meta.json` contract.
    - copy_existing_metadata: Copy adjacent `{source}.meta.json` if present.
    - overwrite: Replace existing target files.
    - validate: Inspect the definition against the RH_OUT contract first.
    - force: Deploy even when validation reports errors.

    Returns:
        {"success": true, "data": {
            "definition": "door.gh",
            "file_path": ".../definitions/door.gh",
            "meta_path": ".../definitions/door.meta.json" | null,
            "metadata_source": "inline" | "sidecar" | "none",
            "validation": {"status": "passed" | "failed" | "skipped",
                           "errors": [...], "warnings": [...]}}}
    """
    if not source_path:
        return _json_response(from_exception(
            ValueError("source_path is required"),
            code=ErrorCode.INVALID_PARAMS,
        ))

    try:
        source = Path(source_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Source definition not found: {source}")
        if source.suffix.lower() not in {".gh", ".ghx"}:
            raise ValueError("source_path must point to a .gh or .ghx file")

        definitions_dir = _resolve_definitions_dir(compute_project_dir)
        if not definitions_dir.exists() or not definitions_dir.is_dir():
            raise FileNotFoundError(f"Definitions directory not found: {definitions_dir}")

        definition_name = target_name or source.name
        target = _safe_target_path(definitions_dir, definition_name)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Definition already exists: {target}")
        _preflight_metadata_target(
            source,
            target,
            metadata,
            copy_existing_metadata,
            overwrite,
        )

        validation: Dict[str, Any] = {"status": "skipped", "reason": "validate=False",
                                      "errors": [], "warnings": []}
        if validate:
            validation = _run_validation(source, metadata, copy_existing_metadata)
            if validation["status"] == "failed" and not force:
                return _json_response(error(
                    "Validation failed — definition violates the Compute "
                    "output contract (pass force=True to deploy anyway): "
                    + " | ".join(validation["errors"]),
                    code=ErrorCode.INVALID_PARAMS,
                    data={"validation": validation},
                ))

        shutil.copy2(source, target)
        meta_path, metadata_source = _write_metadata(
            source,
            target,
            metadata,
            copy_existing_metadata,
            overwrite,
        )

        return _json_response(ok(
            message=f"Deployed GH definition to Compute Platform: {target.name}",
            data={
                "definition": target.name,
                "file_path": str(target),
                "definitions_dir": str(definitions_dir),
                "meta_path": str(meta_path) if meta_path else None,
                "metadata_source": metadata_source,
                "overwrite": overwrite,
                "validation": validation,
            },
        ))
    except Exception as e:
        logger.error(f"Error deploying GH definition to Compute Platform: {str(e)}")
        return _json_response(from_exception(e, code=ErrorCode.INVALID_PARAMS))
