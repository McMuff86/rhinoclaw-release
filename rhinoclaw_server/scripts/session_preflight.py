#!/usr/bin/env python3
"""Real stdio MCP preflight/fallback. Requires Python 3.11+ and project dependencies.

Read the caller-selected TOML mcp_servers entry, initialize once, list schemas,
then call doctor/capabilities through MCP. No TCP-name guessing or auto-retry.
Use a fresh --output directory under a writable workspace. Optional --call
executes exactly one explicitly requested tool after successful preflight.
"""
import argparse
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def decode(result):
    values = []
    for content in result.content:
        if content.type == "text":
            try:
                values.append(json.loads(content.text))
            except ValueError:
                values.append(content.text)
    return values


def passed(result):
    if result.isError:
        return False
    for value in decode(result):
        if isinstance(value, dict):
            if value.get("success") is False:
                return False
            data = value.get("data")
            if isinstance(data, dict) and data.get("ready") is False:
                return False
    return True


def launch_settings(config, name, output):
    data = tomllib.loads(config.read_text(encoding="utf-8-sig"))
    entry = data.get("mcp_servers", {}).get(name)
    if not isinstance(entry, dict) or not entry.get("command") or entry.get("enabled") is False:
        raise ValueError("Selected stdio MCP server is missing, disabled or has no command")
    env = dict(os.environ)
    env.update({key: str(value) for key, value in entry.get("env", {}).items()})
    # Explicit writable directories avoid accidental source-repo logs and a
    # locked global uv cache. The config's command/arguments remain unchanged.
    for key, folder in (("UV_CACHE_DIR", "uv-cache"), ("RHINOCLAW_LOG_DIR", "logs")):
        path = output / folder
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        with probe.open("x", encoding="utf-8") as stream:
            stream.write("ok")
        probe.unlink()
        env[key] = str(path)
    env["PYTHONUTF8"] = "1"
    return StdioServerParameters(command=entry["command"], args=entry.get("args", []),
                                 env=env, cwd=entry.get("cwd"))


async def list_all_tools(session):
    found, cursor, seen = [], None, set()
    while True:
        page = await session.list_tools(cursor=cursor)
        found.extend(page.tools)
        cursor = page.nextCursor
        if not cursor:
            return found
        if cursor in seen:
            raise RuntimeError("MCP tools/list repeated its cursor")
        seen.add(cursor)


async def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"configuration": "pending", "mcp_startup": "not_attempted",
              "client_tool_exposure": args.client_tools,
              "client_exposure_cause": "not established by this fallback",
              "output": str(output), "calls": []}
    secrets = []

    def safe_json(value):
        text = json.dumps(value, ensure_ascii=True, indent=2)
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]").replace(json.dumps(secret)[1:-1], "[REDACTED]")
        return text

    def write(name, value):
        (output / name).write_text(safe_json(value), encoding="utf-8")

    try:
        params = launch_settings(args.config, args.server, output)
        secrets.extend(value for key, value in (params.env or {}).items()
                       if any(part in key.upper() for part in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")))
        report["configuration"] = "registered_stdio"
        report["mcp_startup"] = "initializing"
        # Keep server stderr off stdout and out of persistent evidence: a
        # third-party entry may emit credentials or echo its environment.
        with open(os.devnull, "w", encoding="utf-8") as err:
            async with stdio_client(params, errlog=err) as streams:
                async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=args.timeout)) as session:
                    initialized = await asyncio.wait_for(session.initialize(), args.timeout)
                    report["mcp_startup"] = "initialized"
                    write("initialize.json", initialized.model_dump(mode="json"))
                    schemas = await asyncio.wait_for(list_all_tools(session), args.timeout)
                    write("mcp_tools.json", [tool.model_dump(mode="json") for tool in schemas])
                    names = {tool.name for tool in schemas}
                    report["mcp_tool_count"] = len(names)

                    async def call(name, arguments):
                        if name not in names:
                            raise ValueError("MCP tool absent from this server: " + name)
                        result = await session.call_tool(name, arguments)
                        write(f"{len(report['calls']):02d}_{name}.json",
                              {"request": {"tool": name, "arguments": arguments}, "response": result.model_dump(mode="json")})
                        report["calls"].append({"tool": name, "pass": passed(result)})
                        return result

                    doctor = await call("rhinoclaw_doctor", {})
                    report["doctor"] = decode(doctor)
                    if not passed(doctor):
                        report["recovery"] = "Apply the failed doctor's diagnosis; no retries or mutations were sent."
                        return 2
                    for tool in ("list_capabilities", "get_session_inventory"):
                        if tool not in names:
                            report[tool] = "unavailable_on_running_server"
                            continue
                        if not passed(await call(tool, {})):
                            return 2
                    if args.call:
                        arguments = json.loads(args.arguments_file.read_text(encoding="utf-8-sig")) if args.arguments_file else {}
                        result = await call(args.call, arguments)
                        if not passed(result):
                            report["recovery"] = "Read current state/artifacts before retrying a failed call."
                            return 2
                    return 0
    except Exception as exc:
        # Keep the phase separate from the underlying failure. Initializing
        # cannot establish a TCP or a client-tool-exposure diagnosis.
        report["failure_type"] = type(exc).__name__
        report["failure"] = str(exc)
        report["recovery"] = "Check the selected config, executable, dependencies and writable cache; no automatic restart."
        return 2
    finally:
        write("preflight.json", report)
        print(safe_json(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--server", default="rhinoclaw")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--client-tools", choices=("available", "unavailable", "unknown"), default="unknown")
    parser.add_argument("--call")
    parser.add_argument("--arguments-file", type=Path)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300 or (args.arguments_file and not args.call):
        parser.error("timeout must be 1..300 seconds; --arguments-file requires --call")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
