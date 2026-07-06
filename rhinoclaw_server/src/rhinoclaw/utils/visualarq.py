"""Shared runner for VisualARQ script execution (NEXT-LEVEL-PLAN 4.1).

VisualARQ has no public .NET SDK on NuGet; its scripting surface is the
`VisualARQ.Script` assembly inside Rhino. Every VA tool ships a small
IronPython-2.7 body that runs in-process; this module wraps it with:
- parameter injection via JSON (no string-format escaping),
- VisualARQ availability detection → graceful degradation,
- RESULT-line parsing back to a dict.

Port of the proven `scripts/rhinoclaw_client/visualarq.py` mechanics.
"""
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("rhinoclaw.visualarq")

_PRINT_PREFIX = "Script successfully executed! Print output: "

# The body runs with `va` (VisualARQ.Script), `params` (injected dict),
# `Guid`, `rg` (Rhino.Geometry) in scope and must assign `result`.
_TEMPLATE = """import clr
import json
params = json.loads({params_json!r})
result = None
try:
    clr.AddReference("VisualARQ.Script")
    import VisualARQ.Script as va
except Exception as e:
    result = {{"available": False, "status": "unavailable",
              "message": "VisualARQ not available: " + str(e)}}
if result is None:
    try:
        from System import Guid
        import Rhino.Geometry as rg
{body}
    except Exception as e:
        result = {{"status": "error", "message": "VisualARQ error: " + str(e)}}
print("RESULT:" + json.dumps(result))
"""


def build_va_script(body: str, params: Optional[Dict[str, Any]] = None) -> str:
    """Wrap an IronPython body (sets `result`) with the VA prelude."""
    indented = "\n".join(
        "        " + line if line.strip() else line
        for line in body.strip("\n").splitlines()
    )
    return _TEMPLATE.format(
        params_json=json.dumps(params or {}),
        body=indented,
    )


def run_va(rhino, body: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a VA script body in Rhino, return the parsed `result` dict."""
    code = build_va_script(body, params)
    raw = rhino.send_command("execute_rhinoscript_python_code", {"code": code})

    text = raw if isinstance(raw, str) else ""
    if isinstance(raw, dict):
        nested = raw.get("output", raw.get("result", ""))
        text = nested if isinstance(nested, str) else str(nested or "")
    if text.startswith(_PRINT_PREFIX):
        text = text[len(_PRINT_PREFIX):]

    if "RESULT:" not in text:
        return {"status": "error",
                "message": f"No RESULT line in VA script output: {text[:200]}"}
    payload = text.split("RESULT:", 1)[1].strip().splitlines()[0]
    return json.loads(payload)


def va_unavailable(result: Dict[str, Any]) -> bool:
    """True when the script reported VisualARQ as not loaded."""
    return result.get("available") is False
