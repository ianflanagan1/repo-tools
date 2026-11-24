"""The commands that read a git host's delivery data, and give a repo's URL, written once against
GitHostApi and listed by each git host's tool, so `github deployments` and `bitbucket deployments`
behave alike.

    url <repo>                                         the SSH URL git reaches it at
    environments <repo>                                the repo's deployment environments
    deployments <repo> <environment> [--since <date>]  its deployments there, newest first
    merged <repo> [--base <branch>] [--since <date>]   its merged pull requests, newest first
    commits <repo> <base> <head>                       the commits in head and not in base

Each prints one JSON object per line, then its status line, so `grep '^{'` keeps only the data.
Nothing is stored: each run asks the git host afresh, but for url, which is made from the name
alone.
--since is a date, 2026-07-01, or a time, 2026-07-01T09:00+01:00, in UTC unless it gives its
offset; it's 30 days ago unless given.
"""

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from cli_kit import cli
from cli_kit.outcome import NothingToDo

from repo_tools.git_host_api import GitHostApi

DEFAULT_DAYS = 30


@dataclass(frozen=True)
class Command:
    """A command module's shape, as cli.run takes it, for a command made for one git host."""

    register: Callable[[cli.Subparsers], None]


def commands(git_host: Callable[[], GitHostApi]) -> list[Command]:
    """The url and delivery commands for the git host's API that git_host makes. It's called only
    when one runs."""
    return [
        Command(lambda subparsers: _url(subparsers, git_host)),
        Command(lambda subparsers: _environments(subparsers, git_host)),
        Command(lambda subparsers: _deployments(subparsers, git_host)),
        Command(lambda subparsers: _merged(subparsers, git_host)),
        Command(lambda subparsers: _commits(subparsers, git_host)),
    ]


def _url(subparsers: cli.Subparsers, git_host: Callable[[], GitHostApi]) -> None:
    parser = subparsers.add_parser(
        "url",
        help="print the SSH URL git reaches the repo at",
        description="Prints the repo's full name and the SSH URL git reaches it at, the one"
        " publish adds as origin, as one JSON object. A bare name is in the default owner: on"
        " GitHub the account gh is logged in as. The URL is made from the name alone, so the repo"
        " needn't exist yet.",
    )
    parser.add_argument("repo", help="owner/name, or a bare name in the default owner")
    parser.set_defaults(run=lambda args: url(git_host(), args.repo))


def _environments(subparsers: cli.Subparsers, git_host: Callable[[], GitHostApi]) -> None:
    parser = subparsers.add_parser(
        "environments",
        help="list the repo's deployment environments",
        description="Lists the repo's deployment environments, one JSON object per line.",
    )
    parser.add_argument("repo", help="owner/name, or a bare name in the default owner")
    parser.set_defaults(run=lambda args: environments(git_host(), args.repo))


def _deployments(subparsers: cli.Subparsers, git_host: Callable[[], GitHostApi]) -> None:
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
        run=lambda args: deployments(git_host(), args.repo, args.environment, args.since)
    )


def _merged(subparsers: cli.Subparsers, git_host: Callable[[], GitHostApi]) -> None:
    parser = subparsers.add_parser(
        "merged",
        help="list the pull requests merged since a date, newest first",
        description="Lists the pull requests merged since a date, newest first, one JSON object"
        " per line, each with when it opened and merged and the commit it merged as.",
    )
    parser.add_argument("repo", help="owner/name, or a bare name in the default owner")
    parser.add_argument("--base", help="only those merged into this branch")
    _since(parser)
    parser.set_defaults(run=lambda args: merged(git_host(), args.repo, args.since, args.base))


def _commits(subparsers: cli.Subparsers, git_host: Callable[[], GitHostApi]) -> None:
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
    parser.set_defaults(run=lambda args: commits(git_host(), args.repo, args.base, args.head))


def url(git_host: GitHostApi, name: str) -> NothingToDo:
    repo = git_host.full_name(name)
    at = git_host.url(repo)
    _print([{"repo": repo, "url": at}])
    return NothingToDo(f"{repo} is at {at}.")


def environments(git_host: GitHostApi, name: str) -> NothingToDo:
    repo = git_host.full_name(name)
    found = git_host.environments(repo)
    _print({"name": environment} for environment in found)
    return NothingToDo(f"{repo} has {_count(found, 'environment')}.")


def deployments(
    git_host: GitHostApi, name: str, environment: str, since: datetime | None
) -> NothingToDo:
    repo, since = git_host.full_name(name), since or _default_since()
    found = git_host.deployments(repo, environment, since)
    _print(asdict(deployment) for deployment in found)
    return NothingToDo(
        f"{_count(found, 'deployment')} of {repo} to {environment} since {_day(since)}."
    )


def merged(
    git_host: GitHostApi, name: str, since: datetime | None, base: str | None
) -> NothingToDo:
    repo, since = git_host.full_name(name), since or _default_since()
    found = git_host.merged_pull_requests(repo, since, base)
    _print(asdict(pull) for pull in found)
    into = f" into {base}" if base else ""
    return NothingToDo(
        f"{_count(found, 'pull request')} of {repo} merged{into} since {_day(since)}."
    )


def commits(git_host: GitHostApi, name: str, base: str, head: str) -> NothingToDo:
    repo = git_host.full_name(name)
    found = git_host.commits_between(repo, base, head)
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
