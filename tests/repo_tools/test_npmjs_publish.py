"""What npmjs publish reads from package.json before it touches npm or GitHub."""

from pathlib import Path

import pytest
from cli_kit.outcome import Precondition

from repo_tools.npmjs.commands.publish import package_name, publish, repository


def test_reads_the_package_name_from_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "@me/thing"}')
    assert package_name(tmp_path) == "@me/thing"


def test_fails_without_package_json(tmp_path: Path):
    with pytest.raises(Precondition, match="No package.json"):
        package_name(tmp_path)


def test_fails_when_package_json_has_no_name(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"description": "x"}')
    with pytest.raises(Precondition, match="has no name"):
        package_name(tmp_path)


def test_fails_when_package_json_is_not_json(tmp_path: Path):
    (tmp_path / "package.json").write_text("not json")
    with pytest.raises(Precondition, match="not valid JSON"):
        package_name(tmp_path)


def test_a_private_package_is_refused(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "thing", "private": true}')
    with pytest.raises(Precondition, match="private"):
        package_name(tmp_path)


def test_reads_the_github_repo_from_a_repository_object(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"repository": {"type": "git", "url": "git+https://github.com/me/thing.git"}}'
    )
    assert repository(tmp_path) == "me/thing"


def test_reads_the_github_repo_from_a_repository_string(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"repository": "https://github.com/me/thing"}')
    assert repository(tmp_path) == "me/thing"


def test_fails_when_package_json_names_no_repository(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "thing"}')
    with pytest.raises(Precondition, match="names no repository"):
        repository(tmp_path)


def test_fails_for_a_missing_directory(tmp_path: Path):
    with pytest.raises(Precondition, match="No such directory"):
        publish(tmp_path / "missing")
