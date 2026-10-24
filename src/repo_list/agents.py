"""Whether a Claude Code session is working in a directory, from the files the worktree-hooks
plugin keeps in its git directory: one per session open there, saying whether it's busy with a
prompt or idle.

A file whose session's process has gone, as after a crash, is ignored, as is the session that
runs repo-list or repo-fix itself.
"""

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import final

# COUPLED:claude-sessions. = worktree-hooks:scripts/agent_activity.py SESSIONS and its JSON fields
SESSIONS = "claude-sessions"
BUSY = "busy"
OWN_SESSION = "CLAUDE_CODE_SESSION_ID"


@final
@dataclass(frozen=True)
class Session:
    id: str
    busy: bool
    alive: bool
    """Whether its Claude Code process is still running."""


def working(sessions: Sequence[Session], own: str | None) -> bool:
    """Whether any session but own, the one running this, is busy and still running."""
    return any(s.busy and s.alive and s.id != own for s in sessions)


def sessions(git_dir: Path) -> list[Session]:
    """The sessions the worktree-hooks plugin records in git_dir. A file that can't be read as
    one is skipped."""
    found = []
    for file in sorted((git_dir / SESSIONS).glob("*.json")):
        try:
            state = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(state, dict):
            continue
        pid = state.get("pid")
        alive = _running(pid) if isinstance(pid, int) else True
        found.append(Session(file.stem, state.get("state") == BUSY, alive))
    return found


def own_session() -> str | None:
    """The session running this command, when Claude Code runs it."""
    return os.environ.get(OWN_SESSION)


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
