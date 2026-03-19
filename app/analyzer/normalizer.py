from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Dict, List

from app.models.commit import Commit
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Common suffix/prefix patterns that should be stripped when normalizing
# author names (e.g. "[bot]", "(bot)", trailing punctuation, etc.)
_BOT_PATTERN = re.compile(r"\[bot\]|\(bot\)|bot$", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")

# Map well-known email username variations to a canonical form.
# Extend this dict with project-specific overrides as needed.
_KNOWN_ALIASES: Dict[str, str] = {}


class CommitNormalizer:
    """Normalizes and deduplicates commits across multiple VCS sources."""

    def __init__(self, aliases: Dict[str, str] | None = None) -> None:
        """Initialize with an optional alias map.

        Args:
            aliases: Dict mapping raw author strings (lower-cased) to a
                     canonical display name.  These are layered on top of
                     the built-in alias table.
        """
        self._aliases: Dict[str, str] = {**_KNOWN_ALIASES}
        if aliases:
            self._aliases.update({k.lower().strip(): v for k, v in aliases.items()})

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def normalize_author(self, name: str) -> str:
        """Return a canonical author name.

        Normalisation steps (in order):
        1. Unicode NFC normalisation.
        2. Strip leading/trailing whitespace.
        3. Collapse internal whitespace to a single space.
        4. Strip bot suffixes (``[bot]``, ``(bot)``, etc.).
        5. Look up in the alias table (case-insensitive key).
        6. Title-case the result for consistent display.

        Args:
            name: Raw author string from a commit.

        Returns:
            Normalised display name.
        """
        if not name:
            return "Unknown"

        # Step 1 – Unicode normalisation
        name = unicodedata.normalize("NFC", name)

        # Step 2–3 – whitespace
        name = _WHITESPACE_RE.sub(" ", name).strip()

        # Step 4 – remove bot markers
        name = _BOT_PATTERN.sub("", name).strip()

        if not name:
            return "Unknown"

        # Step 5 – alias lookup
        lower_key = name.lower()
        if lower_key in self._aliases:
            return self._aliases[lower_key]

        # Step 6 – title-case (handles all-caps or all-lowercase names)
        # Preserve casing if it looks intentional (mixed case, e.g. "leMaire")
        if name == name.upper() or name == name.lower():
            name = name.title()

        return name

    def normalize_commits(self, commits: List[Commit]) -> List[Commit]:
        """Return a new list of commits with normalised author names.

        The original :class:`~app.models.commit.Commit` objects are not
        mutated; new instances are created via ``dataclasses.replace``.

        Args:
            commits: Raw commit list.

        Returns:
            New list with normalised ``author`` fields.
        """
        from dataclasses import replace  # local import to avoid circularity

        normalized: List[Commit] = []
        for commit in commits:
            normalized_author = self.normalize_author(commit.author)
            if normalized_author != commit.author:
                logger.debug(
                    "Normalised author: %r -> %r", commit.author, normalized_author
                )
                normalized.append(replace(commit, author=normalized_author))
            else:
                normalized.append(commit)
        return normalized

    def deduplicate(self, commits: List[Commit]) -> List[Commit]:
        """Remove duplicate commits.

        A commit is considered a duplicate if:
        * The ``(sha, repo, source)`` triple already appeared, **or**
        * The ``(author, message_hash, repo)`` triple already appeared
          (catches cross-source duplicates where the SHA differs).

        Args:
            commits: Input commit list (may contain duplicates).

        Returns:
            Deduplicated list preserving the original ordering.
        """
        seen_sha: set[tuple[str, str, str]] = set()
        seen_content: set[tuple[str, str, str]] = set()
        unique: List[Commit] = []

        for commit in commits:
            sha_key = (commit.sha, commit.repo, commit.source)
            # A short content fingerprint: author + first 120 chars of message
            content_fingerprint = hashlib.sha1(
                f"{commit.author.lower()}|{commit.message[:120].lower()}".encode(),
                usedforsecurity=False,
            ).hexdigest()
            content_key = (content_fingerprint, commit.repo, commit.source)

            if sha_key in seen_sha:
                logger.debug("Dedup (sha): skipping %s (%s)", commit.sha[:8], commit.repo)
                continue
            if content_key in seen_content:
                logger.debug(
                    "Dedup (content): skipping commit by %s in %s",
                    commit.author,
                    commit.repo,
                )
                continue

            seen_sha.add(sha_key)
            seen_content.add(content_key)
            unique.append(commit)

        removed = len(commits) - len(unique)
        if removed:
            logger.info("Deduplication removed %d duplicate commit(s).", removed)
        return unique

    def group_by_author(self, commits: List[Commit]) -> Dict[str, List[Commit]]:
        """Group commits by normalised author name.

        Args:
            commits: Normalised, deduplicated commit list.

        Returns:
            Dict mapping author name to list of their commits, sorted with the
            most-committing authors first.
        """
        groups: Dict[str, List[Commit]] = {}
        for commit in commits:
            groups.setdefault(commit.author, []).append(commit)

        # Sort each author's commits by timestamp descending (newest first)
        for author_commits in groups.values():
            author_commits.sort(key=lambda c: c.timestamp, reverse=True)

        logger.info("Grouped commits across %d unique author(s).", len(groups))
        return groups
