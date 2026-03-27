from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.models.commit import Commit, FileStat
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Bitbucket Server (Stash) REST API 1.0
_BITBUCKET_SERVER_URL = os.environ.get("BITBUCKET_SERVER_URL", "https://stash.gto.db.com:8081")
_API_BASE = f"{_BITBUCKET_SERVER_URL}/rest/api/1.0"

_MAX_RETRIES = 5
_INITIAL_BACKOFF = 1.0
_PAGE_LIMIT = 100  # max page size for Bitbucket Server


class BitbucketAuthError(Exception):
    """Raised when the Bitbucket token is invalid or missing."""


class BitbucketNotFoundError(Exception):
    """Raised when the requested repository does not exist."""


class BitbucketRateLimitError(Exception):
    """Raised when the rate limit is exhausted and retries are exceeded."""


class BitbucketClient:
    """Bitbucket Server (Stash) REST API 1.0 client.

    Authentication uses a Personal Access Token (PAT) via Bearer header.
    Generate one at: https://stash.gto.db.com/plugins/servlet/access-tokens/manage
    """

    def __init__(self, token: str, username: Optional[str] = None) -> None:
        if not token or not token.strip():
            raise BitbucketAuthError(
                "A Bitbucket Server personal access token is required. "
                "Set BITBUCKET_TOKEN to a Personal Access Token from Stash.\n"
                "  export BITBUCKET_TOKEN=your_pat_here"
            )
        self._token = token.strip()
        self._username = (username or os.environ.get("BITBUCKET_USERNAME", "")).strip()
        if not self._username:
            raise BitbucketAuthError(
                "A Bitbucket Server username is required for HTTP Basic auth. "
                "Set BITBUCKET_USERNAME to your Stash username.\n"
                "  export BITBUCKET_USERNAME=your_username"
            )
        self._session = requests.Session()
        self._session.auth = (self._username, self._token)
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        if os.environ.get("DISABLE_SSL_VERIFY", "").lower() in ("1", "true", "yes"):
            self._session.verify = False
            logger.warning("SSL verification disabled (DISABLE_SSL_VERIFY=true).")
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        logger.info("BitbucketClient (Server) initialised — host: %s", _BITBUCKET_SERVER_URL)

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

        Bitbucket Server does not support server-side date filtering, so we
        paginate until commits fall outside the requested window.

        Args:
            repo:           Repository in ``PROJECT_KEY/repo_slug`` format.
            since:          Start of the date range (inclusive), timezone-aware.
            until:          End of the date range (inclusive), timezone-aware.
            fetch_details:  When True, also fetch per-commit file diffs.

        Returns:
            List of normalized :class:`~app.models.commit.Commit` objects.
        """
        project, repo_slug = self._parse_repo(repo)
        url = f"{_API_BASE}/projects/{project}/repos/{repo_slug}/commits"

        since_aware = _ensure_utc(since)
        until_aware = _ensure_utc(until)

        logger.info(
            "Fetching commits from Bitbucket Server: %s (since=%s, until=%s)",
            repo, since_aware.isoformat(), until_aware.isoformat(),
        )

        raw_commits: List[Dict[str, Any]] = []
        start = 0
        page = 1
        stop_early = False

        while not stop_early:
            params: Dict[str, Any] = {"start": start, "limit": _PAGE_LIMIT}
            response = self._get_with_retry(url, params=params)
            data: Dict[str, Any] = response.json()
            page_values: List[Dict[str, Any]] = data.get("values", [])

            for raw in page_values:
                ts = _parse_timestamp(raw)
                if ts is None:
                    continue
                # Commits are returned newest-first; stop once before the window
                if ts < since_aware:
                    stop_early = True
                    break
                if ts <= until_aware:
                    raw_commits.append(raw)

            logger.info(
                "  Page %d: %d commits (accepted so far: %d)",
                page, len(page_values), len(raw_commits),
            )

            if data.get("isLastPage", True) or stop_early:
                break

            start = data.get("nextPageStart", start + _PAGE_LIMIT)
            page += 1

        commits = [self._normalize(raw, repo) for raw in raw_commits]
        logger.info(
            "Finished fetching Bitbucket Server commits for %s: %d total", repo, len(commits),
        )

        if fetch_details and commits:
            commits = self._enrich_with_details(commits, repo)

        return commits

    def fetch_commit_detail(
        self, repo: str, sha: str
    ) -> Tuple[List[FileStat], int, int]:
        """Fetch file-level diffs for a single commit.

        Uses the commit-level diff endpoint which returns all changed files
        with their hunks in one call. Falls back to the changes endpoint
        (file names only, no line counts) if the diff call fails.

        Returns:
            Tuple of (file_stats, total_additions, total_deletions).
        """
        project, repo_slug = self._parse_repo(repo)
        return self._fetch_commit_diff(project, repo_slug, sha)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _enrich_with_details(
        self, commits: List[Commit], repo: str
    ) -> List[Commit]:
        """Fetch per-commit file diffs and return enriched commit list."""
        from dataclasses import replace as dc_replace

        logger.info("Fetching commit details for %d commits in %s...", len(commits), repo)
        enriched: List[Commit] = []
        for i, commit in enumerate(commits, 1):
            try:
                file_stats, additions, deletions = self.fetch_commit_detail(repo, commit.sha)
                enriched.append(dc_replace(
                    commit,
                    file_stats=file_stats,
                    additions=additions,
                    deletions=deletions,
                ))
                logger.debug(
                    "  [%d/%d] %s — %d file(s) +%d -%d",
                    i, len(commits), commit.sha[:7], len(file_stats), additions, deletions,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not fetch detail for %s: %s — using message only.",
                    commit.sha[:7], exc,
                )
                enriched.append(commit)

        logger.info("Detail fetch complete for %s.", repo)
        return enriched

    def _fetch_commit_diff(
        self, project: str, repo_slug: str, sha: str
    ) -> Tuple[List[FileStat], int, int]:
        """Fetch and parse the diff for all files in a single commit.

        Bitbucket Server diff response structure:
        {
          "diffs": [{
            "source": {"toString": "old/path.py"},
            "destination": {"toString": "new/path.py"},
            "hunks": [{
              "segments": [{
                "type": "ADDED" | "REMOVED" | "CONTEXT",
                "lines": [{"line": "..."}]
              }]
            }]
          }]
        }
        """
        diff_url = f"{_API_BASE}/projects/{project}/repos/{repo_slug}/commits/{sha}/diff"
        try:
            response = self._get_with_retry(diff_url, params={"contextLines": 3, "whitespace": "IGNORE_ALL"})
            diff_data: Dict[str, Any] = response.json()
        except Exception as exc:
            logger.warning(
                "Diff endpoint failed for %s — falling back to changes only: %s", sha[:7], exc,
            )
            return self._fetch_changes_only(project, repo_slug, sha)

        file_stats: List[FileStat] = []
        total_additions = 0
        total_deletions = 0

        for diff in diff_data.get("diffs", []):
            # Destination path is the post-commit filename; use source for deletions
            dest = diff.get("destination") or {}
            src = diff.get("source") or {}
            filename = dest.get("toString") or src.get("toString") or ""
            if not filename:
                continue

            # Determine status from presence of source/destination
            if not diff.get("source"):
                status = "added"
            elif not diff.get("destination"):
                status = "removed"
            elif dest.get("toString") != src.get("toString"):
                status = "renamed"
            else:
                status = "modified"

            additions = 0
            deletions = 0
            patch_lines: List[str] = []

            for hunk in diff.get("hunks", []):
                src_line = hunk.get("sourceLine", 1)
                src_span = hunk.get("sourceSpan", 0)
                dst_line = hunk.get("destinationLine", 1)
                dst_span = hunk.get("destinationSpan", 0)
                patch_lines.append(f"@@ -{src_line},{src_span} +{dst_line},{dst_span} @@")

                for seg in hunk.get("segments", []):
                    seg_type = seg.get("type", "CONTEXT")
                    for line_obj in seg.get("lines", []):
                        text = line_obj.get("line", "")
                        if seg_type == "ADDED":
                            patch_lines.append(f"+{text}")
                            additions += 1
                        elif seg_type == "REMOVED":
                            patch_lines.append(f"-{text}")
                            deletions += 1
                        else:
                            patch_lines.append(f" {text}")

            total_additions += additions
            total_deletions += deletions
            file_stats.append(FileStat(
                filename=filename,
                status=status,
                additions=additions,
                deletions=deletions,
                patch="\n".join(patch_lines),
            ))

        return file_stats, total_additions, total_deletions

    def _fetch_changes_only(
        self, project: str, repo_slug: str, sha: str
    ) -> Tuple[List[FileStat], int, int]:
        """Fallback: fetch file list from changes endpoint (no line counts or patch)."""
        changes_url = f"{_API_BASE}/projects/{project}/repos/{repo_slug}/commits/{sha}/changes"
        response = self._get_with_retry(changes_url, params={"limit": 100})
        data: Dict[str, Any] = response.json()

        file_stats: List[FileStat] = []
        status_map = {
            "ADD": "added", "MODIFY": "modified", "DELETE": "removed",
            "RENAME": "renamed", "COPY": "added",
        }

        for item in data.get("values", []):
            path_obj = item.get("path") or item.get("srcPath") or {}
            filename = path_obj.get("toString") or path_obj.get("name") or ""
            if not filename:
                continue
            change_type = item.get("type", "MODIFY")
            file_stats.append(FileStat(
                filename=filename,
                status=status_map.get(change_type, "modified"),
            ))

        return file_stats, 0, 0

    def _get_with_retry(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET with exponential back-off on transient errors."""
        backoff = _INITIAL_BACKOFF
        for attempt in range(1, _MAX_RETRIES + 1):
            response = self._session.get(url, params=params, timeout=30)

            if response.status_code == 200:
                return response

            if response.status_code == 401:
                raise BitbucketAuthError(
                    "Bitbucket Server returned 401 Unauthorized. "
                    "Verify BITBUCKET_TOKEN is a valid Personal Access Token."
                )

            if response.status_code == 403:
                raise BitbucketAuthError(
                    "Bitbucket Server returned 403 Forbidden. "
                    "Ensure the PAT has repository read permissions."
                )

            if response.status_code == 404:
                raise BitbucketNotFoundError(
                    f"Resource not found (HTTP 404): {url}\n"
                    "Verify the PROJECT_KEY/repo_slug format and token access."
                )

            if response.status_code in (429, 503) or response.status_code >= 500:
                if attempt >= _MAX_RETRIES:
                    response.raise_for_status()
                logger.warning(
                    "HTTP %d from Bitbucket Server. Retrying in %.1fs (attempt %d/%d).",
                    response.status_code, backoff, attempt, _MAX_RETRIES,
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue

            response.raise_for_status()

        raise RuntimeError("Exhausted retries without a successful response.")

    def _normalize(self, raw: Dict[str, Any], repo: str) -> Commit:
        """Convert a raw Bitbucket Server commit dict into a :class:`Commit`."""
        author_obj = raw.get("author", {})
        author_name = (
            author_obj.get("displayName")
            or author_obj.get("name")
            or author_obj.get("emailAddress")
            or "Unknown"
        ).strip()

        raw_message: str = raw.get("message", "").strip()
        first_line = raw_message.split("\n")[0].strip() if raw_message else "(no message)"

        ts = _parse_timestamp(raw) or datetime.now(tz=timezone.utc)
        sha: str = raw.get("id", "")

        return Commit(
            author=author_name,
            message=first_line,
            timestamp=ts,
            source="bitbucket",
            sha=sha,
            repo=repo,
        )

    @staticmethod
    def _parse_repo(repo: str) -> Tuple[str, str]:
        parts = repo.strip().split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError(
                f"Invalid Bitbucket Server repo format: {repo!r}. "
                "Expected 'PROJECT_KEY/repo_slug' (e.g. 'MYPROJ/my-repo')."
            )
        return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _ensure_utc(dt: datetime) -> datetime:
    """Return *dt* as a timezone-aware UTC datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_timestamp(raw: Dict[str, Any]) -> Optional[datetime]:
    """Parse commit timestamp from Bitbucket Server response.

    Bitbucket Server returns ``authorTimestamp`` as milliseconds since epoch.
    """
    for field in ("authorTimestamp", "committerTimestamp"):
        ts_ms = raw.get(field)
        if ts_ms is not None:
            try:
                return datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                logger.warning("Could not parse timestamp field %r: %r", field, ts_ms)
    return None
