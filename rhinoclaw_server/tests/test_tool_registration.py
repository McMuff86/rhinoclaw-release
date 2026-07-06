"""Regression guard: every @mcp.tool() in tools/ must actually be reachable.

Tools register with FastMCP at import time, so a tool module that exists but
is not imported in ``rhinoclaw/__init__.py`` silently disappears from MCP
(the "13 decorated-but-unregistered tools" gap fixed in Wave 5).  This test
statically scans ``tools/*.py`` for decorated functions and asserts each one
is registered and re-exported, so the drift can never recur.
"""
import ast
import asyncio
from pathlib import Path

import rhinoclaw

TOOLS_DIR = Path(rhinoclaw.__file__).parent / "tools"


def _decorated_tool_names():
    """All function names under tools/ decorated with @mcp.tool(...)."""
    names = []
    for py_file in sorted(TOOLS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute) and target.attr == "tool":
                    names.append((py_file.name, node.name))
    return names


def test_tools_dir_is_scanned():
    assert len(_decorated_tool_names()) > 90, "AST scan found suspiciously few tools"


def test_every_decorated_tool_is_registered_with_mcp():
    registered = {tool.name for tool in asyncio.run(rhinoclaw.mcp.list_tools())}
    missing = [
        f"{file}: {name}"
        for file, name in _decorated_tool_names()
        if name not in registered
    ]
    assert not missing, (
        "Decorated tools missing from the MCP registry — add the module import "
        f"to rhinoclaw/__init__.py: {missing}"
    )


def test_every_decorated_tool_is_reexported():
    missing = [
        f"{file}: {name}"
        for file, name in _decorated_tool_names()
        if not hasattr(rhinoclaw, name)
    ]
    assert not missing, (
        "Decorated tools not re-exported from the rhinoclaw package — add the "
        f"name to the import in rhinoclaw/__init__.py: {missing}"
    )
