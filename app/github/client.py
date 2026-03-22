from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from dateutil import parser as dateutil_parser

from app.models.commit import Commit, FileStat
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
    """GitHub REST API v3 client using curl for HTTP requests."""

    def __init__(self, token: Optional[str] = None) -> None:
        """Initialize the client.

        Args:
            token: GitHub personal access token or fine-grained token.
                   Optional for public repos; required for private repos.
                   Providing a token raises the rate limit from 60 to 5000 req/hr.
        """
        self._token = token.strip() if token and token.strip() else None
        self._ssl_verify = os.environ.get("DISABLE_SSL_VERIFY", "").lower() not in ("1", "true", "yes")

        if self._token:
            logger.info("GitHub client authenticated (rate limit: 5000 req/hr).")
        else:
            logger.info("GitHub client unauthenticated — public repos only (rate limit: 60 req/hr).")

        if not self._ssl_verify:
            logger.warning("SSL verification disabled (DISABLE_SSL_VERIFY=true).")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_commits(
        self,
        repo: str,
        since: datetime,
        until: datetime,
        fetch_details: bool = True,
    ) -> List[Commit]:
        """Fetch all commits in *repo* between *since* and *until*.

        Args:
            repo:  Repository in ``owner/repo`` format.
            since: Start of the date range (inclusive), timezone-aware.
            until: End of the date range (inclusive), timezone-aware.

        Returns:
            List of normalized :class:`~app.models.commit.Commit` objects.
        """
        owner, repo_name = self._parse_repo(repo)
        params = {
            "since": _fmt_iso(since),
            "until": _fmt_iso(until),
            "per_page": str(_MAX_PER_PAGE),
        }
        base_url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo_name}/commits"
        first_url = f"{base_url}?{urlencode(params)}"

        logger.info(
            "Fetching commits from GitHub: %s (since=%s, until=%s)",
            repo, params["since"], params["until"],
        )

        raw_commits: List[Dict[str, Any]] = []
        next_url: Optional[str] = first_url
        page = 1

        while next_url:
            status, body, link_header = self._curl_with_retry(next_url)

            if status == 409:
                logger.warning("Repository '%s' is empty (no commits). Skipping.", repo)
                return []

            try:
                page_data: List[Dict[str, Any]] = json.loads(body)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"GitHub API returned non-JSON response (status={status}): {body[:200]}"
                ) from exc

            raw_commits.extend(page_data)
            logger.info(
                "  Page %d: fetched %d commits (total so far: %d)",
                page, len(page_data), len(raw_commits),
            )
            next_url = _parse_next_link(link_header)
            page += 1

        commits = [self._normalize(c, repo) for c in raw_commits]
        logger.info("Finished fetching GitHub commits for %s: %d total", repo, len(commits))

        if fetch_details and commits:
            commits = self._enrich_with_details(commits, repo)

        return commits

    def _enrich_with_details(self, commits: List[Commit], repo: str) -> List[Commit]:
        """Fetch per-commit file stats and return enriched commit list."""
        logger.info("Fetching commit details for %d commits in %s...", len(commits), repo)
        enriched: List[Commit] = []
        for i, commit in enumerate(commits, start=1):
            try:
                file_stats, additions, deletions = self.fetch_commit_detail(repo, commit.sha)
                from dataclasses import replace as dc_replace
                enriched.append(dc_replace(
                    commit,
                    file_stats=file_stats,
                    additions=additions,
                    deletions=deletions,
                ))
                logger.debug(
                    "  [%d/%d] %s — %d file(s) +%d -%d",
                    i, len(commits), commit.sha[:7],
                    len(file_stats), additions, deletions,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not fetch detail for %s: %s — using message only.", commit.sha[:7], exc)
                enriched.append(commit)
        logger.info("Detail fetch complete for %s.", repo)
        return enriched

    def fetch_commit_detail(
        self, repo: str, sha: str
    ) -> tuple:  # (List[FileStat], int additions, int deletions)
        """Fetch file-level changes for a single commit.

        Returns:
            Tuple of (file_stats, total_additions, total_deletions).
        """
        owner, repo_name = self._parse_repo(repo)
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo_name}/commits/{sha}"
        status, body, _ = self._curl_with_retry(url)

        try:
            data: Dict[str, Any] = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Non-JSON response for commit {sha}: {body[:200]}") from exc

        stats = data.get("stats", {})
        additions: int = stats.get("additions", 0)
        deletions: int = stats.get("deletions", 0)

        file_stats: List[FileStat] = [
            FileStat(
                filename=f.get("filename", ""),
                status=f.get("status", "modified"),
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
            )
            for f in data.get("files", [])
            if f.get("filename")
        ]
        return file_stats, additions, deletions

    # ------------------------------------------------------------------
    # curl execution
    # ------------------------------------------------------------------

    def _build_curl_cmd(self, url: str) -> List[str]:
        """Build the curl command list for a GET request."""
        cmd = ["curl", "-s", "-i"]
        if not self._ssl_verify:
            cmd.append("-k")
        cmd.extend(["-H", "Accept: application/vnd.github+json"])
        cmd.extend(["-H", "X-GitHub-Api-Version: 2022-11-28"])
        if self._token:
            cmd.extend(["-H", f"Authorization: Bearer {self._token}"])
        cmd.append(url)
        return cmd

    def _curl_with_retry(self, url: str) -> Tuple[int, str, str]:
        """Run curl with exponential back-off on rate limits.

        Returns:
            Tuple of (http_status_code, response_body, link_header).
        """
        backoff = _INITIAL_BACKOFF
        for attempt in range(1, _MAX_RETRIES + 1):
            status, body, headers_raw = self._run_curl(url)

            if status == 200:
                link = _extract_header(headers_raw, "link")
                return status, body, link

            if status == 401:
                raise GitHubAuthError(
                    "GitHub API returned 401 Unauthorized. "
                    "Check that GITHUB_TOKEN is valid and has the required scopes."
                )

            if status == 404:
                raise GitHubNotFoundError(
                    f"Repository not found (HTTP 404): {url}. "
                    "Verify the owner/repo format and that the token has access."
                )

            if status == 409:
                # Empty repository — return immediately, caller handles it
                return status, body, ""

            if status in (403, 429):
                remaining = _extract_header(headers_raw, "x-ratelimit-remaining") or "0"
                reset_ts = _extract_header(headers_raw, "x-ratelimit-reset")
                is_unauthenticated = not self._token

                if reset_ts:
                    reset_time = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc)
                    reset_str = reset_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                    wait_seconds = max(
                        (reset_time - datetime.now(tz=timezone.utc)).total_seconds() + 1,
                        backoff,
                    )
                else:
                    reset_str = "unknown"
                    wait_seconds = backoff

                if attempt >= _MAX_RETRIES:
                    if is_unauthenticated:
                        raise GitHubRateLimitError(
                            "GitHub rate limit exceeded for unauthenticated requests (60 req/hr). "
                            f"Rate limit resets at {reset_str}. "
                            "Fix: set GITHUB_TOKEN to get 5000 req/hr:\n"
                            "  export GITHUB_TOKEN=ghp_your_token_here"
                        )
                    raise GitHubRateLimitError(
                        f"GitHub rate limit exceeded. Remaining: {remaining}. "
                        f"Rate limit resets at {reset_str}. "
                        "Consider using a token with higher rate limits or waiting."
                    )

                logger.warning(
                    "GitHub rate limit hit (remaining=%s). Waiting %.1fs before retry %d/%d.",
                    remaining, wait_seconds, attempt, _MAX_RETRIES,
                )
                time.sleep(wait_seconds)
                backoff = min(backoff * 2, 60.0)
                continue

            raise RuntimeError(
                f"GitHub API returned unexpected status {status} for URL: {url}. "
                f"Body: {body[:200]}"
            )

        raise RuntimeError("Exhausted retries without a successful response.")

    def _run_curl(self, url: str) -> Tuple[int, str, str]:
        """Execute curl and return (status_code, body, raw_headers_string)."""
        cmd = self._build_curl_cmd(url)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"curl timed out fetching: {url}")
        except FileNotFoundError:
            raise RuntimeError(
                "curl is not installed or not found in PATH. "
                "Install curl and try again."
            )

        raw = result.stdout

        # curl -i outputs: status line + headers + blank line + body
        # Split on the first blank line (handles both \r\n\r\n and \n\n)
        if "\r\n\r\n" in raw:
            header_section, _, body = raw.partition("\r\n\r\n")
        elif "\n\n" in raw:
            header_section, _, body = raw.partition("\n\n")
        else:
            header_section, body = raw, ""

        # Parse status code from first line: "HTTP/1.1 200 OK"
        status_line = header_section.split("\n")[0].strip()
        try:
            status_code = int(status_line.split()[1])
        except (IndexError, ValueError):
            raise RuntimeError(
                f"Could not parse HTTP status from curl output. "
                f"First line: {status_line!r}. Full output: {raw[:300]}"
            )

        return status_code, body.strip(), header_section

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(self, raw: Dict[str, Any], repo: str) -> Commit:
        """Convert a raw GitHub API commit dict into a :class:`Commit`."""
        commit_data = raw.get("commit", {})
        commit_author = commit_data.get("author", {})
        api_author = raw.get("author") or {}

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
    """Format a datetime as ISO-8601 accepted by GitHub."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_header(headers_raw: str, name: str) -> Optional[str]:
    """Case-insensitive header extraction from a raw header block."""
    for line in headers_raw.splitlines():
        if ":" in line and line.split(":", 1)[0].strip().lower() == name.lower():
            return line.split(":", 1)[1].strip()
    return None


def _parse_next_link(link_header: str) -> Optional[str]:
    """Extract the rel="next" URL from a GitHub Link header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None
