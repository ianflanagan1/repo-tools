"""Bitbucket Cloud's REST API (2.0), for the bitbucket commands and the Bitbucket forge.

It signs in with your Atlassian email and a scoped API token, by basic auth: Bitbucket no
longer takes app passwords. Git itself goes over SSH, with your own key, so the token never
pushes. A repo is named workspace/slug, the slug being the lower-case name in its URLs.
"""

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

from cli_kit.credentials import Credential, Token
from cli_kit.outcome import Failure, Precondition

BASE_URL = "https://api.bitbucket.org/2.0"
PAGE = 50  # the most the pull requests endpoint allows; others allow 100
# characters. Bitbucket documents no limit on a repo's description; this is GitHub's, so a
# description stays one short line in either.
DESCRIPTION_MAX_LENGTH = 350

SCOPES = (
    "read:repository:bitbucket",
    "admin:repository:bitbucket",
    "read:pullrequest:bitbucket",
    "write:pullrequest:bitbucket",
    "read:pipeline:bitbucket",
)

TOKEN = Token(
    service="bitbucket-api-token",
    name="Bitbucket API token",
    username="atlassian-email",
    create="Create an API token with scopes at"
    " https://id.atlassian.com/manage-profile/security/api-tokens, choosing Bitbucket and only"
    f" these scopes: {', '.join(SCOPES)}.",
)


class NotFound(Failure):
    """Bitbucket answered 404: there's no such thing, or the token can't see it."""


class Forbidden(Failure):
    """Bitbucket answered 403: the token lacks a scope it needs, or the account lacks access."""


class Bitbucket:
    def __init__(self, credential: Credential) -> None:
        pair = f"{credential.username}:{credential.token}".encode()
        self._auth = f"Basic {base64.b64encode(pair).decode()}"

    # Repositories

    def repository(self, repo: str) -> dict | None:
        """The repo, or None when there's none the token can see."""
        try:
            return self._send("GET", self._url("repositories", repo))
        except NotFound:
            return None

    def create(self, repo: str, private: bool, description: str, project: str | None) -> None:
        """Creates the repo, in the workspace's project with key project, or in its default
        project when None."""
        body: dict = {"scm": "git", "is_private": private, "description": description}
        if project:
            body["project"] = {"key": project}
        self._send("POST", self._url("repositories", repo), body)

    def rename(self, repo: str, new_name: str) -> str:
        """Renames the repo, which gives it the slug of the new name, and returns its new
        workspace/slug."""
        renamed = self._send("PUT", self._url("repositories", repo), {"name": new_name})
        return renamed["full_name"]

    def delete(self, repo: str) -> None:
        """Deletes the repo. The token needs the delete:repository:bitbucket scope."""
        self._send("DELETE", self._url("repositories", repo))

    # Pipelines

    def pipelines_enabled(self, repo: str) -> bool:
        """Whether Pipelines is on. A repo that has never configured it answers 404: off."""
        try:
            config = self._send("GET", self._url("repositories", repo, "pipelines_config"))
        except NotFound:
            return False
        return bool(config.get("enabled"))

    def enable_pipelines(self, repo: str) -> None:
        url = self._url("repositories", repo, "pipelines_config")
        self._send("PUT", url, {"enabled": True})

    def pipeline_for(self, repo: str, commit: str) -> dict | None:
        """The latest pipeline run on commit, or None while there's none."""
        query = urllib.parse.urlencode(
            {"target.commit.hash": commit, "sort": "-created_on", "pagelen": 1}
        )
        page = self._send("GET", self._url("repositories", repo, "pipelines") + "?" + query)
        return next(iter(page.get("values", [])), None)

    def pipelines(self, repo: str) -> Iterator[dict]:
        """The repo's pipeline runs, newest first, read only as far as the caller iterates."""
        return self._pages(self._url("repositories", repo, "pipelines") + "?sort=-created_on")

    def pipeline(self, repo: str, uuid: str) -> dict:
        return self._send("GET", self._url("repositories", repo, "pipelines", uuid))

    def failed_step_log(self, repo: str, pipeline: str) -> str:
        """The log of the pipeline's first failed step, or "" when no step failed."""
        steps = self._pages(self._url("repositories", repo, "pipelines", pipeline, "steps"))
        for step in steps:
            result = step.get("state", {}).get("result", {}).get("name")
            if result in ("FAILED", "ERROR"):
                url = self._url("repositories", repo, "pipelines", pipeline, "steps", step["uuid"])
                return self._send("GET", url + "/log", text=True)
        return ""

    # Files

    def file(self, repo: str, revision: str, path: str) -> str | None:
        """The file at path in revision, a branch, tag or commit, or None when it has none."""
        try:
            return self._send(
                "GET", self._url("repositories", repo, "src", revision, path), text=True
            )
        except NotFound:
            return None

    # Delivery

    def environments(self, repo: str) -> list[dict]:
        return list(self._pages(self._url("repositories", repo, "environments") + "/"))

    def deployments(self, repo: str) -> Iterator[dict]:
        """Every deployment Bitbucket still lists, in its own order. It drops those whose
        pipeline's artifacts have expired."""
        return self._pages(self._url("repositories", repo, "deployments") + "/")

    def merged_pull_requests(
        self, repo: str, updated_since: str, base: str | None
    ) -> Iterator[dict]:
        """Merged pull requests last updated at or after updated_since, an ISO 8601 time, into
        base or any branch, most recently updated first."""
        clauses = ['state = "MERGED"', f"updated_on >= {updated_since}"]
        if base:
            clauses.append(f"destination.branch.name = {json.dumps(base)}")
        query = urllib.parse.urlencode(
            {"q": " AND ".join(clauses), "sort": "-updated_on", "state": "MERGED"}
        )
        return self._pages(self._url("repositories", repo, "pullrequests") + "?" + query)

    def open_pull_requests(self, repo: str, branch: str) -> int:
        """How many open pull requests the repo has from branch."""
        clauses = [f"source.branch.name = {json.dumps(branch)}", 'state = "OPEN"']
        query = urllib.parse.urlencode({"q": " AND ".join(clauses)})
        url = self._url("repositories", repo, "pullrequests") + "?" + query
        return len(list(self._pages(url)))

    def create_draft_pull_request(
        self, repo: str, branch: str, base: str, title: str, body: str
    ) -> str:
        """Opens a draft pull request from branch into base, and returns its URL. The token
        needs the write:pullrequest:bitbucket scope."""
        created = self._send(
            "POST",
            self._url("repositories", repo, "pullrequests"),
            {
                "title": title,
                "description": body,
                "source": {"branch": {"name": branch}},
                "destination": {"branch": {"name": base}},
                "draft": True,
            },
        )
        return created["links"]["html"]["href"]

    def commit(self, repo: str, revision: str) -> dict:
        return self._send("GET", self._url("repositories", repo, "commit", revision))

    def commits(self, repo: str, include: str, exclude: str) -> Iterator[dict]:
        """The commits reachable from include and not from exclude, newest first."""
        query = urllib.parse.urlencode({"include": include, "exclude": exclude})
        return self._pages(self._url("repositories", repo, "commits") + "?" + query)

    # Plumbing

    def _pages(self, url: str) -> Iterator[dict]:
        """Every value in each page of the answer to url, following each page's next link, read
        only as far as the caller iterates."""
        separator = "&" if "?" in url else "?"
        next_url: str | None = f"{url}{separator}pagelen={PAGE}"
        while next_url:
            page = self._send("GET", next_url)
            yield from page.get("values", [])
            next_url = page.get("next")

    def _send(self, method: str, url: str, body: dict | None = None, text: bool = False) -> Any:
        """Sends body as JSON, and returns Bitbucket's JSON answer, {} for none, or its answer
        as text when text is set.

        Raises Precondition when Bitbucket refuses the token, NotFound when it answers 404, and
        Failure, with Bitbucket's message, for any other error or when it can't be reached.
        """
        accept = "text/plain, */*" if text else "application/json"
        headers = {"Authorization": self._auth, "Accept": accept}
        if body is not None:
            headers["Content-Type"] = "application/json"
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                content = response.read().decode(errors="replace")
        except urllib.error.HTTPError as error:
            messages = _messages(error.read().decode(errors="replace"))
            if error.code == 401:
                raise _refused() from None
            if error.code == 403:
                raise Forbidden(
                    "Bitbucket answered 403.",
                    *messages,
                    f"The token needs the scopes {', '.join(SCOPES)}, and your account access.",
                ) from None
            kind = NotFound if error.code == 404 else Failure
            raise kind(f"Bitbucket answered {error.code}.", *messages) from None
        except urllib.error.URLError as error:
            raise Failure(f"Can't reach {request.host}.", str(error.reason)) from None
        if text:
            return content
        return json.loads(content) if content.strip() else {}

    @staticmethod
    def _url(*path: str) -> str:
        """The API URL of path, where workspace/slug counts as two parts."""
        parts = [part for segment in path for part in segment.split("/")]
        return BASE_URL + "/" + "/".join(urllib.parse.quote(part, safe="{}") for part in parts)


def connect() -> Bitbucket:
    return Bitbucket(TOKEN.read())


def repo_from_url(url: str) -> str:
    """The workspace/slug of a Bitbucket remote URL, in SSH or HTTPS form."""
    match = re.search(r"bitbucket\.org[:/](.+?)(?:\.git)?/?$", url)
    if not match:
        raise Precondition(f"{url} is not a Bitbucket repo.")
    return match.group(1)


def renamed_url(url: str, repo: str) -> str:
    """The Bitbucket remote URL url, in the same SSH or HTTPS form, naming repo instead."""
    return re.sub(r"(bitbucket\.org[:/]).+?((?:\.git)?)$", rf"\g<1>{repo}\g<2>", url)


def ssh_url(repo: str) -> str:
    return f"git@bitbucket.org:{repo}.git"


def web_url(repo: str) -> str:
    return f"https://bitbucket.org/{repo}"


def _refused() -> Precondition:
    return Precondition(
        "Bitbucket refused the API token.",
        "It must be an API token with scopes, stored under the email you sign in to Atlassian"
        " with, and not expired. Delete it from the credential store and run again to see how"
        " to store a new one.",
    )


def _messages(body: str) -> list[str]:
    """Bitbucket's error message and detail, or the body as it is when it isn't its JSON."""
    try:
        error = json.loads(body).get("error", {})
    except (ValueError, AttributeError):
        return [body.strip()] if body.strip() else []
    return [str(error[key]) for key in ("message", "detail") if error.get(key)]
