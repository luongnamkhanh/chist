"""Locate Claude Code data directories and chist artifacts."""
from __future__ import annotations
import os
from pathlib import Path


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))


def projects_dir() -> Path:
    return claude_home() / "projects"


def db_path() -> Path:
    return claude_home() / "history.db"


def archive_dir() -> Path:
    return claude_home() / "archive"


def log_path() -> Path:
    return claude_home() / "history-index.log"


def cwd_project_name(cwd: Path | None = None) -> str:
    """Return Claude Code's sanitized cwd format: '/foo/bar' -> '-foo-bar'."""
    p = cwd if cwd is not None else Path.cwd()
    return str(p.resolve()).replace("/", "-")
