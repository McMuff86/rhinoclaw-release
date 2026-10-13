"""
Runtime configuration for the RhinoClaw MCP server.

All values can be overridden via environment variables prefixed with
``RHINOCLAW_``. Stored as a frozen dataclass so the same instance can be
shared between threads without surprises.

Examples
--------
::

    RHINOCLAW_HOST=192.168.1.20 RHINOCLAW_PORT=1999 uvx rhinoclaw

::

    RHINOCLAW_AUTH_TOKEN=$(openssl rand -hex 16) uvx rhinoclaw

The defaults match the historical behaviour (loopback, port 1999, 15s
timeout, no auth) so existing setups keep working when the variables
are unset.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _default_log_dir() -> Path:
    """Pick a sane per-OS log directory, fall back to a project-local one."""
    explicit = os.environ.get("RHINOCLAW_LOG_DIR")
    if explicit:
        return Path(explicit).expanduser()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "rhinoclaw" / "logs"
    else:
        xdg = os.environ.get("XDG_STATE_HOME")
        if xdg:
            return Path(xdg) / "rhinoclaw" / "logs"
        home = os.environ.get("HOME")
        if home:
            return Path(home) / ".local" / "state" / "rhinoclaw" / "logs"

    # Last-resort fallback: project-local (legacy behaviour).
    return Path(__file__).resolve().parent.parent.parent / "logs"


def _library_dir() -> Optional[Path]:
    """Root of the file-based part library (``RHINOCLAW_LIBRARY_DIR``).

    Expected layout: ``<dir>/catalog.json`` plus ``<dir>/parts/<part_id>/``
    folders each containing ``part.3dm`` + ``part.json``. ``None`` when the
    variable is unset — the library tools then answer with a setup hint
    instead of guessing a path.
    """
    raw = os.environ.get("RHINOCLAW_LIBRARY_DIR")
    if not raw:
        return None
    return Path(raw).expanduser()


def _kit_paths() -> tuple[Path, ...]:
    """Explicit kit roots or scan directories (``RHINOCLAW_KITS``).

    ``os.pathsep``-separated (``;`` on Windows, ``:`` on POSIX). Each entry
    is either a kit root (contains ``rhinoclaw-kit.json``) or a directory
    scanned one level deep.
    """
    raw = os.environ.get("RHINOCLAW_KITS")
    if not raw:
        return ()
    return tuple(Path(part.strip()).expanduser() for part in raw.split(os.pathsep) if part.strip())


def _kits_root() -> Optional[Path]:
    """Optional extra scan root (``RHINOCLAW_KITS_ROOT``), one level deep."""
    raw = os.environ.get("RHINOCLAW_KITS_ROOT")
    if not raw:
        return None
    return Path(raw).expanduser()


def _rahmentuer_root() -> Optional[Path]:
    """Optional complete Rahmentuer script/vendor-asset root."""
    raw = os.environ.get("RHINOCLAW_RAHMENTUER_ROOT")
    if not raw:
        return None
    return Path(raw).expanduser()


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. Access via :func:`get_settings`."""

    host: str
    port: int
    ws_port: int
    timeout_seconds: float
    max_timeout_seconds: float
    debug: bool
    auth_token: Optional[str]
    log_format: str  # "text" or "json"
    log_dir: Path
    library_dir: Optional[Path]
    kit_paths: tuple[Path, ...]
    kits_root: Optional[Path]
    rahmentuer_root: Optional[Path]

    @property
    def auth_required(self) -> bool:
        return bool(self.auth_token)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=_env_str("RHINOCLAW_HOST", "127.0.0.1"),
            port=_env_int("RHINOCLAW_PORT", 1999),
            ws_port=_env_int("RHINOCLAW_WS_PORT", 2000),
            timeout_seconds=_env_float("RHINOCLAW_TIMEOUT", 15.0),
            # Aligned with the plugin's hard cap on its UI-thread wait
            # (300 s) since 0.7.6 — with the old 120 s default, timeouts in
            # (120, 300] that tools like execute_python3_code document for
            # first-time `# r:` pip installs were silently unreachable.
            max_timeout_seconds=_env_float("RHINOCLAW_MAX_TIMEOUT", 300.0),
            debug=_env_bool("RHINOCLAW_DEBUG", False),
            auth_token=os.environ.get("RHINOCLAW_AUTH_TOKEN") or None,
            log_format=_env_str("RHINOCLAW_LOG_FORMAT", "text").lower(),
            log_dir=_default_log_dir(),
            library_dir=_library_dir(),
            kit_paths=_kit_paths(),
            kits_root=_kits_root(),
            rahmentuer_root=_rahmentuer_root(),
        )


_cached: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the process-wide settings, loading from env on first call."""
    global _cached
    if _cached is None:
        _cached = Settings.from_env()
    return _cached


def reload_settings() -> Settings:
    """Force re-read from environment. Useful for tests."""
    global _cached
    _cached = Settings.from_env()
    return _cached
