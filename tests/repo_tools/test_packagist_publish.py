"""The checks packagist publish makes before it touches Packagist or GitHub."""

from pathlib import Path

import pytest
from cli_kit.errors import Precondition

from repo_tools.packagist.commands.publish import package_name, publish


def test_reads_the_package_name_from_composer_json(tmp_path: Path):
    (tmp_path / "composer.json").write_text('{"name": "someone/phpstan-foo"}')
    assert package_name(tmp_path) == "someone/phpstan-foo"


def test_fails_without_composer_json(tmp_path: Path):
    with pytest.raises(Precondition, match="No composer.json"):
        package_name(tmp_path)


def test_fails_when_composer_json_has_no_name(tmp_path: Path):
    (tmp_path / "composer.json").write_text('{"description": "x"}')
    with pytest.raises(Precondition, match="has no name"):
        package_name(tmp_path)


def test_fails_when_composer_json_is_not_json(tmp_path: Path):
    (tmp_path / "composer.json").write_text("not json")
    with pytest.raises(Precondition, match="not valid JSON"):
        package_name(tmp_path)


def test_fails_for_a_missing_directory(tmp_path: Path):
    with pytest.raises(Precondition, match="No such directory"):
        publish(tmp_path / "missing")
