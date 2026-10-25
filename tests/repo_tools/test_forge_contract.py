"""Every Forge adapter gives the same records for the same history, read from its host's own
answers: GitHub's through faked gh calls, Bitbucket's through a faked API client.

The history is written once, as the records it should come back as, and each host's fake
answers with it in that host's shape.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from cli_kit.outcome import Failure, Precondition

from repo_tools.bitbucket import forge as bitbucket_forge
from repo_tools.forge import Commit, Forge, Status
from repo_tools.github import api as github_api
from repo_tools.github import forge as github_forge

REPO = "team/app"
T = datetime(2026, 9, 1, 12, tzinfo=UTC)
SINCE = T - timedelta(days=1)


def at(hours: float) -> datetime:
    return T + timedelta(hours=hours)


# (environment, commit, status, started, finished), newest first.
DEPLOYMENTS = [
    ("Production", "c" * 40, Status.IN_PROGRESS, at(30), None),
    ("Production", "b" * 40, Status.FAILED, at(20), at(20.5)),
    ("Staging", "b" * 40, Status.SUCCEEDED, at(19), at(19.1)),
    ("Production", "a" * 40, Status.SUCCEEDED, at(10), at(10.2)),
    ("Production", "9" * 40, Status.SUCCEEDED, at(-48), at(-47.9)),
]

# (number, base, opened, merged, merge commit), newest merge first.
PULLS = [
    (12, "main", at(-30), at(25), "d" * 40),
    (11, "release", at(-5), at(15), "e" * 40),
    (10, "main", at(-6), at(8), "f" * 40),
    (9, "main", at(-100), at(-60), "0" * 40),
]

# base..head, newest first.
FILES = {("trunk", ".config/ianf-dora.toml"): 'version = 1\nproduction = "Production"\n'}

COMMITS = [
    Commit("2" * 40, at(19), "Merged in develop (pull request #4)", merge=True),
    Commit("b" * 40, at(18), "Fix the thing", merge=False),
    Commit("1" * 40, at(12), "Start the thing", merge=False),
]


class GitHubHost:
    """gh, answering as GitHub would for the history."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(github_api, "exists", lambda repo: repo == REPO)
        monkeypatch.setattr(github_forge, "output", self.gh)

    def forge(self) -> Forge:
        return github_forge.GitHub()

    def gh(self, *args: str, input: str | None = None) -> str:
        if args[2:] == (f"repos/{REPO}", "--jq", ".default_branch"):
            return "trunk"
        if args[2].startswith(f"repos/{REPO}/contents/"):
            path, _, ref = args[2].removeprefix(f"repos/{REPO}/contents/").partition("?ref=")
            if (ref, path) in FILES:
                return FILES[(ref, path)]
            raise Failure("gh api repos/… failed.", "gh: Not Found (HTTP 404)")
        if args[2] == f"repos/{REPO}/environments":
            return "Production\nStaging"
        if args[2] == "graphql":
            request = json.loads(input)
            if "deployments(" in request["query"]:
                return json.dumps(self._deployments(request["variables"]))
            return json.dumps(self._pulls(request["variables"]))
        if args[2].startswith(f"repos/{REPO}/compare/a...b"):
            # GitHub lists a comparison's commits oldest first.
            return "\n".join(
                json.dumps(
                    {
                        "sha": c.sha,
                        "date": c.authored_at.isoformat(),
                        "message": c.summary,
                        "parents": 2 if c.merge else 1,
                    }
                )
                for c in reversed(COMMITS)
            )
        raise AssertionError(f"unexpected gh {args}")

    def _deployments(self, variables: dict) -> dict:
        # Exact environment names only, as GitHub matches them; one per page, to page through.
        matching = [d for d in DEPLOYMENTS if d[0] in variables["environments"]]
        return self._page("deployments", matching, variables["after"], self._deployment)

    def _deployment(self, index: int, deployment: tuple) -> dict:
        environment, commit, status, started, finished = deployment
        states = {
            Status.SUCCEEDED: "SUCCESS",
            Status.FAILED: "FAILURE",
            Status.IN_PROGRESS: "IN_PROGRESS",
        }
        return {
            "databaseId": index,
            "environment": environment,
            "createdAt": started.isoformat().replace("+00:00", "Z"),
            "commitOid": commit,
            "latestStatus": {
                "state": states[status],
                "createdAt": (finished or started).isoformat(),
                "logUrl": f"https://github.com/{REPO}/actions/runs/{index}",
            },
        }

    def _pulls(self, variables: dict) -> dict:
        matching = [p for p in PULLS if variables["base"] in (None, p[1])]
        return self._page("pullRequests", matching, variables["after"], self._pull)

    def _pull(self, index: int, pull: tuple) -> dict:
        number, base, opened, merged, merge_commit = pull
        return {
            "number": number,
            "title": f"PR {number}",
            "url": f"https://github.com/{REPO}/pull/{number}",
            "createdAt": opened.isoformat(),
            "mergedAt": merged.isoformat(),
            "updatedAt": (merged + timedelta(minutes=1)).isoformat(),
            "baseRefName": base,
            "author": {"login": "someone"},
            "mergeCommit": {"oid": merge_commit},
        }

    @staticmethod
    def _page(connection: str, items: list, after: str | None, render) -> dict:
        index = int(after or 0)
        nodes = [render(index, items[index])] if index < len(items) else []
        more = index + 1 < len(items)
        page_info = {"hasNextPage": more, "endCursor": str(index + 1)}
        return {"data": {"repository": {connection: {"nodes": nodes, "pageInfo": page_info}}}}


def bitbucket_time(moment: datetime) -> str:
    """A time as Bitbucket writes a deployment's, in nanoseconds: 2026-10-14T18:21:15.336815045Z."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f") + "045Z"


class BitbucketClient:
    """Bitbucket's API, answering as Bitbucket would for the history."""

    environments_ = [
        {"uuid": "{prod}", "name": "Production"},
        {"uuid": "{stage}", "name": "Staging"},
    ]

    def repository(self, repo: str) -> dict | None:
        if repo != REPO:
            return None
        return {"full_name": REPO, "is_private": True, "mainbranch": {"name": "trunk"}}

    def file(self, repo: str, revision: str, path: str) -> str | None:
        return FILES.get((revision, path))

    def environments(self, repo: str) -> list[dict]:
        return self.environments_

    def deployments(self, repo: str):
        uuids = {e["name"]: e["uuid"] for e in self.environments_}
        # Bitbucket's own order isn't by time, and it lists deployments not yet started.
        yield {
            "uuid": "{waiting}",
            "environment": {"uuid": "{prod}"},
            "state": {"name": "UNDEPLOYED"},
        }
        for index, (environment, commit, status, started, finished) in reversed(
            list(enumerate(DEPLOYMENTS))
        ):
            if status == Status.IN_PROGRESS:
                state = {"name": "IN_PROGRESS", "started_on": bitbucket_time(started)}
            else:
                name = {Status.SUCCEEDED: "SUCCESSFUL", Status.FAILED: "FAILED"}[status]
                state = {
                    "name": "COMPLETED",
                    "status": {"name": name},
                    "started_on": bitbucket_time(started),
                    "completed_on": bitbucket_time(finished),
                    "url": f"https://bitbucket.org/{REPO}/pipelines/results/{index}",
                }
            yield {
                "uuid": f"{{{index}}}",
                "environment": {"uuid": uuids[environment]},
                "state": state,
                "release": {
                    "commit": {"hash": commit},
                    "created_on": (started - timedelta(minutes=5)).isoformat(),
                },
            }

    def merged_pull_requests(self, repo: str, updated_since: str, base: str | None):
        since = datetime.fromisoformat(updated_since)
        for number, branch, opened, merged, merge_commit in PULLS:
            if base in (None, branch) and merged + timedelta(minutes=1) >= since:
                yield {
                    "id": number,
                    "title": f"PR {number}",
                    "author": {"display_name": "someone"},
                    "destination": {"branch": {"name": branch}},
                    "created_on": opened.isoformat(),
                    "updated_on": (merged + timedelta(minutes=1)).isoformat(),
                    # Bitbucket gives a pull request's merge commit by its short hash.
                    "merge_commit": {"hash": merge_commit[:12]},
                    "links": {
                        "html": {"href": f"https://bitbucket.org/{REPO}/pull-requests/{number}"}
                    },
                }

    def commit(self, repo: str, revision: str) -> dict:
        merged = next(p[3] for p in PULLS if p[4].startswith(revision))
        return {
            "hash": next(p[4] for p in PULLS if p[4].startswith(revision)),
            "date": merged.isoformat(),
        }

    def commits(self, repo: str, include: str, exclude: str):
        assert (include, exclude) == ("b", "a")
        for c in COMMITS:
            yield {
                "hash": c.sha,
                "date": c.authored_at.isoformat(),
                "message": f"{c.summary}\n\nMore.",
                "parents": [{"hash": "p" * 40}] * (2 if c.merge else 1),
            }


class BitbucketHost:
    def forge(self) -> Forge:
        return bitbucket_forge.Bitbucket(BitbucketClient())


@pytest.fixture(params=["github", "bitbucket"])
def host(request, monkeypatch: pytest.MonkeyPatch):
    return GitHubHost(monkeypatch) if request.param == "github" else BitbucketHost()


def test_names_the_repos_main_branch(host):
    assert host.forge().main_branch(REPO) == "trunk"


def test_reads_a_committed_file_at_a_revision(host):
    assert (
        host.forge().file(REPO, "trunk", ".config/ianf-dora.toml")
        == FILES[("trunk", ".config/ianf-dora.toml")]
    )


def test_a_file_the_revision_does_not_have_is_none(host):
    assert host.forge().file(REPO, "trunk", "missing.toml") is None


def test_lists_the_environments(host):
    assert host.forge().environments(REPO) == ["Production", "Staging"]


def test_lists_the_deployments_to_an_environment_since_a_time_newest_first(host):
    found = host.forge().deployments(REPO, "Production", SINCE)
    assert [(d.environment, d.commit, d.status, d.started_at, d.finished_at) for d in found] == [
        d for d in DEPLOYMENTS if d[0] == "Production" and d[3] >= SINCE
    ]


def test_matches_the_environment_ignoring_case(host):
    found = host.forge().deployments(REPO, "production", SINCE)
    assert {d.environment for d in found} == {"Production"}


def test_every_deployment_links_to_where_it_ran(host):
    assert all(
        d.url.startswith("https://") for d in host.forge().deployments(REPO, "Production", SINCE)
    )


def test_lists_the_pull_requests_merged_since_a_time_newest_first(host):
    found = host.forge().merged_pull_requests(REPO, SINCE)
    assert [(p.number, p.base, p.opened_at, p.merged_at, p.merge_commit) for p in found] == [
        p for p in PULLS if p[3] >= SINCE
    ]


def test_lists_only_the_pull_requests_merged_into_a_base(host):
    found = host.forge().merged_pull_requests(REPO, SINCE, base="main")
    assert [p.number for p in found] == [12, 10]


def test_lists_the_commits_between_two_revisions_newest_first_by_first_line(host):
    assert host.forge().commits_between(REPO, "a", "b") == COMMITS


def test_a_repo_the_host_does_not_have_is_a_precondition(host):
    with pytest.raises(Precondition):
        host.forge().deployments("team/missing", "Production", SINCE)


def test_every_time_is_in_utc(host):
    forge = host.forge()
    times = [d.started_at for d in forge.deployments(REPO, "Production", SINCE)]
    times += [p.merged_at for p in forge.merged_pull_requests(REPO, SINCE)]
    assert all(t.tzinfo == UTC for t in times)
