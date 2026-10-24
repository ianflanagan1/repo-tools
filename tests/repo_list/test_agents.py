"""Behaviour of telling whether a Claude Code session is working in a directory."""

import json
import os
from pathlib import Path

from repo_list.agents import Session, sessions, working


def test_a_busy_session_whose_process_is_running_is_working():
    assert working([Session("a", busy=True, alive=True)], own=None)


def test_an_idle_session_is_not_working():
    assert not working([Session("a", busy=False, alive=True)], own=None)


def test_a_busy_session_whose_process_has_gone_is_not_working():
    assert not working([Session("a", busy=True, alive=False)], own=None)


def test_the_session_running_the_command_itself_is_not_counted():
    assert not working([Session("me", busy=True, alive=True)], own="me")
    assert working([Session("me", busy=True, alive=True), Session("b", True, True)], own="me")


def write(git_dir: Path, name: str, state: object) -> None:
    directory = git_dir / "claude-sessions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps(state))


def test_the_sessions_are_read_from_their_files_in_the_git_directory(tmp_path: Path):
    write(tmp_path, "s1", {"pid": os.getpid(), "state": "busy"})
    write(tmp_path, "s2", {"pid": 2**22 + 12345, "state": "idle"})
    assert sessions(tmp_path) == [Session("s1", True, True), Session("s2", False, False)]


def test_a_file_without_a_pid_counts_as_running(tmp_path: Path):
    write(tmp_path, "s1", {"state": "busy"})
    assert sessions(tmp_path) == [Session("s1", True, True)]


def test_a_file_that_is_not_a_session_is_skipped(tmp_path: Path):
    write(tmp_path, "bad", ["not", "a", "session"])
    (tmp_path / "claude-sessions" / "garbled.json").write_text("{")
    assert sessions(tmp_path) == []


def test_a_git_directory_without_sessions_has_none(tmp_path: Path):
    assert sessions(tmp_path) == []
