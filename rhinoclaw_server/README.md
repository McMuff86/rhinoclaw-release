# RhinoClaw Server

Python MCP server that connects AI agents to Rhino 3D via the Model Context Protocol.

## Overview

This server bridges AI agents (Claude, Cursor, etc.) to Rhino through:
- **FastMCP**: Python MCP implementation
- **TCP Socket**: Communication with Rhino plugin on `localhost:1999`

## Installation

```bash
# Install uv (if not already installed)
# macOS: brew install uv
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install dependencies
cd rhinoclaw_server
uv pip install -e .
```

## Usage

```bash
# Development mode
uv run python -m rhinoclaw

# Or via uvx (installed)
uvx rhinoclaw
```

**Note:** Start the Rhino plugin first (`mcpstart` in Rhino command line).

## Project Structure

```
rhinoclaw_server/
├── src/rhinoclaw/
│   ├── server.py          # Main server, FastMCP setup
│   ├── tools/             # MCP tool implementations
│   │   ├── create_object.py
│   │   ├── modify_object.py
│   │   ├── get_document_info.py
│   │   └── ...
│   ├── utils/             # Helper utilities
│   └── prompts/           # AI prompts
├── dev/                   # Development scripts
│   ├── dev_test.py        # Basic testing
│   └── dev_castle.py      # Example: castle generation
└── pyproject.toml         # Package configuration
```

## Available Tools

For the complete and up-to-date tool list, see [USAGE.md](../USAGE.md).

**Categories:**
- **System**: ping, get_document_info, get_logs, set_debug_mode
- **Object Creation**: create_object, create_objects, create_text, create_text_dot
- **Object Manipulation**: modify_object, delete_object, select_objects, get_object_properties, set_object_properties
- **Boolean Operations**: boolean_operation (union, difference, intersection)
- **Transform**: copy_object, mirror_object, array_linear, array_polar
- **Curves**: offset_curve, fillet_curves, chamfer_curves
- **Surfaces**: loft_curves, extrude_curve, revolve_curve
- **Dimensions**: create_linear_dimension, create_angular_dimension, create_radial_dimension
- **Layers & Materials**: create_layer, create_material, assign_material_to_layer
- **Scripts**: execute_rhinoscript_python_code

## Development

```bash
# Run tests
uv run python dev/dev_test.py

# Build package
uv build

# Publish to PyPI
uv publish
```

## Documentation

- [Main README](../README.md) - Installation and usage
- [AGENTS.md](../AGENTS.md) - Agent-focused guide
- [USAGE.md](../USAGE.md) - Tool reference and usage examples
