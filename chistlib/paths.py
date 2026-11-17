"""Locate Claude Code data directories and chist artifacts."""
from __future__ import annotations
import os
from pathlib import Path


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))


def projects_dir() -> Path:
    return claude_home() / "projects"


def codex_sessions_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"


def codex_sessions_dirs() -> list[Path]:
    if "CODEX_HOME" in os.environ:
        return [Path(os.environ["CODEX_HOME"]) / "sessions"]
    return [
        Path.home() / ".codex" / "sessions",
        Path.home() / ".local" / "share" / "doer-codex" / "sessions",
    ]


def kiro_sessions_dir() -> Path:
    return Path(os.environ.get("KIRO_HOME", Path.home() / ".kiro")) / "sessions"


def agy_home() -> Path:
    return Path(os.environ.get("AGY_HOME", Path.home() / ".gemini" / "antigravity-cli"))


def agy_brain_dir() -> Path:
    return agy_home() / "brain"


def agy_summaries_db_path() -> Path:
    return agy_home() / "conversation_summaries.db"


def db_path() -> Path:
    return claude_home() / "history.db"


def archive_dir() -> Path:
    return claude_home() / "archive"


def log_path() -> Path:
    return claude_home() / "history-index.log"


def cwd_project_name(cwd: Path | None = None) -> str:
    """Return Claude Code's sanitized cwd format: '/foo/bar' -> '-foo-bar'."""
    p = cwd if cwd is not None else Path.cwd()
    return str(p).replace("/", "-")
