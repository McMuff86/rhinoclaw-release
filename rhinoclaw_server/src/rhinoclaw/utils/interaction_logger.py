"""
Interaction Logger for RhinoClaw.

Logs all MCP tool calls to JSONL files for:
- Workflow analysis
- Error pattern detection  
- Future ML training data

Usage:
    from rhinoclaw.utils.interaction_logger import interaction_logger
    
    # Log a tool call
    interaction_logger.log_tool_call(
        tool_name="create_object",
        tool_args={"type": "BOX", "params": {...}},
        success=True,
        response_summary={"id": "guid-here", "name": "Box_1"}
    )
"""
import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("RhinoClawServer")


@dataclass
class InteractionRecord:
    """Single interaction log record."""
    timestamp: str
    session_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    success: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    response_summary: Optional[Dict[str, Any]] = None
    duration_ms: Optional[float] = None
    client_model: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


class InteractionLogger:
    """
    Thread-safe JSONL logger for MCP interactions.
    
    Writes to: logs/interactions_YYYYMMDD.jsonl
    """
    
    def __init__(self, log_dir: Optional[str] = None, enabled: bool = True):
        self._enabled = enabled
        self._session_id = str(uuid.uuid4())[:8]
        self._lock = threading.Lock()
        self._client_model: Optional[str] = None
        
        # Default log directory: rhinoclaw_server/logs/
        if log_dir is None:
            # Path: utils/interaction_logger.py -> utils -> rhinoclaw -> src -> rhinoclaw_server
            # __file__ = .../src/rhinoclaw/utils/interaction_logger.py
            # parent = .../src/rhinoclaw/utils
            # parent.parent = .../src/rhinoclaw  
            # parent.parent.parent = .../src
            # parent.parent.parent.parent = .../rhinoclaw_server
            server_root = Path(__file__).parent.parent.parent.parent
            self._log_dir = server_root / "logs"
        else:
            self._log_dir = Path(log_dir)
        
        # Create logs directory if it doesn't exist
        if self._enabled:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Interaction logging enabled. Session: {self._session_id}, Dir: {self._log_dir}")
    
    @property
    def session_id(self) -> str:
        """Current session ID."""
        return self._session_id
    
    @property
    def enabled(self) -> bool:
        """Whether logging is enabled."""
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable logging."""
        self._enabled = value
        if value:
            self._log_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Interaction logging {'enabled' if value else 'disabled'}")
    
    def set_client_model(self, model: str):
        """Set the client model name (e.g., 'claude-3.5-sonnet', 'gpt-4')."""
        self._client_model = model
        logger.debug(f"Client model set to: {model}")
    
    def new_session(self) -> str:
        """Start a new session and return the session ID."""
        self._session_id = str(uuid.uuid4())[:8]
        logger.info(f"New interaction session: {self._session_id}")
        return self._session_id
    
    def _get_log_file_path(self) -> Path:
        """Get the log file path for today."""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        return self._log_dir / f"interactions_{date_str}.jsonl"
    
    def log_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        success: bool,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        response_summary: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        """
        Log a tool call interaction.
        
        Args:
            tool_name: Name of the MCP tool called
            tool_args: Arguments passed to the tool
            success: Whether the tool call succeeded
            error_code: Error code if failed (from ErrorCode)
            error_message: Error message if failed
            response_summary: Summary of successful response (e.g., {"id": "...", "count": 5})
            duration_ms: Execution time in milliseconds
        """
        if not self._enabled:
            return
        
        record = InteractionRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self._session_id,
            tool_name=tool_name,
            tool_args=self._sanitize_args(tool_args),
            success=success,
            error_code=error_code,
            error_message=error_message,
            response_summary=response_summary,
            duration_ms=duration_ms,
            client_model=self._client_model,
        )
        
        self._write_record(record)
    
    def _sanitize_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize arguments for logging.
        
        - Truncates very long lists (e.g., point arrays)
        - Removes sensitive data if needed
        """
        if args is None:
            return {}
        
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, list) and len(value) > 20:
                # Truncate long lists, keep first/last few
                sanitized[key] = {
                    "_truncated": True,
                    "length": len(value),
                    "first_3": value[:3],
                    "last_3": value[-3:],
                }
            elif isinstance(value, str) and len(value) > 1000:
                # Truncate very long strings (e.g., code)
                sanitized[key] = {
                    "_truncated": True,
                    "length": len(value),
                    "preview": value[:200] + "...",
                }
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _write_record(self, record: InteractionRecord) -> None:
        """Thread-safe write to JSONL file."""
        try:
            with self._lock:
                log_path = self._get_log_file_path()
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            # Don't let logging errors break the main functionality
            logger.warning(f"Failed to write interaction log: {e}")
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics for the current session (reads from today's log)."""
        if not self._enabled:
            return {"enabled": False}
        
        log_path = self._get_log_file_path()
        if not log_path.exists():
            return {
                "session_id": self._session_id,
                "total_calls": 0,
                "success_count": 0,
                "error_count": 0,
            }
        
        total = 0
        success = 0
        errors = 0
        tool_counts: Dict[str, int] = {}
        
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        if record.get("session_id") == self._session_id:
                            total += 1
                            if record.get("success"):
                                success += 1
                            else:
                                errors += 1
                            
                            tool_name = record.get("tool_name", "unknown")
                            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Error reading log stats: {e}")
        
        return {
            "session_id": self._session_id,
            "total_calls": total,
            "success_count": success,
            "error_count": errors,
            "success_rate": round(success / total * 100, 1) if total > 0 else 0,
            "tool_counts": tool_counts,
        }


# Global singleton instance
interaction_logger = InteractionLogger()


def log_tool_call(
    tool_name: str,
    tool_args: Dict[str, Any],
    success: bool,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    response_summary: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[float] = None,
) -> None:
    """Convenience function to log via the global logger."""
    interaction_logger.log_tool_call(
        tool_name=tool_name,
        tool_args=tool_args,
        success=success,
        error_code=error_code,
        error_message=error_message,
        response_summary=response_summary,
        duration_ms=duration_ms,
    )
