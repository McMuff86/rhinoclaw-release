"""External toolbox kits: discover ``rhinoclaw-kit.json`` and prepare invoke.

The MCP tools ``kit_list`` / ``kit_describe`` / ``kit_invoke`` sit on top of
this module. Discovery is filesystem-only (no live Rhino). Invocation builds
a Python-3 snippet that Rhino runs through ``execute_python3_code``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from rhinoclaw.config import get_settings
from rhinoclaw.utils.part_library import wsl_to_windows_path

SCHEMA = "rhinoclaw-kit/1"
KIT_FILENAME = "rhinoclaw-kit.json"
INVOKE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESULT_PREFIX = "RHINOCLAW_KIT_RESULT:"
CALLABLE = "callable"
INTERACTIVE_ONLY = "interactive_only"
ALLOWED_STATUS = {CALLABLE, INTERACTIVE_ONLY}


class KitError(Exception):
    """Invalid manifest, missing kit, or unsafe invoke request."""


@dataclass(frozen=True)
class KitAction:
    name: str
    status: str
    summary: str = ""
    when: str = ""
    alias: Optional[str] = None
    entry: Optional[str] = None
    invoke: Optional[str] = None
    engine: Optional[str] = None
    rhino: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_schema: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "when": self.when,
            "alias": self.alias,
            "entry": self.entry,
            "invoke": self.invoke,
            "engine": self.engine,
            "rhino": list(self.rhino),
            "requires": list(self.requires),
            "side_effects": list(self.side_effects),
        }
        if include_schema:
            data["input_schema"] = self.input_schema
        return data


@dataclass(frozen=True)
class KitManifest:
    id: str
    title: str
    root: Path
    path: Path
    version: str = "0"
    engine: str = "python3"
    rhino: tuple[str, ...] = ()
    summary: str = ""
    docs: Optional[str] = None
    actions: tuple[KitAction, ...] = ()
    warnings: tuple[str, ...] = ()

    def action(self, name: str) -> KitAction:
        for item in self.actions:
            if item.name == name:
                return item
        raise KitError(f"Unknown action '{name}' in kit '{self.id}'.")

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "version": self.version,
            "root": str(self.root),
            "summary": self.summary,
            "engine": self.engine,
            "rhino": list(self.rhino),
            "actions": [
                {
                    "name": action.name,
                    "alias": action.alias,
                    "status": action.status,
                    "summary": action.summary,
                }
                for action in self.actions
            ],
            "warnings": list(self.warnings),
        }

    def to_detail(self) -> dict[str, Any]:
        data = self.to_summary()
        data["docs"] = self.docs
        data["path"] = str(self.path)
        data["actions"] = [action.to_dict() for action in self.actions]
        return data


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KitError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise KitError(f"{path} must contain a JSON object.")
    return raw


def _parse_action(raw: Any, index: int) -> KitAction:
    if not isinstance(raw, dict):
        raise KitError(f"actions[{index}] must be an object.")
    name = str(raw.get("name") or "").strip()
    if not name or not INVOKE_RE.match(name):
        raise KitError(f"actions[{index}].name is missing or not an identifier.")
    status = str(raw.get("status") or CALLABLE).strip()
    if status not in ALLOWED_STATUS:
        raise KitError(f"action '{name}': status must be {CALLABLE} or {INTERACTIVE_ONLY}.")
    invoke = raw.get("invoke")
    invoke_name = str(invoke).strip() if invoke else None
    if status == CALLABLE:
        if not invoke_name or not INVOKE_RE.match(invoke_name):
            raise KitError(f"action '{name}': callable actions need invoke as an identifier.")
        if not raw.get("entry"):
            raise KitError(f"action '{name}': callable actions need entry.")
    schema = raw.get("input_schema") or {}
    if schema and not isinstance(schema, dict):
        raise KitError(f"action '{name}': input_schema must be an object.")
    return KitAction(
        name=name,
        status=status,
        summary=str(raw.get("summary") or ""),
        when=str(raw.get("when") or ""),
        alias=str(raw["alias"]) if raw.get("alias") else None,
        entry=str(raw["entry"]) if raw.get("entry") else None,
        invoke=invoke_name,
        engine=str(raw["engine"]) if raw.get("engine") else None,
        rhino=_as_str_tuple(raw.get("rhino")),
        requires=_as_str_tuple(raw.get("requires")),
        side_effects=_as_str_tuple(raw.get("side_effects")),
        input_schema=schema if isinstance(schema, dict) else {},
    )


def load_manifest(path: Path) -> KitManifest:
    """Parse and validate a ``rhinoclaw-kit.json`` file."""
    path = path.resolve()
    raw = _load_json(path)
    schema = str(raw.get("schema") or "")
    if schema != SCHEMA:
        raise KitError(f"{path}: unsupported schema '{schema}' (expected {SCHEMA}).")
    kit_id = str(raw.get("id") or "").strip()
    if not kit_id or not INVOKE_RE.match(kit_id):
        raise KitError(f"{path}: id is missing or not an identifier.")
    title = str(raw.get("title") or kit_id)
    actions_raw = raw.get("actions")
    if not isinstance(actions_raw, list) or not actions_raw:
        raise KitError(f"{path}: actions must be a non-empty array.")
    actions = tuple(_parse_action(item, i) for i, item in enumerate(actions_raw))
    names = [action.name for action in actions]
    if len(names) != len(set(names)):
        raise KitError(f"{path}: duplicate action names.")
    return KitManifest(
        id=kit_id,
        title=title,
        root=path.parent,
        path=path,
        version=str(raw.get("version") or "0"),
        engine=str(raw.get("engine") or "python3"),
        rhino=_as_str_tuple(raw.get("rhino")),
        summary=str(raw.get("summary") or ""),
        docs=str(raw["docs"]) if raw.get("docs") else None,
        actions=actions,
    )


def resolve_entry(kit: KitManifest, action: KitAction) -> Path:
    if not action.entry:
        raise KitError(f"action '{action.name}' has no entry.")
    rel = Path(action.entry)
    if rel.is_absolute() or ".." in rel.parts:
        raise KitError(f"action '{action.name}': entry must be a relative path inside the kit.")
    path = (kit.root / rel).resolve()
    try:
        path.relative_to(kit.root.resolve())
    except ValueError as exc:
        raise KitError(f"action '{action.name}': entry escapes the kit root.") from exc
    if not path.is_file():
        raise KitError(f"action '{action.name}': entry file not found: {path}")
    return path


def _unique_existing(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def default_scan_roots() -> list[Path]:
    """Heuristic roots used when ``RHINOCLAW_KITS`` is unset."""
    home = Path.home()
    cwd = Path.cwd()
    return _unique_existing(
        [
            cwd,
            cwd.parent,
            home / "repos",
            home / "source" / "repos",
        ]
    )


def search_locations() -> list[Path]:
    """Directories that may be kit roots or one-level scan folders."""
    settings = get_settings()
    explicit = list(settings.kit_paths)
    if explicit:
        locations = list(explicit)
    else:
        locations = default_scan_roots()
    if settings.kits_root is not None:
        locations.append(settings.kits_root)
    return _unique_existing(locations)


def _candidate_manifests(location: Path) -> list[Path]:
    direct = location / KIT_FILENAME if location.is_dir() else location
    found: list[Path] = []
    if direct.is_file() and direct.name == KIT_FILENAME:
        found.append(direct)
        return found
    if location.is_file() and location.name == KIT_FILENAME:
        found.append(location)
        return found
    if not location.is_dir():
        return found
    if (location / KIT_FILENAME).is_file():
        found.append(location / KIT_FILENAME)
        return found
    try:
        children = sorted(location.iterdir())
    except OSError:
        return found
    for child in children:
        manifest = child / KIT_FILENAME
        if child.is_dir() and manifest.is_file():
            found.append(manifest)
    return found


def discover_kits() -> tuple[list[KitManifest], list[dict[str, str]]]:
    """Load every kit on the search path. Invalid files become warnings."""
    by_id: dict[str, KitManifest] = {}
    errors: list[dict[str, str]] = []
    for location in search_locations():
        for manifest_path in _candidate_manifests(location):
            try:
                kit = load_manifest(manifest_path)
            except KitError as exc:
                errors.append({"path": str(manifest_path), "error": str(exc)})
                continue
            existing = by_id.get(kit.id)
            if existing is not None and existing.path != kit.path:
                errors.append({
                    "path": str(manifest_path),
                    "error": f"duplicate kit id '{kit.id}' (already {existing.path})",
                })
                continue
            by_id[kit.id] = kit
    return list(by_id.values()), errors


def find_kit(kit_id: str) -> KitManifest:
    kits, errors = discover_kits()
    for kit in kits:
        if kit.id == kit_id:
            return kit
    hint = f" Known ids: {', '.join(k.id for k in kits)}." if kits else ""
    extra = f" Load errors: {errors}" if errors else ""
    raise KitError(f"Kit '{kit_id}' not found.{hint}{extra}")


def build_invoke_source(entry: Path, invoke: str, args: dict[str, Any]) -> str:
    """Python 3 snippet that loads ``entry`` and calls ``invoke(**args)``."""
    if not INVOKE_RE.match(invoke):
        raise KitError(f"invoke '{invoke}' is not a valid identifier.")
    payload = {
        "entry": wsl_to_windows_path(str(entry)),
        "invoke": invoke,
        "args": args,
    }
    blob = json.dumps(payload, ensure_ascii=True)
    return (
        "# rhinoclaw-kit invoke\n"
        "import importlib.util\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        f"_payload = json.loads({json.dumps(blob)})\n"
        "entry = _payload['entry']\n"
        "entry_dir = os.path.dirname(entry)\n"
        "if entry_dir not in sys.path:\n"
        "    sys.path.insert(0, entry_dir)\n"
        "invoke = _payload['invoke']\n"
        "args = _payload['args']\n"
        "spec = importlib.util.spec_from_file_location('rhinoclaw_kit_action', entry)\n"
        "if spec is None or spec.loader is None:\n"
        "    raise RuntimeError('cannot load ' + entry)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "fn = getattr(mod, invoke)\n"
        "result = fn(**args)\n"
        "if not isinstance(result, dict):\n"
        "    result = {'ok': True, 'result': result}\n"
        f"print({json.dumps(RESULT_PREFIX)} + json.dumps(result, ensure_ascii=True, default=str))\n"
    )


def parse_invoke_output(output: str) -> dict[str, Any]:
    """Extract the JSON object printed after ``RHINOCLAW_KIT_RESULT:``."""
    text = output or ""
    idx = text.rfind(RESULT_PREFIX)
    if idx < 0:
        raise KitError("Kit action produced no RHINOCLAW_KIT_RESULT line.")
    payload = text[idx + len(RESULT_PREFIX):].strip()
    first_line = payload.splitlines()[0] if payload else ""
    try:
        data = json.loads(first_line)
    except json.JSONDecodeError as exc:
        raise KitError(f"Kit result is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise KitError("Kit result must be a JSON object.")
    return data
