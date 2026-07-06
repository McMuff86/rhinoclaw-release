import json

from mcp.server.fastmcp import Context

from rhinoclaw.config import get_settings
from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.responses import ok


def _verdict(connected, auth, next_action, *, host=None, port=None,
             plugin=None, mode=None, hello_supported=None, detail=None,
             blocked_until=None):
    data = {
        "connected": connected,
        "auth": auth,
        "next_action": next_action,
        "host": host,
        "port": port,
    }
    if plugin is not None:
        data["plugin_version"] = plugin
    if mode is not None:
        data["mode"] = mode
    if hello_supported is not None:
        data["hello_supported"] = hello_supported
    if blocked_until is not None:
        data["blocked_until"] = blocked_until
    if detail:
        data["detail"] = detail
    return json.dumps(ok(
        message=("READY" if auth == "ready" else f"NOT READY — {next_action}"),
        data=data,
    ))


@mcp.tool()
def preflight(ctx: Context) -> str:
    """RUN THIS FIRST. One call → the complete connection/auth state + the exact
    `next_action`. No trial-and-error: only call other tools when
    `data.auth == "ready"`.

    Uses the auth-free `hello` handshake when available (never trips the
    brute-force block); falls back to a single ping on older plugins.

    `data.auth` ∈ {ready, missing_client_token, token_mismatch, blocked, unknown}.
    `data.next_action` is a one-line instruction. Rules:
    - `ready` → proceed.
    - `missing_client_token` / `token_mismatch` → CONFIG error, do NOT retry;
      fix RHINOCLAW_AUTH_TOKEN (same value both sides) + restart Rhino.
    - `blocked` → respect the cooldown (`blocked_until`); do NOT retry.
    - `unknown` (not connected) → start Rhino + `tcpstart`; on WSL check
      RHINOCLAW_HOST.
    """
    settings = get_settings()
    client_has_token = bool(settings.auth_token)
    host, port = settings.host, settings.port

    # 1. Can we reach the plugin at all?
    try:
        rhino = get_rhino_connection()
    except Exception as e:
        return _verdict(
            False, "unknown",
            f"Plugin not reachable at {host}:{port}. Start Rhino + run `tcpstart` "
            f"(or `mcpstart`); on WSL check RHINOCLAW_HOST.",
            host=host, port=port, detail=str(e),
        )

    # 2. Auth-free discovery (no token needed, no brute-force counter).
    try:
        h = rhino.send_command("hello", {})
    except Exception as e:
        return _preflight_fallback(e, client_has_token, host, port)

    plugin = h.get("plugin_version")
    mode = h.get("mode")
    auth_required = h.get("auth_required")

    if h.get("blocked"):
        return _verdict(
            True, "blocked",
            f"blocked until {h.get('blocked_until')} — wait, do NOT retry "
            f"(too many failed auth attempts).",
            host=host, port=port, plugin=plugin, mode=mode,
            hello_supported=True, blocked_until=h.get("blocked_until"),
        )

    if auth_required and not client_has_token:
        return _verdict(
            True, "missing_client_token",
            "plugin requires a token but the client sends none — set "
            "RHINOCLAW_AUTH_TOKEN on the client (same value as the plugin) and restart.",
            host=host, port=port, plugin=plugin, mode=mode, hello_supported=True,
        )

    if auth_required and client_has_token:
        # Confirm the token actually matches with ONE authenticated ping.
        try:
            rhino.send_command("ping", {})
            return _verdict(True, "ready", "ready", host=host, port=port,
                            plugin=plugin, mode=mode, hello_supported=True)
        except Exception as e:
            return _verdict(
                True, "token_mismatch",
                "auth token mismatch — set the SAME RHINOCLAW_AUTH_TOKEN on both "
                "client and plugin, then restart Rhino (the plugin reads it at start).",
                host=host, port=port, plugin=plugin, mode=mode,
                hello_supported=True, detail=str(e),
            )

    return _verdict(True, "ready", "ready", host=host, port=port,
                    plugin=plugin, mode=mode, hello_supported=True)


def _preflight_fallback(hello_error, client_has_token, host, port):
    """Older plugin without `hello`: classify the hello error, then verdict.

    On a pre-`hello` plugin the command still hits the auth gate, so the error
    text already tells us the auth state (an "unknown command" error means the
    request got PAST auth — so auth is fine, the plugin just predates `hello`).
    """
    msg = str(hello_error).lower()
    if "auth token missing or invalid" in msg or "auth_required" in msg:
        if not client_has_token:
            return _verdict(
                True, "missing_client_token",
                "plugin requires a token but the client sends none — set "
                "RHINOCLAW_AUTH_TOKEN (same value as the plugin) and restart. "
                "(Also re-sync the skill: scripts/sync-skill.sh.)",
                host=host, port=port, hello_supported=False,
            )
        return _verdict(
            True, "token_mismatch",
            "auth token mismatch — same RHINOCLAW_AUTH_TOKEN on both sides, then "
            "restart Rhino.",
            host=host, port=port, hello_supported=False,
        )
    if "blocked" in msg:
        return _verdict(
            True, "blocked",
            "blocked (too many failed auth attempts) — wait out the cooldown, do NOT retry.",
            host=host, port=port, hello_supported=False,
        )
    if "unknown command" in msg:
        # Got past auth → connection + auth are fine; plugin just predates hello.
        return _verdict(
            True, "ready",
            "ready — note: this plugin predates `hello`; rebuild to enable the "
            "auth-free handshake.",
            host=host, port=port, hello_supported=False,
        )
    logger.warning(f"preflight: unexpected handshake error: {hello_error}")
    return _verdict(
        True, "unknown", f"unexpected handshake error: {hello_error}",
        host=host, port=port, hello_supported=False,
    )
