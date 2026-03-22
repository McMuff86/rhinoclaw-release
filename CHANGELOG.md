# Changelog

## [0.2.5] - 2026-03-22

### Added
- **Python 3 (CPython) execution** via `execute_python3_code` command
  - Hybrid approach: tries RhinoCodePlatform reflection API first, falls back to ScriptEditor temp file execution
  - Full stdout/stderr capture with structured JSON result
  - Proper error handling with traceback
  - Undo transaction support (auto-rollback on failure)
  - Requires Rhino 8+ (returns clear error on Rhino 7)
- **`get_script_capabilities` command** — query available scripting engines
  - Returns `ironpython2`, `python3` availability, and `rhino_version`
  - Useful for agents to determine which script executor to use

## [0.2.4] - 2026-03-22

### Added
- **VisualARQ BIM Integration** – Complete BIM workflow with graceful degradation
  - **`visualarq.py` script** (1553 lines) with 24 commands for BIM object management
  - **Walls, doors, windows, columns, beams, slabs** – Full architectural BIM objects
  - **Building hierarchy** – Buildings and levels with elevation management
  - **Custom BIM parameters** – Add/set/get custom properties (text, number, boolean, length)
  - **IFC import/export** – Support for IFC2x3, IFC4, IFC4.3 formats
  - **Style management** – Query and create wall/door/window styles
  - **Object queries** – List all BIM objects with properties
  - **Graceful degradation** – No crashes when VisualARQ not installed

#### VisualARQ Commands Added

| Category | Commands | Description |
|----------|----------|-------------|
| **Setup** | `check`, `info` | Verify installation, get styles/levels overview |
| **Geometry** | `wall`, `door`, `window`, `column`, `beam`, `slab` | Create BIM objects with styles |
| **Hierarchy** | `levels`, `add-level`, `add-building` | Building structure management |
| **Parameters** | `add-param`, `set-param`, `get-param` | Custom BIM properties |
| **IFC** | `ifc-export`, `ifc-import` | Industry standard exchange |
| **Queries** | `list-walls`, `list-doors`, `list-windows`, `list-objects` | BIM object inspection |
| **Styles** | `wall-styles`, `door-styles`, `window-styles`, `add-wall-style` | Style management |

## [0.2.3] - 2026-03-19

### Added
- **`build_gh_definition` command** – programmatic Grasshopper definition builder
  - Python 3 Script components with custom named inputs/outputs
  - Number Sliders, Boolean Toggles, Panels
  - SDK (native) components by GUID
  - Custom Preview components with Material input
  - Colour Swatch with named presets (wood, oak, walnut, birch, steel, glass, etc.)
  - Automatic wiring between components by name or index
- **`build_and_bake_gh` command** – build + solve + bake to named Rhino layer
  - Optional layer colour and material assignment
  - Configurable bake output parameter
- **Template catalog** at `skills/rhinoclaw/templates/ghscripts/`
  - Parametric Chair (curved backrest, tapered legs, stretchers)
  - Parametric Table (tapered legs, aprons, overhang)
  - Parametric Shelf (adjustable shelves, divisions, back panel, plinth)
  - TwistedTower (helix sculpture with 8 parameters)

### Key Discovery
Rhino 8 Python 3 Script components require specific initialization:
1. Add to active GH_Document BEFORE parameter manipulation
2. Use `CreateParameter()` + `VariableParameterMaintenance()` for new params
3. `SetParametersToScript()` to bind params to script runtime
4. `#! python3` shebang in source code

## [0.2.2] - 2026-03-19

### Changed
- Version bump for GH builder integration

## [0.2.1] - 2026-03-18

### Changed
- **Renamed SentinelChat → ClawChat** – generic branding for public release
  - Rhino Command: `ClawChat` (was `SentinelChat`)
  - Panel title: "RhinoClaw Chat" (was "Sentinel Chat")
  - Settings key: `ClawChatUrl` (auto-migrates from `SentinelChatUrl`)
- Updated manifest description

### Fixed
- Panel registration stability

## [0.2.0] - 2026-03-16

### Added
- **ClawChat Panel** – embedded AI chat directly inside Rhino 8
  - Eto.Forms WebView, Rhino Command: `ClawChat`
  - Setup screen with presets: OpenClaw, Tailscale, Ollama, LibreChat, Custom URL
  - Persistent URL, ⚙ Settings button
- Smart Grasshopper prompt handling with parameter metadata pre-loading
- Build-and-install PowerShell script

### Changed
- Bumped version to 0.2.0
- Updated Yak manifest for publish

## [0.1.3.9] - 2026-02

### Added
- 72 MCP tools for geometry, transforms, booleans, materials
- Grasshopper integration (SDK, Player, Presets)
- Viewport control, screenshots, render settings
- Groups & Blocks management
- File operations (import/export)
- Boolean operations (union, difference, intersection)
- PBR material support
- Enhanced debugging and logging

## [0.1.0] - 2026-01

### Added
- Initial release
- TCP/WebSocket server in Rhino plugin
- Python MCP server
- Basic geometry creation and manipulation
- Document inspection
- Script execution
