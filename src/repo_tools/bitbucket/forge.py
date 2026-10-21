"""Bitbucket Cloud as a Forge, read through its REST API.

Deployments are Bitbucket's deployments, which Pipelines records for each step that names a
deployment environment. Bitbucket stops listing a deployment once its pipeline's artifacts
expire, so older ones can't be read back: see the README's DORA section.

Bitbucket doesn't say when a pull request merged, so it's taken as the date of its merge
commit, which Bitbucket makes as it merges. That costs a request per pull request.
"""

from datetime import UTC, datetime

from cli_kit.outcome import Precondition

from repo_list import config
from repo_tools.bitbucket import api
from repo_tools.forge import Commit, Deployment, Forge, PullRequest, Status

STATUSES = {
    "SUCCESSFUL": Status.SUCCEEDED,
    "FAILED": Status.FAILED,
    "STOPPED": Status.STOPPED,
}


class Bitbucket(Forge):
    name = "Bitbucket"

    def __init__(self, client: api.Bitbucket | None = None) -> None:
        self._client = client

    @property
    def client(self) -> api.Bitbucket:
        """The API client, signed in on first use, so a command that fails its own checks never
        reads the token."""
        if self._client is None:
            self._client = api.connect()
        return self._client

    def full_name(self, repo: str) -> str:
        if "/" in repo:
            return repo
        workspace = config.load().bitbucket_workspace
        if not workspace:
            raise Precondition(
                f"Name the repo as workspace/{repo}.",
                f"Or set bitbucket.workspace in {config.CONFIG} for repos given by bare name.",
            )
        return f"{workspace}/{repo}"

    def main_branch(self, repo: str) -> str:
        found = self.client.repository(repo)
        if found is None:
            raise Precondition(f"No Bitbucket repo {repo}, or the token can't see it.")
        return found["mainbranch"]["name"]

    def file(self, repo: str, revision: str, path: str) -> str | None:
        self._must_exist(repo)
        return self.client.file(repo, revision, path)

    def environments(self, repo: str) -> list[str]:
        self._must_exist(repo)
        return [environment["name"] for environment in self.client.environments(repo)]

    def deployments(self, repo: str, environment: str, since: datetime) -> list[Deployment]:
        self._must_exist(repo)
        environments = self.client.environments(repo)
        uuid = next(
            (e["uuid"] for e in environments if e["name"].casefold() == environment.casefold()),
            None,
        )
        if uuid is None:
            names = ", ".join(e["name"] for e in environments) or "none"
            raise Precondition(f"{repo} has no environment {environment}.", f"It has: {names}.")
        name = next(e["name"] for e in environments if e["uuid"] == uuid)

        found = []
        for raw in self.client.deployments(repo):
            if raw.get("environment", {}).get("uuid") != uuid:
                continue
            deployment = _deployment(repo, raw, name)
            if deployment is not None and deployment.started_at >= since:
                found.append(deployment)
        return sorted(found, key=lambda d: d.started_at, reverse=True)

    def merged_pull_requests(
        self, repo: str, since: datetime, base: str | None = None
    ) -> list[PullRequest]:
        self._must_exist(repo)
        found = []
        for raw in self.client.merged_pull_requests(repo, since.isoformat(), base):
            merge = (raw.get("merge_commit") or {}).get("hash")
            if not merge:
                continue
            commit = self.client.commit(repo, merge)
            merged_at = _time(commit["date"])
            if merged_at >= since:
                found.append(_pull_request(raw, commit["hash"], merged_at))
        return sorted(found, key=lambda pull: pull.merged_at, reverse=True)

    def commits_between(self, repo: str, base: str, head: str) -> list[Commit]:
        self._must_exist(repo)
        return [
            Commit(
                c["hash"],
                _time(c["date"]),
                c.get("message", "").partition("\n")[0],
                merge=len(c.get("parents", [])) > 1,
            )
            for c in self.client.commits(repo, include=head, exclude=base)
        ]

    def _must_exist(self, repo: str) -> None:
        if self.client.repository(repo) is None:
            raise Precondition(f"No Bitbucket repo {repo}, or the token can't see it.")


def _deployment(repo: str, raw: dict, environment: str) -> Deployment | None:
    """The deployment, or None for one Bitbucket lists that hasn't started, such as a manual
    step not yet run. Its times are started_on and completed_on, as Bitbucket sends them,
    though its API reference names them start_date and completion_date."""
    state = raw.get("state", {})
    match state.get("name"):
        case "COMPLETED":
            status = STATUSES.get(state.get("status", {}).get("name", ""), Status.STOPPED)
            finished = _time(state["completed_on"]) if state.get("completed_on") else None
        case "IN_PROGRESS":
            status, finished = Status.IN_PROGRESS, None
        case _:
            return None
    release = raw.get("release", {})
    return Deployment(
        id=raw["uuid"],
        environment=environment,
        commit=release.get("commit", {}).get("hash", ""),
        status=status,
        started_at=_time(state.get("started_on") or release["created_on"]),
        finished_at=finished,
        url=state.get("url") or release.get("url") or f"{api.web_url(repo)}/deployments",
    )


def _pull_request(raw: dict, merge_commit: str, merged_at: datetime) -> PullRequest:
    return PullRequest(
        number=raw["id"],
        title=raw["title"],
        author=(raw.get("author") or {}).get("display_name", ""),
        base=raw["destination"]["branch"]["name"],
        opened_at=_time(raw["created_on"]),
        merged_at=merged_at,
        merge_commit=merge_commit,
        url=raw["links"]["html"]["href"],
    )


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)
