from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from dateutil import parser as dateutil_parser

from app.models.commit import Commit
from app.utils.logger import get_logger

logger = get_logger(__name__)

_BITBUCKET_API_BASE = "https://api.bitbucket.org/2.0"
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 1.0  # seconds
_PAGE_LEN = 100  # maximum page size for Bitbucket API


class BitbucketAuthError(Exception):
    """Raised when the Bitbucket token is invalid or missing."""


class BitbucketNotFoundError(Exception):
    """Raised when the requested repository does not exist."""


class BitbucketRateLimitError(Exception):
    """Raised when the rate limit is exhausted and retries are exceeded."""


class BitbucketClient:
    """Thin wrapper around the Bitbucket Cloud REST API 2.0 for commit data."""

    def __init__(self, token: str) -> None:
        """Initialize the client.

        Args:
            token: Bitbucket App Password or OAuth access token.
        """
        if not token or not token.strip():
            raise BitbucketAuthError(
                "A Bitbucket token is required. "
                "Set the BITBUCKET_TOKEN environment variable to an App Password."
            )
        self._token = token.strip()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

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

        The Bitbucket Cloud API does not support date-range filtering on
        commits, so we fetch pages until the commit timestamp falls before
        *since* and then filter in Python.

        Args:
            repo:  Repository in ``workspace/repo_slug`` format.
            since: Start of the date range (inclusive), timezone-aware.
            until: End of the date range (inclusive), timezone-aware.

        Returns:
            List of normalized :class:`~app.models.commit.Commit` objects.

        Raises:
            BitbucketAuthError:      On HTTP 401 / 403.
            BitbucketNotFoundError:  On HTTP 404.
            requests.HTTPError:      On other unexpected HTTP errors.
        """
        workspace, repo_slug = self._parse_repo(repo)
        url: Optional[str] = (
            f"{_BITBUCKET_API_BASE}/repositories/{workspace}/{repo_slug}/commits"
        )
        params: Dict[str, Any] = {"pagelen": _PAGE_LEN}

        # Ensure datetimes are timezone-aware for comparisons
        since_aware = _ensure_utc(since)
        until_aware = _ensure_utc(until)

        logger.info(
            "Fetching commits from Bitbucket: %s (since=%s, until=%s)",
            repo,
            since_aware.isoformat(),
            until_aware.isoformat(),
        )

        commits: List[Commit] = []
        page = 1
        stop_early = False

        while url and not stop_early:
            response = self._get_with_retry(url, params=params if page == 1 else None)
            data: Dict[str, Any] = response.json()
            raw_commits: List[Dict[str, Any]] = data.get("values", [])

            for raw in raw_commits:
                ts = self._parse_timestamp(raw)
                if ts is None:
                    continue

                # Commits are returned newest-first; once we're older than
                # *since* we can stop fetching further pages.
                if ts < since_aware:
                    stop_early = True
                    break

                if ts > until_aware:
                    continue  # Skip commits newer than the requested window

                commits.append(self._normalize(raw, repo))

            logger.info(
                "  Page %d: processed %d commits (accepted so far: %d)",
                page,
                len(raw_commits),
                len(commits),
            )

            url = data.get("next")  # Bitbucket provides the full next URL
            page += 1

        logger.info(
            "Finished fetching Bitbucket commits for %s: %d total", repo, len(commits)
        )
        return commits

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_with_retry(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Perform a GET request with exponential back-off on transient errors."""
        backoff = _INITIAL_BACKOFF
        for attempt in range(1, _MAX_RETRIES + 1):
            response = self._session.get(url, params=params, timeout=30)

            if response.status_code == 200:
                return response

            if response.status_code == 401:
                raise BitbucketAuthError(
                    "Bitbucket API returned 401 Unauthorized. "
                    "Check that BITBUCKET_TOKEN is a valid App Password or access token."
                )

            if response.status_code == 403:
                raise BitbucketAuthError(
                    "Bitbucket API returned 403 Forbidden. "
                    "Ensure the token has the 'repository:read' scope."
                )

            if response.status_code == 404:
                raise BitbucketNotFoundError(
                    f"Repository not found (HTTP 404) for URL: {url}. "
                    "Verify the workspace/repo_slug format and token permissions."
                )

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", backoff))
                if attempt >= _MAX_RETRIES:
                    raise BitbucketRateLimitError(
                        "Bitbucket rate limit exceeded after maximum retries."
                    )
                logger.warning(
                    "Bitbucket rate limit hit. Waiting %.1fs before retry %d/%d.",
                    retry_after,
                    attempt,
                    _MAX_RETRIES,
                )
                time.sleep(retry_after)
                backoff = min(backoff * 2, 60.0)
                continue

            if response.status_code >= 500:
                if attempt >= _MAX_RETRIES:
                    response.raise_for_status()
                logger.warning(
                    "Bitbucket server error %d. Retrying in %.1fs (attempt %d/%d).",
                    response.status_code,
                    backoff,
                    attempt,
                    _MAX_RETRIES,
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue

            response.raise_for_status()

        raise RuntimeError("Exhausted retries without a successful response.")

    def _normalize(self, raw: Dict[str, Any], repo: str) -> Commit:
        """Convert a raw Bitbucket API commit dict into a :class:`Commit`."""
        # Author resolution: prefer user display_name, fall back to raw string
        author_obj = raw.get("author", {})
        user_obj = author_obj.get("user", {})
        raw_author_str: str = author_obj.get("raw", "")

        if user_obj.get("display_name"):
            author_name = user_obj["display_name"].strip()
        elif raw_author_str:
            # raw is typically "Full Name <email@example.com>"
            match = re.match(r"^(.+?)\s*<", raw_author_str)
            author_name = match.group(1).strip() if match else raw_author_str.strip()
        else:
            author_name = "Unknown"

        raw_message: str = raw.get("message", "").strip()
        first_line = raw_message.split("\n")[0].strip() if raw_message else "(no message)"

        ts = self._parse_timestamp(raw) or datetime.now(tz=timezone.utc)
        sha: str = raw.get("hash", "")

        return Commit(
            author=author_name,
            message=first_line,
            timestamp=ts,
            source="bitbucket",
            sha=sha,
            repo=repo,
        )

    @staticmethod
    def _parse_timestamp(raw: Dict[str, Any]) -> Optional[datetime]:
        """Parse the commit date field from a Bitbucket commit dict."""
        date_str: str = raw.get("date", "")
        if not date_str:
            return None
        try:
            ts = dateutil_parser.isoparse(date_str)
            return _ensure_utc(ts)
        except (ValueError, TypeError):
            logger.warning("Could not parse Bitbucket timestamp %r.", date_str)
            return None

    @staticmethod
    def _parse_repo(repo: str) -> tuple[str, str]:
        parts = repo.strip().split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError(
                f"Invalid Bitbucket repo format: {repo!r}. "
                "Expected 'workspace/repo_slug'."
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
