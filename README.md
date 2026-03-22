# RhinoClaw - AI-Powered Rhino 3D Automation via MCP

[![CI](https://github.com/McMuff86/rhinoclaw/actions/workflows/ci.yml/badge.svg)](https://github.com/McMuff86/rhinoclaw/actions/workflows/ci.yml)
![Tests](https://img.shields.io/badge/tests-333%20passed-brightgreen)
![Version](https://img.shields.io/badge/version-0.2.5-blue)
[![ClawHub](https://img.shields.io/badge/ClawHub-rhinoclaw-orange)](https://clawhub.ai/McMuff86/rhinoclaw)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

<img src="assets/rhinoclaw_logo.png" alt="RhinoClaw Logo" width="130">

RhinoClaw connects **Rhino 3D** to AI agents through the **Model Context Protocol (MCP)**, enabling prompt-assisted 3D modeling, automation, and parametric design. With **72 MCP tools**, it's the most comprehensive Rhino-AI integration available.

## What Can You Do?

- 🗣️ **Talk to Rhino** — Create and modify 3D geometry with natural language
- 🔧 **Automate workflows** — Boolean operations, transforms, arrays, materials
- 🏗️ **BIM workflows** — VisualARQ integration for walls, doors, windows, levels, IFC export (optional dependency)
- 🦗 **Grasshopper integration** — Build, solve, and bake parametric definitions programmatically
- 📸 **Capture & render** — Viewport screenshots, render settings, camera control
- 📦 **Full pipeline** — Import/export, layers, groups, blocks, mesh operations

## Quick Start

### 1. Install the Rhino Plugin

In Rhino: **Tools → Package Manager → Search "rhinoclaw" → Install**

### 2. Install UV (Python package manager)

```bash
# macOS
brew install uv

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 3. Configure Your AI Client

Add to your MCP config file:

```json
{
  "mcpServers": {
    "rhino": {
      "command": "uvx",
      "args": ["rhinoclaw"]
    }
  }
}
```

**Config file locations:**
- **Claude Desktop:** Claude → Settings → Developer → Edit Config
- **Cursor:** Create `.cursor/mcp.json` in your project root
- **Other MCP clients:** See their documentation for config file location

### 4. Connect

1. In Rhino, type `mcpstart` in the command line
2. Your AI client should show RhinoClaw tools as available

> **⚠️ Run only one MCP server instance** (either Cursor or Claude Desktop, not both)

### Alternative: OpenClaw Integration

If you use [OpenClaw](https://openclaw.ai), install the RhinoClaw **AgentSkill** from [ClawHub](https://clawhub.ai/McMuff86/rhinoclaw):

```bash
npx clawhub@latest install rhinoclaw
```

Then configure the skill:

```bash
cd skills/rhinoclaw
cp config.example.json config.json
# Edit config.json with your Rhino host IP
```

In Rhino, type `tcpstart` (instead of `mcpstart`) for remote/WSL access. Your OpenClaw agent can now control Rhino directly — geometry, materials, Grasshopper, VisualARQ, everything.

> **ClawHub page:** [clawhub.ai/McMuff86/rhinoclaw](https://clawhub.ai/McMuff86/rhinoclaw)

## Features (72 Tools)

| Category | Tools | Examples |
|----------|-------|---------|
| **Geometry Creation** | 13 types | Box, Sphere, Cylinder, Cone, Surface, Mesh, Points, Curves, Arcs, Ellipses |
| **Object Modification** | Modify, Properties, Selection | Rename, recolor, move to layer, batch operations |
| **Transforms** | Copy, Mirror, Arrays | Linear array, polar array, transform operations |
| **Boolean Operations** | Union, Difference, Intersection | Solid modeling workflows |
| **Curve & Surface** | Offset, Fillet, Chamfer, Loft, Extrude, Revolve | Complex surface creation |
| **Materials & Rendering** | PBR Materials, Layer Materials, Render Settings | Full material pipeline |
| **Layers & Organization** | Create, Delete, Set Current | Layer management |
| **Viewport** | Camera, Orbit, Zoom, Capture, Render | Screenshots, view control |
| **Groups & Blocks** | Create, Ungroup, Insert, Explode | Object hierarchies |
| **Grasshopper** | SDK, Player, Build, Bake | Parametric automation |
| **GH Definition Builder** | Build .gh files programmatically | Python 3 Script nodes, sliders, auto-wiring |
| **VisualARQ BIM** | Walls, Doors, Windows, Levels, IFC | Complete BIM workflow (optional dependency) |
| **File Operations** | Open, Save, Import, Export | Multiple format support |
| **Mesh Operations** | Import, Export, Convert | Mesh processing |
| **Script Execution** | Python, RhinoScript | Custom automation |
| **Dimensions** | Create dimensions, Query properties | Annotation tools |

See [docs/USAGE.md](docs/USAGE.md) for the complete tool reference with parameters and examples.

## Grasshopper Definition Builder

Build parametric Grasshopper definitions entirely from your AI agent:

```
"Create a parametric table with adjustable width, depth, height, 
leg taper, and overhang. Bake it to a layer called 'Furniture'."
```

RhinoClaw can:
- Create Python 3 Script components with custom I/O
- Add Number Sliders, Boolean Toggles, Panels
- Wire components together automatically
- Solve and bake to named layers with materials
- Use colour presets (wood, oak, walnut, steel, glass...)

**Included templates:** Parametric Chair, Table, Shelf, TwistedTower

## ClawChat — AI Chat Inside Rhino

Built-in chat panel directly in Rhino 8:
- Works with OpenClaw, Ollama, LibreChat, or any custom endpoint
- Persistent settings, one-click setup
- Command: `ClawChat` in Rhino

## Architecture

```
┌─────────────────┐     TCP:1999     ┌──────────────────┐
│   AI Agent       │ ◄──────────────► │   MCP Server     │
│ (Claude/Cursor)  │                  │   (Python)       │
└─────────────────┘                  └────────┬─────────┘
                                              │
                                     ┌────────▼─────────┐
                                     │   Rhino Plugin   │
                                     │   (C# / .NET)    │
                                     └──────────────────┘
```

- **MCP Server** (`rhinoclaw_server/`): Python, FastMCP — handles tool routing
- **Rhino Plugin** (`rhinoclaw_plugin/`): C#, RhinoCommon — executes commands in Rhino
- **Transport**: JSON over TCP (port 1999), WebSocket monitoring (port 2000)

## Requirements

- **Rhino 7+** (Windows and Mac) — keep Rhino up to date
- **Python 3.10+**
- **UV** package manager

**Optional Dependencies:**
- **VisualARQ** — For BIM workflows (walls, doors, windows, IFC). RhinoClaw works without VisualARQ installed.

## Development

```bash
# Install dev dependencies
cd rhinoclaw_server
uv pip install -e ".[dev]"

# Run tests (333 tests)
uv run pytest tests/ -v

# Build
cd rhinoclaw_server && uv build        # Python package
cd rhinoclaw_plugin && dotnet build -c Release  # C# plugin
```

See [AGENTS.md](AGENTS.md) for the full development guide.

## Contributing

Contributions welcome! Please submit a Pull Request.

- [AGENTS.md](AGENTS.md) — Development guidelines & agent integration
- [docs/USAGE.md](docs/USAGE.md) — Tool reference & examples
- [docs/ROADMAP.md](docs/ROADMAP.md) — Project roadmap
- [FUTURE_ISSUES.md](FUTURE_ISSUES.md) — Known issues & planned features

## License

MIT License — See [LICENSE](LICENSE) for details.

## Author

Created by [Solid AI](https://solid-ai.ai) · [McMuff86](https://github.com/McMuff86)
