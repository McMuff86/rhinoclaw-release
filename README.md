# RhinoClaw 0.8.2

RhinoClaw connects AI clients to Rhino through 181 MCP tools for geometry,
Grasshopper, viewports and optional VisualARQ workflows.

## Install

1. In Rhino for Windows, run `PackageManager`, search for `rhinoclaw`, and install
   version **0.8.2**. Restart Rhino to load it.
   For a downloaded release, install the `.yak` in [packages/](packages/) with
   Rhino closed using `"C:\Program Files\Rhino 8\System\yak.exe" install <package.yak>`.
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
3. Add this entry to your AI client's MCP configuration:

```json
{
  "mcpServers": {
    "rhinoclaw": {
      "command": "uvx",
      "args": ["--from", "rhinoclaw==0.8.2", "rhinoclaw"]
    }
  }
}
```

4. In Rhino run `ClawStart`. Run `preflight` and `rhinoclaw_doctor` from the client.
   Use one Rhino session and one controlling MCP client at a time.

## Upgrade from 0.7.15

Update both the Rhino plug-in and the Python server. Commands now use the `Claw`
prefix: `ClawStart`, `ClawStop`, `ClawStatus`, `ClawAutoStart` and `ClawTcpStart`.
Rhino 9's `MCPStart` starts RhinoAI, not RhinoClaw. Some legacy tools now return
structured JSON responses. See [CHANGELOG.md](CHANGELOG.md) for 0.8.0–0.8.2 changes.

The Windows package contains .NET 7, 8 and 10 assemblies with an API baseline of
Rhino 8.17. Native runtime acceptance and optional VisualARQ limitations are
recorded in the [release handoff](https://github.com/McMuff86/RhinoClaw/blob/main/docs/HANDOFF-2026-10-13-RELEASE-0.8.2.md).
Assembly inclusion alone does not certify a host or third-party plug-in.

## Contents and development

This snapshot contains the installable Yak package, Python runtime sources,
user documentation and [release-inventory.json](release-inventory.json) with
SHA256 checksums. It excludes local logs, model fixtures, screenshots, caches,
developer scripts and agent-session files. The required GH and RhinoScript
reference catalogs are included. The Python source distribution on PyPI also
contains the automated tests.

Development, tests and issues live in [RhinoClaw](https://github.com/McMuff86/RhinoClaw).
See the [tool reference](https://github.com/McMuff86/RhinoClaw/blob/main/docs/USAGE.md)
and [SECURITY.md](SECURITY.md) for configuration and authentication. Configuration
uses environment variables; there is no runtime `config.example.json` in this snapshot.

MIT license. Copyright and license text: [LICENSE](LICENSE).
