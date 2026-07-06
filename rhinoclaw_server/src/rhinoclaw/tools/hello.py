import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def hello(ctx: Context) -> str:
    """Auth-free handshake — discover the plugin's state WITHOUT needing a token.

    `hello` bypasses the plugin's auth gate AND the brute-force counter, so you
    can always learn the server's state safely, even with no/wrong token and
    even while blocked. It returns only non-secret metadata. Prefer `preflight`,
    which wraps this into a single actionable verdict.

    Returns (in `data`):
        - plugin_version
        - auth_required: does the plugin require a token?
        - mode: "tcpstart" (remote/0.0.0.0) | "mcpstart" (local)
        - gh_available: is Grasshopper loaded?
        - blocked: is THIS remote in the brute-force cooldown? (not a token check)
        - blocked_until: ISO-8601 (only when blocked)
        - server_time

    Note: requires a plugin build that supports `hello`. On older plugins this
    returns an error (UNKNOWN_COMMAND or AUTH_REQUIRED) — `preflight` handles
    that fallback for you.
    """
    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("hello", {})
        return json.dumps(ok(
            message=(
                f"Plugin {result.get('plugin_version', '?')} · "
                f"auth_required={result.get('auth_required')} · "
                f"mode={result.get('mode')} · gh={result.get('gh_available')} · "
                f"blocked={result.get('blocked')}"
            ),
            data=result,
        ))
    except Exception as e:
        logger.error(f"hello handshake failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
