"""The commands that read a code host's delivery data, written once against Forge and listed by
each host's tool, so `github deployments` and `bitbucket deployments` behave alike.

    environments <repo>                                the repo's deployment environments
    deployments <repo> <environment> [--since <date>]  its deployments there, newest first
    merged <repo> [--base <branch>] [--since <date>]   its merged pull requests, newest first
    commits <repo> <base> <head>                       the commits in head and not in base

Each prints one JSON object per line, then its status line, so `grep '^{'` keeps only the data.
Nothing is stored: each run asks the host afresh. --since is a date, 2026-07-01, or a time,
2026-07-01T09:00+01:00, in UTC unless it gives its offset; it's 30 days ago unless given.
"""

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from cli_kit import cli
from cli_kit.outcome import NothingToDo

from repo_tools.forge import Forge

DEFAULT_DAYS = 30


@dataclass(frozen=True)
class Command:
    """A command module's shape, as cli.run takes it, for a command made for one host."""

    register: Callable[[cli.Subparsers], None]


def commands(forge: Callable[[], Forge]) -> list[Command]:
    """The delivery commands for the host forge makes. It's called only when one runs."""
    return [
        Command(lambda subparsers: _environments(subparsers, forge)),
        Command(lambda subparsers: _deployments(subparsers, forge)),
        Command(lambda subparsers: _merged(subparsers, forge)),
        Command(lambda subparsers: _commits(subparsers, forge)),
    ]


def _environments(subparsers: cli.Subparsers, forge: Callable[[], Forge]) -> None:
    parser = subparsers.add_parser(
        "environments",
        help="list the repo's deployment environments",
        description="Lists the repo's deployment environments, one JSON object per line.",
    )
    parser.add_argument("repo", help="owner/name, or a bare name in the default owner")
    parser.set_defaults(run=lambda args: environments(forge(), args.repo))


def _deployments(subparsers: cli.Subparsers, forge: Callable[[], Forge]) -> None:
    parser = subparsers.add_parser(
        "deployments",
        help="list the deployments to an environment, newest first",
        description="Lists the deployments to an environment, matched ignoring case, started"
        " since a date, newest first, one JSON object per line. Each has its commit, its status"
        " (succeeded, failed, stopped or in_progress) and when it started and finished.",
    )
    parser.add_argument("repo", help="owner/name, or a bare name in the default owner")
    parser.add_argument("environment", help="such as production")
    _since(parser)
    parser.set_defaults(
        run=lambda args: deployments(forge(), args.repo, args.environment, args.since)
    )


def _merged(subparsers: cli.Subparsers, forge: Callable[[], Forge]) -> None:
    parser = subparsers.add_parser(
        "merged",
        help="list the pull requests merged since a date, newest first",
        description="Lists the pull requests merged since a date, newest first, one JSON object"
        " per line, each with when it opened and merged and the commit it merged as.",
    )
    parser.add_argument("repo", help="owner/name, or a bare name in the default owner")
    parser.add_argument("--base", help="only those merged into this branch")
    _since(parser)
    parser.set_defaults(run=lambda args: merged(forge(), args.repo, args.since, args.base))


def _commits(subparsers: cli.Subparsers, forge: Callable[[], Forge]) -> None:
    parser = subparsers.add_parser(
        "commits",
        help="list the commits in head and not in base, newest first",
        description="Lists the commits reachable from head and not from base, as `git log"
        " base..head` does, newest first, one JSON object per line, each with when it was"
        " written. Between two deployments' commits, it's what the later one shipped.",
    )
    parser.add_argument("repo", help="owner/name, or a bare name in the default owner")
    parser.add_argument("base", help="a commit, branch or tag")
    parser.add_argument("head", help="a commit, branch or tag")
    parser.set_defaults(run=lambda args: commits(forge(), args.repo, args.base, args.head))


def environments(forge: Forge, name: str) -> NothingToDo:
    repo = forge.full_name(name)
    found = forge.environments(repo)
    _print({"name": environment} for environment in found)
    return NothingToDo(f"{repo} has {_count(found, 'environment')}.")


def deployments(forge: Forge, name: str, environment: str, since: datetime | None) -> NothingToDo:
    repo, since = forge.full_name(name), since or _default_since()
    found = forge.deployments(repo, environment, since)
    _print(asdict(deployment) for deployment in found)
    return NothingToDo(
        f"{_count(found, 'deployment')} of {repo} to {environment} since {_day(since)}."
    )


def merged(forge: Forge, name: str, since: datetime | None, base: str | None) -> NothingToDo:
    repo, since = forge.full_name(name), since or _default_since()
    found = forge.merged_pull_requests(repo, since, base)
    _print(asdict(pull) for pull in found)
    into = f" into {base}" if base else ""
    return NothingToDo(
        f"{_count(found, 'pull request')} of {repo} merged{into} since {_day(since)}."
    )


def commits(forge: Forge, name: str, base: str, head: str) -> NothingToDo:
    repo = forge.full_name(name)
    found = forge.commits_between(repo, base, head)
    _print(asdict(commit) for commit in found)
    return NothingToDo(f"{_count(found, 'commit')} of {repo} in {head} and not in {base}.")


def parse_since(text: str) -> datetime:
    """A date or time as --since takes it, in UTC unless it gives its offset."""
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} isn't a date, such as 2026-07-01, or a time, such as 2026-07-01T09:00"
        ) from None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC)


def _since(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--since",
        type=parse_since,
        help=f"a date or time, in UTC unless it gives its offset; {DEFAULT_DAYS} days ago unless"
        " given",
    )


def _default_since() -> datetime:
    return datetime.now(UTC) - timedelta(days=DEFAULT_DAYS)


def _print(records) -> None:
    for record in records:
        print(json.dumps(record, default=_json))


def _json(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"{value!r} isn't JSON")


def _count(items: list, noun: str) -> str:
    return f"{len(items)} {noun}{'' if len(items) == 1 else 's'}"


def _day(moment: datetime) -> str:
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        moment.date().isoformat() if moment == midnight else moment.strftime("%Y-%m-%d %H:%M UTC")
    )
