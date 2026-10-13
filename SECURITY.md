# Security Policy

## Threat Model

RhinoClaw lets an AI agent execute commands inside Rhino. By design, the
plugin exposes a TCP server (default port `1999`) and a WebSocket server
(default port `2000`) that accept JSON commands. Two of those commands —
`execute_rhinoscript_python_code` and `execute_python3_code` — run
**arbitrary code** in the Rhino process.

Anyone who can talk to those ports can:

- Read, modify and delete the active `.3dm` document
- Read and write files anywhere the Rhino process can reach
- Execute arbitrary Python with full access to the user's machine

## Default Posture

- `ClawStart` binds to `127.0.0.1` (loopback only). This is the recommended
  mode and is what you want for Cursor / Claude Desktop / any other
  MCP-over-stdio agent on the same machine.
- `ClawTcpStart` binds to `0.0.0.0` (all interfaces). It exists for use cases
  like WSL bridges or LAN-attached AI runners and is **not safe to expose
  beyond a trusted host**. Optional token authentication protects TCP commands
  and WebSocket commands/subscriptions; it does not encrypt network traffic.

## Recommendations

- **Local use:** prefer `ClawStart`. Do not open ports 1999 / 2000 in your
  firewall.
- **Remote / WSL use:** only run `ClawTcpStart` on networks you fully control
  (e.g. a Tailscale tailnet, a local-only Docker network, or a WSL
  loopback). Stop the server when you are done (`ClawStop`).
- **Multi-user workstations:** assume any local user on the machine can
  reach the loopback port. Do not run RhinoClaw on shared workstations
  with untrusted users.
- **Sensitive documents:** RhinoClaw can read and modify your active
  document. Close confidential `.3dm` files before connecting an
  unfamiliar AI agent.

## Auto-Start (0.2.7+)

The `ClawAutoStart` command persists a "start the server on Rhino launch"
flag (off by default after install/update). When enabled in **TCP mode**,
the plugin will, on every Rhino launch, bind `0.0.0.0:1999` without
asking — meaning the same risks that apply to a manual `ClawTcpStart` apply
silently across reboots. Two safeguards:

- The plugin prints a loud multi-line warning to the Rhino command line
  if auto-start fires in TCP mode without `RHINOCLAW_AUTH_TOKEN` set.
- Switching to loopback-only is one command: `ClawAutoStart` → "Mode" →
  toggles to `mcp` (`127.0.0.1`).

If you enable auto-start with TCP, **set `RHINOCLAW_AUTH_TOKEN`
machine-wide** (e.g. via Windows User-Environment-Variables) so it's
present from the first Rhino launch.

## Brute-Force Protection (0.4.0+)

When `RHINOCLAW_AUTH_TOKEN` enforcement is on, the plugin tracks
authentication failures per remote endpoint. After `MAX_FAILURES`
within `FAILURE_WINDOW`, the source is blocked for `BLOCK_DURATION`
and further commands are rejected with `AUTH_BLOCKED` (with the
`blocked_until` timestamp in the response).

Defaults — tunable via env vars:

| Variable | Default | Meaning |
|----------|---------|---------|
| `RHINOCLAW_AUTH_MAX_FAILURES` | `5` | Failed-token attempts that trip a block |
| `RHINOCLAW_AUTH_FAILURE_WINDOW` | `60` (s) | Sliding window the failures are counted in |
| `RHINOCLAW_AUTH_BLOCK_DURATION` | `900` (s = 15 min) | How long the block lasts |

A successful auth check inside the window clears the failure counter
for that remote — a transient typo doesn't compound across retries.

**Audit log** — every auth event is appended (one JSON-Line per
event) to:

```
%LOCALAPPDATA%\rhinoclaw\logs\auth_YYYYMMDD.jsonl
```

Each line carries timestamp, remote endpoint, command name, outcome
(`success` / `failure` / `blocked` / `rejected_pre_block`) and reason
(`missing_token` / `invalid_token`). Audit writes are best-effort —
if the disk is full, the auth path still flows. The file rotates
daily.

## Token Authentication (0.2.6+)

Since 0.8.1 all WebSocket commands except the metadata-only `ping` require
the same configured token as TCP. Send `auth` on every request. Event clients
must first send `{"command":"subscribe","request_id":"...","auth":"..."}`
and receive `Subscribed`; the public `Connected` welcome contains no prompt
or document state. History, prompts and document events are delivered only
to authorized subscribers. A rejected request revokes event subscriptions.
The Python client subscribes automatically, including after reconnection.
Clients of older plugins still work, but those plugins do not enforce this
WebSocket protection. Upgrade both components together.

Transport debug logs omit credential-bearing wire messages. Standard Python
logs, interaction logs and plugin logger output redact the configured token.

When `ClawTcpStart` is unavoidable (WSL, Tailscale, LAN runners), set a
shared secret on both sides via the `RHINOCLAW_AUTH_TOKEN` environment
variable. Every command without a matching token will be rejected with
`AUTH_REQUIRED`.

**Generate and persist a token (recommended on Windows):**

```powershell
# Run once on the Rhino host. Generates a 256-bit random token,
# persists it as a User-environment variable, and prints
# copy-paste instructions for the WSL / Cursor / Claude side.
.\scripts\setup-auth-token.ps1
```

The token is stored as the User-environment variable
`RHINOCLAW_AUTH_TOKEN` and survives reboots. Restart Rhino so the
plugin picks it up.

**Manually (if you don't want the helper):**

```bash
# Linux / macOS / WSL
export RHINOCLAW_AUTH_TOKEN=$(openssl rand -hex 32)
```

```powershell
# Windows — quick one-liner using .NET's CSPRNG (NOT Get-Random; that's
# not cryptographic). Saves to the User-environment variable so Rhino
# inherits it on next launch.
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
[Environment]::SetEnvironmentVariable('RHINOCLAW_AUTH_TOKEN', $token, 'User')
$env:RHINOCLAW_AUTH_TOKEN = $token
$token  # prints the token for the client side
```

**Set it on both sides before starting:**

1. On the Rhino host, set the variable in the same shell that launches
   Rhino, then run `ClawTcpStart`. The plugin reads the variable on `Start()`
   and prints `Auth: enforcing RHINOCLAW_AUTH_TOKEN on every command`.
2. On the AI client (`uvx rhinoclaw`, Cursor, Claude Desktop), set the
   same variable so the Python client can attach it to every JSON
   command.

Constant-time comparison is used inside the plugin to defeat timing
attacks. Note that the token is only as strong as the channel: if you
expose `ClawTcpStart` on a hostile network, an attacker who can sniff the
plaintext TCP stream still gets the token. Use it on top of a trusted
transport (Tailscale, WireGuard, SSH tunnel), not as a replacement for
one.

**Verify the wiring after setup:**

From the AI client side, call the `get_auth_status` MCP tool. It does
a round-trip ping through the plugin and tells you whether the token
matches. The response includes a fingerprint (first 4 + last 4
characters) so you can spot-check that both sides are using the same
value without ever logging the secret in full.

**Re-print or revoke later:**

```powershell
.\scripts\setup-auth-token.ps1 -Reveal   # show the current token
.\scripts\setup-auth-token.ps1 -Remove   # revoke (plugin accepts everything again)
```

Token authentication is opt-in and backwards-compatible: with the
variable unset, 0.2.6 behaves exactly like 0.2.5.

## Reporting a Vulnerability

If you find a security issue, please email **info@solid-ai.ai** with:

- A description of the issue and its impact
- Steps to reproduce
- The version of RhinoClaw and Rhino you tested against

We aim to acknowledge reports within five business days. Please give us
a reasonable window to ship a fix before public disclosure.
