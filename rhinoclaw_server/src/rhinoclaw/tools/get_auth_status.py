import json

from mcp.server.fastmcp import Context

from rhinoclaw.config import get_settings
from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def get_auth_status(ctx: Context) -> str:
    """Verify whether the auth token is correctly configured on both ends.

    Calls `ping` against the plugin so the round-trip exercises the
    auth middleware. Without revealing the actual token, the response
    tells you:
    - whether the client is sending a token at all
    - whether the plugin accepted it (= ping reached the handler)
    - the token's first/last 4 characters as a fingerprint, so you can
      visually confirm both sides are using the same value without ever
      logging the secret

    Use this right after `setup-auth-token.ps1` to verify the wiring,
    then never again.

    Returns:
        On success:
            {
              "success": true,
              "data": {
                "client_sends_token": true,
                "plugin_accepts_token": true,
                "token_fingerprint": "abc1...xyz9",
                "auth_required_on_plugin": true | "unknown"
              }
            }
        On AUTH_REQUIRED:
            {"success": false, "code": "AUTH_REQUIRED", ...}
            → token mismatch or only one side has it set.
    """
    try:
        settings = get_settings()
        client_token = settings.auth_token
        client_sends_token = bool(client_token)

        # Round-trip a ping. If the plugin enforces auth and the token is
        # wrong, this raises with AUTH_REQUIRED; the except block returns
        # a structured error so the user sees what went wrong.
        rhino = get_rhino_connection()
        rhino.send_command("ping", {})

        fingerprint = _fingerprint(client_token) if client_sends_token else None

        return json.dumps(ok(
            message=(
                "Auth verified — token accepted by plugin"
                if client_sends_token
                else "Plugin reachable; client is NOT sending an auth token"
            ),
            data={
                "client_sends_token": client_sends_token,
                "plugin_accepts_token": True,
                "token_fingerprint": fingerprint,
                # We can't directly query the plugin's auth setting today;
                # the ping succeeded so EITHER both sides have a matching
                # token OR neither side has one. The next ping_no_auth call
                # could distinguish, but it's not critical for setup.
                "auth_required_on_plugin": "unknown" if not client_sends_token else True,
            },
        ))

    except Exception as e:
        logger.error(f"Auth status check failed: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


def _fingerprint(token: str) -> str:
    """First 4 + ellipsis + last 4. Enough to spot-check parity, not enough
    to reconstruct the token from a screenshot."""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"
