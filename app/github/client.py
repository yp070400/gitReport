from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from dateutil import parser as dateutil_parser

from app.models.commit import Commit
from app.utils.logger import get_logger

logger = get_logger(__name__)

_GITHUB_API_BASE = "https://api.github.com"
_MAX_PER_PAGE = 100
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 1.0  # seconds


class GitHubAuthError(Exception):
    """Raised when the GitHub token is invalid or missing."""


class GitHubRateLimitError(Exception):
    """Raised when the rate limit is exhausted and retries are exceeded."""


class GitHubNotFoundError(Exception):
    """Raised when the requested repository does not exist."""


class GitHubClient:
    """Thin wrapper around the GitHub REST API v3 for fetching commit data."""

    def __init__(self, token: Optional[str] = None) -> None:
        """Initialize the client.

        Args:
            token: GitHub personal access token or fine-grained token.
                   Optional for public repos; required for private repos.
                   Providing a token also raises the rate limit from 60 to 5000 req/hr.
        """
        self._token = token.strip() if token and token.strip() else None
        self._session = requests.Session()
        headers: Dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
            logger.info("GitHub client authenticated (rate limit: 5000 req/hr).")
        else:
            logger.info("GitHub client unauthenticated — public repos only (rate limit: 60 req/hr).")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_commits(
        self,
        repo: str,
        since: datetime,
        until: datetime,
    ) -> List[Commit]:
        """Fetch all commits in *repo* between *since* and *until*.

        Args:
            repo:  Repository in ``owner/repo`` format.
            since: Start of the date range (inclusive), timezone-aware.
            until: End of the date range (inclusive), timezone-aware.

        Returns:
            List of normalized :class:`~app.models.commit.Commit` objects.

        Raises:
            GitHubAuthError:        On HTTP 401.
            GitHubRateLimitError:   When rate limit cannot be recovered from.
            GitHubNotFoundError:    On HTTP 404.
            requests.HTTPError:     On other unexpected HTTP errors.
        """
        owner, repo_name = self._parse_repo(repo)
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo_name}/commits"
        params: Dict[str, Any] = {
            "since": _fmt_iso(since),
            "until": _fmt_iso(until),
            "per_page": _MAX_PER_PAGE,
        }

        logger.info("Fetching commits from GitHub: %s (since=%s, until=%s)", repo, params["since"], params["until"])

        raw_commits: List[Dict[str, Any]] = []
        page = 1
        next_url: Optional[str] = url

        while next_url:
            try:
                response = self._get_with_retry(next_url, params=params if page == 1 else None)
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 409:
                    logger.warning(
                        "Repository '%s' is empty (no commits). Skipping.", repo
                    )
                    return []
                raise
            page_data: List[Dict[str, Any]] = response.json()
            raw_commits.extend(page_data)
            logger.info("  Page %d: fetched %d commits (total so far: %d)", page, len(page_data), len(raw_commits))
            next_url = _parse_next_link(response.headers.get("Link", ""))
            page += 1

        commits = [self._normalize(c, repo) for c in raw_commits]
        logger.info("Finished fetching GitHub commits for %s: %d total", repo, len(commits))
        return commits

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_with_retry(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Perform a GET request with exponential back-off on rate limits."""
        backoff = _INITIAL_BACKOFF
        for attempt in range(1, _MAX_RETRIES + 1):
            response = self._session.get(url, params=params, timeout=30)

            if response.status_code == 200:
                return response

            if response.status_code == 401:
                raise GitHubAuthError(
                    "GitHub API returned 401 Unauthorized. "
                    "Check that GITHUB_TOKEN is valid and has the required scopes."
                )

            if response.status_code == 404:
                raise GitHubNotFoundError(
                    f"Repository not found (HTTP 404) for URL: {url}. "
                    "Verify the owner/repo format and that the token has access."
                )

            if response.status_code in (403, 429):
                remaining = response.headers.get("X-RateLimit-Remaining", "?")
                reset_ts = response.headers.get("X-RateLimit-Reset")

                if reset_ts:
                    reset_time = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc)
                    wait_seconds = max(
                        (reset_time - datetime.now(tz=timezone.utc)).total_seconds() + 1,
                        backoff,
                    )
                else:
                    wait_seconds = backoff

                if attempt >= _MAX_RETRIES:
                    raise GitHubRateLimitError(
                        f"GitHub rate limit exceeded. Remaining: {remaining}. "
                        f"Rate limit resets at {reset_ts}. "
                        "Consider waiting or using a token with higher rate limits."
                    )

                logger.warning(
                    "GitHub rate limit hit (remaining=%s). Waiting %.1fs before retry %d/%d.",
                    remaining,
                    wait_seconds,
                    attempt,
                    _MAX_RETRIES,
                )
                time.sleep(wait_seconds)
                backoff = min(backoff * 2, 60.0)
                continue

            # Any other non-success status
            response.raise_for_status()

        # Should be unreachable, but satisfies type checker
        raise RuntimeError("Exhausted retries without a successful response.")

    def _normalize(self, raw: Dict[str, Any], repo: str) -> Commit:
        """Convert a raw GitHub API commit dict into a :class:`Commit`."""
        commit_data = raw.get("commit", {})
        commit_author = commit_data.get("author", {})
        api_author = raw.get("author") or {}

        # Prefer the git-level author name; fall back to the GitHub login
        author_name: str = (
            commit_author.get("name")
            or api_author.get("login")
            or "Unknown"
        ).strip()

        raw_message: str = commit_data.get("message", "").strip()
        first_line = raw_message.split("\n")[0].strip() if raw_message else "(no message)"

        raw_ts = commit_author.get("date", "")
        try:
            ts = dateutil_parser.isoparse(raw_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            ts = datetime.now(tz=timezone.utc)
            logger.warning("Could not parse timestamp %r; using current time.", raw_ts)

        sha: str = raw.get("sha", "")

        return Commit(
            author=author_name,
            message=first_line,
            timestamp=ts,
            source="github",
            sha=sha,
            repo=repo,
        )

    @staticmethod
    def _parse_repo(repo: str) -> tuple[str, str]:
        parts = repo.strip().split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError(
                f"Invalid GitHub repo format: {repo!r}. Expected 'owner/repo'."
            )
        return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _fmt_iso(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 string accepted by GitHub."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_next_link(link_header: str) -> Optional[str]:
    """Extract the ``rel="next"`` URL from a GitHub ``Link`` response header.

    GitHub paginates using the ``Link`` header with the format::

        <https://api.github.com/...?page=2>; rel="next", <...>; rel="last"

    Returns the URL string if found, else ``None``.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None
