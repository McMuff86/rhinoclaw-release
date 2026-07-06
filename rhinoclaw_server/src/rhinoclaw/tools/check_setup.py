import json
import platform
from pathlib import Path
from typing import Any, Dict, List

from mcp.server.fastmcp import Context

from rhinoclaw import __version__ as server_version
from rhinoclaw.config import get_settings
from rhinoclaw.server import get_rhino_connection, mcp
from rhinoclaw.tools.get_ui_state import get_ui_state
from rhinoclaw.utils.interaction_logger import interaction_logger
from rhinoclaw.utils.responses import ok


def _check(name: str, status: str, detail: str, fix: str = "") -> Dict[str, str]:
    entry = {"check": name, "status": status, "detail": detail}
    if fix:
        entry["fix"] = fix
    return entry


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


@mcp.tool()
def rhinoclaw_doctor(ctx: Context) -> str:
    """Diagnose the RhinoClaw setup — one call, PASS/FAIL with an exact fix each.

    Run this when anything seems broken (or right after installing). Checks,
    in dependency order:
    1. TCP connection to the Rhino plugin (`hello`, auth-free)
    2. Authentication (a real authed call)
    3. Plugin ↔ server version match
    4. Grasshopper availability (needed for place_doors / GH tools)
    5. WSL host configuration sanity
    6. Outcome-corpus directory writable (logs/ — recall depends on it)

    Returns:
        {"success": true, "data": {"ready": bool, "summary": "...",
            "checks": [{"check", "status": "PASS|WARN|FAIL|SKIP",
                        "detail", "fix?"}, ...]}}

    `ready: true` = every check PASS or WARN. Apply the `fix` strings in
    order — they are written to be executable as-is.
    """
    checks: List[Dict[str, str]] = []
    settings = get_settings()
    hello: Dict[str, Any] = {}

    # 1. Connection (hello bypasses auth and the brute-force counter).
    try:
        rhino = get_rhino_connection()
        hello = rhino.send_command("hello", {}) or {}
        checks.append(_check(
            "connection", "PASS",
            f"Plugin reachable at {settings.host}:{settings.port} "
            f"(mode={hello.get('mode', '?')})",
        ))
    except Exception as e:
        wsl_hint = (
            " From WSL: the Windows host is NOT 127.0.0.1 — run "
            "`ip route show default | awk '{print $3}'` and set "
            "RHINOCLAW_HOST to that IP."
            if _is_wsl() else ""
        )
        checks.append(_check(
            "connection", "FAIL", f"No plugin at {settings.host}:{settings.port}: {e}",
            "Start Rhino and run `tcpstart` (remote/WSL) or `mcpstart` "
            "(local)." + wsl_hint,
        ))
        return json.dumps(ok(
            message="Doctor: FAIL at connection — fix that first, the "
                    "remaining checks depend on it",
            data={"ready": False, "summary": "1 FAIL (connection)",
                  "checks": checks},
        ))

    # 2. Auth — hello is auth-free, so verify with a real authed call.
    auth_required = bool(hello.get("auth_required"))
    try:
        rhino.send_command("ping", {})
        checks.append(_check(
            "auth", "PASS",
            "Authed call succeeded"
            + (" (token verified)" if auth_required else " (no token required)"),
        ))
    except Exception as e:
        checks.append(_check(
            "auth", "FAIL", f"Authed call rejected: {e}",
            "Set RHINOCLAW_AUTH_TOKEN on the client to the SAME value the "
            "plugin was started with (the plugin reads it only at Rhino "
            "start). Check with `get_auth_status`.",
        ))

    # 2b. UI state — an invisible modal dialog blocks every mutating call.
    try:
        ui_data = json.loads(get_ui_state(ctx)).get("data", {})
        if ui_data.get("busy"):
            checks.append(_check(
                "ui_state", "WARN", ui_data.get("diagnosis", "Rhino is busy"),
                "Check the Rhino screen: close any dialog, finish/cancel the "
                "running command (cancel_rhino_command), then retry.",
            ))
        else:
            checks.append(_check(
                "ui_state", "PASS", "UI thread idle — no modal dialog, no "
                "running command"))
    except Exception as e:
        checks.append(_check("ui_state", "SKIP", f"probe failed: {e}"))

    # 3. Version match ("0.5.0.0" ↔ "0.5.0").
    plugin_version = str(hello.get("plugin_version", "?"))
    if plugin_version.startswith(server_version):
        checks.append(_check(
            "version", "PASS",
            f"Plugin {plugin_version} ↔ Server {server_version}"))
    else:
        checks.append(_check(
            "version", "WARN",
            f"Plugin {plugin_version} ≠ Server {server_version}",
            "Rebuild + redeploy the plugin (scripts/deploy.ps1) or update "
            "the server (`uv sync` / reinstall) so both sides match.",
        ))

    # 4. Grasshopper.
    if hello.get("gh_available"):
        checks.append(_check("grasshopper", "PASS", "Grasshopper is loaded"))
    else:
        checks.append(_check(
            "grasshopper", "WARN", "Grasshopper not loaded",
            "Run `Grasshopper` once in Rhino — place_doors and the GH tools "
            "need it.",
        ))

    # 5. WSL host sanity.
    if _is_wsl():
        if settings.host in ("127.0.0.1", "localhost"):
            checks.append(_check(
                "wsl_host", "WARN",
                "Running under WSL but RHINOCLAW_HOST is loopback — that "
                "only works with a port proxy.",
                "export RHINOCLAW_HOST=$(ip route show default | awk "
                "'{print $3}')",
            ))
        else:
            checks.append(_check(
                "wsl_host", "PASS", f"WSL → Windows host {settings.host}"))
    else:
        checks.append(_check("wsl_host", "SKIP", "Not running under WSL"))

    # 6. Outcome corpus (recall_placements depends on it).
    log_dir = interaction_logger._log_dir
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        probe = log_dir / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(_check(
            "outcome_corpus", "PASS", f"logs/ writable: {log_dir}"))
    except OSError as e:
        checks.append(_check(
            "outcome_corpus", "FAIL", f"Cannot write {log_dir}: {e}",
            "Fix permissions on the logs directory — without it, judged "
            "outcomes evaporate and recall_placements never learns.",
        ))

    fails = sum(1 for c in checks if c["status"] == "FAIL")
    warns = sum(1 for c in checks if c["status"] == "WARN")
    ready = fails == 0
    summary = (f"{len(checks)} checks: "
               f"{sum(1 for c in checks if c['status'] == 'PASS')} PASS, "
               f"{warns} WARN, {fails} FAIL "
               f"(platform: {platform.system()}"
               f"{', WSL' if _is_wsl() else ''})")

    return json.dumps(ok(
        message=f"Doctor: {'ready' if ready else 'NOT ready'} — {summary}",
        data={"ready": ready, "summary": summary, "checks": checks},
    ))


# Keep an importable alias matching the plan's file naming (check_setup).
def check_setup(ctx: Context) -> str:  # pragma: no cover - thin alias
    return rhinoclaw_doctor(ctx)
