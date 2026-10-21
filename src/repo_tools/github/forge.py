"""GitHub as a Forge, read through gh.

Deployments are GitHub's deployments API, which Actions fills when a job names an environment,
and each one's status is its latest deployment status. GitHub marks a successful deployment
inactive once a newer one to the same environment succeeds, so inactive counts as succeeded.
"""

import json
from datetime import UTC, datetime

from cli_kit.outcome import Failure, Precondition
from cli_kit.proc import output

from repo_tools.forge import Commit, Deployment, Forge, PullRequest, Status
from repo_tools.github import api

PAGE = 100

STATUSES = {
    "SUCCESS": Status.SUCCEEDED,
    "INACTIVE": Status.SUCCEEDED,
    "FAILURE": Status.FAILED,
    "ERROR": Status.FAILED,
    "PENDING": Status.IN_PROGRESS,
    "QUEUED": Status.IN_PROGRESS,
    "IN_PROGRESS": Status.IN_PROGRESS,
    "WAITING": Status.IN_PROGRESS,
}

DEPLOYMENTS = """
query($owner: String!, $name: String!, $environments: [String!], $after: String) {
  repository(owner: $owner, name: $name) {
    deployments(environments: $environments, first: 100, after: $after,
                orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        databaseId environment createdAt commitOid
        latestStatus { state createdAt logUrl }
      }
    }
  }
}
"""

# GitHub can't order pull requests by when they merged, so they're read by when they last
# changed, which is never before they merged, until one changed before since.
MERGED = """
query($owner: String!, $name: String!, $base: String, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, baseRefName: $base, first: 100, after: $after,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title url createdAt mergedAt updatedAt baseRefName
        author { login }
        mergeCommit { oid }
      }
    }
  }
}
"""


class GitHub(Forge):
    name = "GitHub"

    def full_name(self, repo: str) -> str:
        return api.full_name(repo)

    def main_branch(self, repo: str) -> str:
        self._must_exist(repo)
        return output("gh", "api", f"repos/{repo}", "--jq", ".default_branch")

    def file(self, repo: str, revision: str, path: str) -> str | None:
        self._must_exist(repo)
        try:
            return output(
                "gh",
                "api",
                f"repos/{repo}/contents/{path}?ref={revision}",
                "-H",
                "Accept: application/vnd.github.raw",
            )
        except Failure as failure:
            if any("HTTP 404" in line for line in failure.details):
                return None
            raise

    def environments(self, repo: str) -> list[str]:
        self._must_exist(repo)
        return _environments(repo)

    def deployments(self, repo: str, environment: str, since: datetime) -> list[Deployment]:
        self._must_exist(repo)
        # GitHub matches the environment exactly, so it's named as GitHub has it.
        named = {name.casefold(): name for name in _environments(repo)}
        environment = named.get(environment.casefold(), environment)
        found: list[Deployment] = []
        for node in self._nodes(repo, DEPLOYMENTS, "deployments", environments=[environment]):
            started = _time(node["createdAt"])
            if started < since:
                break
            found.append(_deployment(repo, node))
        return found

    def merged_pull_requests(
        self, repo: str, since: datetime, base: str | None = None
    ) -> list[PullRequest]:
        self._must_exist(repo)
        found: list[PullRequest] = []
        for node in self._nodes(repo, MERGED, "pullRequests", base=base):
            if _time(node["updatedAt"]) < since:
                break
            if _time(node["mergedAt"]) >= since:
                found.append(_pull_request(node))
        return sorted(found, key=lambda pull: pull.merged_at, reverse=True)

    def commits_between(self, repo: str, base: str, head: str) -> list[Commit]:
        self._must_exist(repo)
        jq = (
            ".commits[] | {sha, date: .commit.author.date, message: .commit.message,"
            " parents: (.parents | length)}"
        )
        listing = output(
            "gh",
            "api",
            f"repos/{repo}/compare/{base}...{head}?per_page={PAGE}",
            "--paginate",
            "--jq",
            jq,
        )
        commits = [json.loads(line) for line in listing.splitlines()]
        # GitHub lists them oldest first.
        return [
            Commit(
                c["sha"],
                _time(c["date"]),
                c["message"].partition("\n")[0],
                merge=c["parents"] > 1,
            )
            for c in reversed(commits)
        ]

    def _must_exist(self, repo: str) -> None:
        if not api.exists(repo):
            raise Precondition(f"gh can't see a repo {repo}.")

    def _nodes(self, repo: str, query: str, connection: str, **variables):
        """Each node of the repository's connection, page by page, read only as far as the
        caller iterates."""
        owner, name = repo.split("/", 1)
        after = None
        while True:
            body = {
                "query": query,
                "variables": {"owner": owner, "name": name, "after": after, **variables},
            }
            page = json.loads(
                output("gh", "api", "graphql", "--input", "-", input=json.dumps(body))
            )
            found = page["data"]["repository"][connection]
            yield from found["nodes"]
            if not found["pageInfo"]["hasNextPage"]:
                return
            after = found["pageInfo"]["endCursor"]


def _environments(repo: str) -> list[str]:
    jq = ".environments[].name"
    return output("gh", "api", f"repos/{repo}/environments", "--jq", jq).splitlines()


def _deployment(repo: str, node: dict) -> Deployment:
    latest = node.get("latestStatus") or {}
    status = STATUSES.get(latest.get("state", ""), Status.STOPPED) if latest else Status.IN_PROGRESS
    finished = _time(latest["createdAt"]) if status != Status.IN_PROGRESS else None
    url = latest.get("logUrl") or f"https://github.com/{repo}/deployments/{node['environment']}"
    return Deployment(
        id=str(node["databaseId"]),
        environment=node["environment"],
        commit=node["commitOid"],
        status=status,
        started_at=_time(node["createdAt"]),
        finished_at=finished,
        url=url,
    )


def _pull_request(node: dict) -> PullRequest:
    return PullRequest(
        number=node["number"],
        title=node["title"],
        author=(node.get("author") or {}).get("login", "ghost"),
        base=node["baseRefName"],
        opened_at=_time(node["createdAt"]),
        merged_at=_time(node["mergedAt"]),
        merge_commit=(node.get("mergeCommit") or {}).get("oid"),
        url=node["url"],
    )


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)
