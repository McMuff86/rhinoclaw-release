"""Dedicated, readback-verified agent path for the proven Rahmentuer builder."""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError
from rhinoclaw.utils.kits import KitError, build_invoke_source, parse_invoke_output
from rhinoclaw.utils.part_library import wsl_to_windows_path
from rhinoclaw.utils.rahmentuer import (
    ENTRY_FILE,
    RahmentuerAssetError,
    resolve_asset_root,
    verify_rahmentuer_readback,
)
from rhinoclaw.utils.responses import error, from_exception, ok


def _finite_positive(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def _finite_point(point: Any) -> list[float]:
    if not isinstance(point, (list, tuple)) or len(point) != 3:
        raise ValueError("point must contain exactly [x, y, z]")
    try:
        result = [float(value) for value in point]
    except (TypeError, ValueError) as exc:
        raise ValueError("point must contain finite numbers") from exc
    if not all(math.isfinite(value) for value in result):
        raise ValueError("point must contain finite numbers")
    return result


def _require_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


@mcp.tool()
def insert_rahmentuer(
    ctx: Context,
    block_name: str,
    point: List[float],
    lichtbreite: float = 960.0,
    lichthoehe: float = 2100.0,
    bandseite: Literal["links", "rechts"] = "links",
    rahmendicke: float = 53.0,
    tuerstaerke: float = 58.0,
    sfs_enabled: bool = True,
    glutz_enabled: bool = True,
    intumex_enabled: bool = True,
    dichtnut_enabled: bool = True,
    overrides: Optional[Dict[str, Any]] = None,
    asset_root: Optional[str] = None,
    timeout: float = 180.0,
) -> str:
    """Insert one complete parametric frame door as a verified named block.

    This is the prompt-free MCP wrapper around the live-proven
    ``build_rahmentuer_block`` workflow. It creates the frame, rebated leaf,
    optional grooves/Intumex, SFS hinges, lock and handle hardware plus ERP
    user text as one top-level block instance. The returned verdict comes from
    separate ``get_objects_info`` and ``list_block_definitions`` reads; it does
    not trust the builder's own bbox or part-count claims.

    Parameters:
    - block_name: Unique ERP/instance name, e.g. ``OH7A.1OG.02``. A definition
      already in use is refused, never silently duplicated.
    - point: World insertion point ``[x, y, z]``; no interactive GetPoint.
    - lichtbreite / lichthoehe: Clear opening dimensions in millimetres.
    - bandseite: ``links`` is live/visually verified; ``rechts`` is a mirrored
      engagement rule and still requires project-specific visual approval.
    - rahmendicke / tuerstaerke: Main depth dimensions in millimetres.
    - sfs_enabled / glutz_enabled: Include the registered real hardware.
    - intumex_enabled / dichtnut_enabled: Include verified frame details.
    - overrides: Advanced ``rahmentuer.py`` config values. Explicit parameters
      above win over keys with the same names.
    - asset_root: Folder containing ``rahmentuer.py``, ``block_hardware.py``
      and selected vendor 3DM files. Otherwise uses
      ``RHINOCLAW_RAHMENTUER_ROOT`` then safe default locations.
    - timeout: Python-3 execution timeout, 1..300 seconds.

    Success requires: exactly one resolvable instance, matching name and ERP
    prefixes, exactly one matching definition/reference, independent part
    count, requested outer width/height, and a world bbox equal to the local
    definition bbox translated by ``point``.
    """
    mutation_attempted = False
    builder: dict[str, Any] = {}
    try:
        if not isinstance(block_name, str):
            raise ValueError("block_name must be a non-empty string")
        name = block_name.strip()
        if not name:
            raise ValueError("block_name must be a non-empty string")
        if len(name) > 120:
            raise ValueError("block_name must be at most 120 characters")
        insert_point = _finite_point(point)
        width = _finite_positive("lichtbreite", lichtbreite)
        height = _finite_positive("lichthoehe", lichthoehe)
        frame_depth = _finite_positive("rahmendicke", rahmendicke)
        leaf_depth = _finite_positive("tuerstaerke", tuerstaerke)
        run_timeout = _finite_positive("timeout", timeout)
        if run_timeout > 300:
            raise ValueError("timeout must be at most 300 seconds")
        if bandseite not in ("links", "rechts"):
            raise ValueError("bandseite must be 'links' or 'rechts'")
        if overrides is not None and not isinstance(overrides, dict):
            raise ValueError("overrides must be an object")
        use_sfs = _require_bool("sfs_enabled", sfs_enabled)
        use_glutz = _require_bool("glutz_enabled", glutz_enabled)
        use_intumex = _require_bool("intumex_enabled", intumex_enabled)
        use_dichtnut = _require_bool("dichtnut_enabled", dichtnut_enabled)

        merged = dict(overrides or {})
        merged.update({
            "lichtbreite": width,
            "lichthoehe": height,
            "bandseite": bandseite,
            "rahmendicke": frame_depth,
            "tuerstaerke": leaf_depth,
            "sfs_enabled": use_sfs,
            "glutz_enabled": use_glutz,
            "intumex_enabled": use_intumex,
            "dichtnut_enabled": use_dichtnut,
        })
        try:
            json.dumps(merged, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "overrides must contain finite JSON-serializable values"
            ) from exc
        root = resolve_asset_root(merged, asset_root)
        entry = root / ENTRY_FILE
        source = build_invoke_source(
            entry,
            "build_rahmentuer_block",
            {
                "overrides": merged,
                "block_name": name,
                "insert_point": insert_point,
            },
        )

        rhino = get_rhino_connection()
        mutation_attempted = True
        engine = rhino.send_command(
            "execute_python3_code",
            {"code": source},
            timeout=run_timeout,
        )
        if not isinstance(engine, dict) or engine.get("success") is False:
            rollback_proven = (
                isinstance(engine, dict)
                and engine.get("rollback_performed") is True
            )
            return json.dumps(error(
                (engine or {}).get("message", "Rahmentuer Python 3 execution failed")
                if isinstance(engine, dict)
                else "Rahmentuer Python 3 execution returned no result",
                code=(
                    ErrorCode.SCRIPT_ERROR
                    if rollback_proven
                    else ErrorCode.PARTIAL_MUTATION
                ),
                data={"engine": engine, "mutation_attempted": True},
            ))

        try:
            payload = parse_invoke_output(str(engine.get("result") or ""))
        except KitError as exc:
            return json.dumps(error(
                str(exc),
                code=ErrorCode.PARTIAL_MUTATION,
                data={"engine": engine, "mutation_attempted": True},
            ))
        if "instance_id" not in payload:
            return json.dumps(error(
                "Rahmentuer builder created no instance; the block name may already be in use.",
                code=ErrorCode.RESOURCE_IN_USE,
                data={"builder": payload, "engine": engine,
                      "mutation_attempted": True},
            ))
        builder = payload
        instance_id = str(builder["instance_id"])

        object_readback = rhino.send_command(
            "get_objects_info", {"ids": [instance_id]})
        definition_readback = rhino.send_command(
            "list_block_definitions",
            {"name_filter": name, "include_bbox": True},
        )
        verification = verify_rahmentuer_readback(
            builder=builder,
            object_readback=object_readback,
            definition_readback=definition_readback,
            block_name=name,
            insert_point=insert_point,
            lichtbreite=width,
            lichthoehe=height,
            overrides=merged,
        )
        data = {
            "status": "success" if verification["pass"] else "verification_failed",
            "block_name": name,
            "instance_id": instance_id,
            "insert_point": insert_point,
            "asset_root": wsl_to_windows_path(str(root)),
            "parts": builder.get("parts"),
            "requested": {
                "lichtbreite": width,
                "lichthoehe": height,
                "bandseite": bandseite,
                "rahmendicke": frame_depth,
                "tuerstaerke": leaf_depth,
            },
            "verification": verification,
            "engine": {
                "success": engine.get("success"),
                "engine": engine.get("engine"),
                "duration_ms": engine.get("duration_ms"),
            },
            "warnings": (
                ["bandseite='rechts' uses an engagement mirror that still "
                 "requires project-specific visual approval"]
                if bandseite == "rechts" else []
            ),
        }
        if not verification["pass"]:
            return json.dumps(error(
                "Rahmentuer was created but independent readback verification failed.",
                code=ErrorCode.PARTIAL_MUTATION,
                data=data,
            ))
        return json.dumps(ok(
            message=(
                f"Inserted and verified Rahmentuer '{name}' "
                f"({width:g} x {height:g} mm, {builder.get('parts')} parts)"
            ),
            data=data,
        ))
    except (ValueError, RahmentuerAssetError) as exc:
        code = (
            ErrorCode.PRECONDITION_FAILED
            if isinstance(exc, RahmentuerAssetError)
            else ErrorCode.INVALID_PARAMS
        )
        return json.dumps(error(str(exc), code=code))
    except RhinoCommandError as exc:
        code = ErrorCode.PARTIAL_MUTATION if mutation_attempted else exc.error_code
        return json.dumps(error(
            str(exc),
            code=code,
            data={"builder": builder, "mutation_attempted": mutation_attempted,
                  "plugin_response": exc.response},
        ))
    except Exception as exc:
        logger.error("insert_rahmentuer failed: %s", exc)
        code = ErrorCode.PARTIAL_MUTATION if mutation_attempted else ErrorCode.RHINO_ERROR
        return json.dumps(from_exception(exc, code=code))
