import json
import time
from typing import Any, Dict

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

_PRINT_PREFIX = "Script successfully executed! Print output: "

# IronPython 2.7 probe — runs on the UI thread, so the very fact that it
# answers already proves the thread is not hard-blocked.
_PROBE = """
import Rhino
import json
state = {}
try:
    state['in_command'] = int(Rhino.Commands.Command.InCommand())
except Exception:
    state['in_command'] = None
try:
    stack = list(Rhino.Commands.Command.GetCommandStack() or [])
    state['command_stack'] = [str(c) for c in stack]
except Exception:
    state['command_stack'] = []
try:
    state['prompt'] = Rhino.RhinoApp.CommandPrompt or ''
except Exception:
    state['prompt'] = ''
# Modal dialogs disable the main window — the one reliable Win32 signal.
try:
    import clr
    clr.AddReference('Eto')
    from Rhino.UI import RhinoEtoApp
    w = RhinoEtoApp.MainWindow
    state['main_window_enabled'] = bool(w.Enabled) if w is not None else None
except Exception:
    state['main_window_enabled'] = None
print('STATE:' + json.dumps(state))
"""


@mcp.tool()
def get_ui_state(ctx: Context, timeout: float = 10.0) -> str:
    """Is Rhino ready for commands — or blocked by a dialog/running command?

    Run this when a tool times out or behaves oddly. An invisible **modal
    dialog** (first-run options, license prompts, save confirmations) or a
    long-running command silently blocks every mutating call — a remote
    agent cannot see it, but this probe can.

    Returns:
        {"success": true, "data": {
            "busy": false,
            "modal_dialog_open": false,    // main window disabled = modal up
            "in_command": 0,               // active Rhino command depth
            "command_stack": [],
            "command_prompt": "Command",
            "diagnosis": "ready"}}

    When the probe itself times out, the answer is still diagnostic:
    `busy: true` with diagnosis "UI thread blocked" — a script/command is
    hogging the UI thread; check the Rhino screen.
    """
    try:
        rhino = get_rhino_connection()
        try:
            raw = rhino.send_command("execute_rhinoscript_python_code",
                                     {"code": _PROBE}, timeout=timeout)
        except Exception as probe_error:
            # No answer IS an answer: the UI thread can't service us.
            return json.dumps(ok(
                message="Rhino UI thread is NOT responding — busy",
                data={
                    "busy": True,
                    "modal_dialog_open": None,
                    "in_command": None,
                    "command_stack": [],
                    "command_prompt": None,
                    "diagnosis": (
                        "UI thread blocked (long-running command or script). "
                        "Check the Rhino screen; if a prompt is waiting, see "
                        f"get_command_history. ({probe_error})"
                    ),
                },
            ))

        text = raw if isinstance(raw, str) else (raw or {}).get("result", "")
        if isinstance(text, str) and text.startswith(_PRINT_PREFIX):
            text = text[len(_PRINT_PREFIX):]
        state: Dict[str, Any] = json.loads(
            str(text).split("STATE:", 1)[1].strip().splitlines()[0])

        modal = (state.get("main_window_enabled") is False)
        in_command = state.get("in_command") or 0
        prompt = (state.get("prompt") or "").strip()
        waiting_for_input = prompt not in ("", "Command")

        diagnosis = []
        if modal:
            diagnosis.append(
                "A MODAL DIALOG is open (main window disabled) — it blocks "
                "saves/exports until someone closes it on the Rhino screen.")
        if in_command > 0:
            stack = state.get("command_stack") or []
            diagnosis.append(
                f"A command is running ({', '.join(stack) or 'unknown'}).")
        if waiting_for_input and not modal:
            diagnosis.append(
                f"The command line is waiting for input: '{prompt}' — feed "
                "it via SendKeystrokes or cancel_rhino_command.")

        busy = modal or in_command > 0 or waiting_for_input
        return json.dumps(ok(
            message="Rhino busy: " + ("; ".join(diagnosis) or "—")
                    if busy else "Rhino ready",
            data={
                "busy": busy,
                "modal_dialog_open": modal if state.get(
                    "main_window_enabled") is not None else None,
                "in_command": in_command,
                "command_stack": state.get("command_stack") or [],
                "command_prompt": prompt,
                "diagnosis": " ".join(diagnosis) or "ready",
            },
        ))
    except Exception as e:
        logger.error(f"Error probing UI state: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def wait_until_ready(
    ctx: Context,
    timeout: float = 60.0,
    poll_interval: float = 2.0,
) -> str:
    """Wait until Rhino can accept commands again — instead of retrying blind.

    Polls `get_ui_state` until Rhino is neither running a command, nor
    waiting at a prompt, nor blocked by a modal dialog. Use it after
    starting long operations (GrasshopperPlayer, renders) or before a
    batch of mutating calls.

    Returns:
        ready:   {"success": true, "data": {"ready": true,
                  "waited_seconds": 4.1, "polls": 3}}
        timeout: {"success": true, "data": {"ready": false,
                  "waited_seconds": 60.0, "polls": 30,
                  "last_state": {...}, "hint": "..."}}

    A `ready: false` result includes the last probe state — if
    `modal_dialog_open` is true, no amount of waiting helps: the dialog
    must be closed on the Rhino screen.
    """
    start = time.monotonic()
    polls = 0
    last_data: Dict[str, Any] = {}
    while True:
        polls += 1
        last_data = json.loads(get_ui_state(ctx)).get("data", {})
        if not last_data.get("busy"):
            return json.dumps(ok(
                message=f"Rhino ready after {polls} poll(s)",
                data={"ready": True,
                      "waited_seconds": round(time.monotonic() - start, 1),
                      "polls": polls},
            ))
        if time.monotonic() - start >= timeout:
            hint = ("A modal dialog is open — close it on the Rhino screen; "
                    "waiting longer will not help."
                    if last_data.get("modal_dialog_open")
                    else "Still busy — consider cancel_rhino_command or a "
                         "longer timeout.")
            return json.dumps(ok(
                message=f"Rhino still busy after {round(timeout, 1)}s",
                data={"ready": False,
                      "waited_seconds": round(time.monotonic() - start, 1),
                      "polls": polls, "last_state": last_data, "hint": hint},
            ))
        time.sleep(poll_interval)
