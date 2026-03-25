from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


_MAX_PATCH_CHARS = 1500  # truncate individual file patches to keep prompt size sane


@dataclass
class FileStat:
    """Represents a single file changed in a commit."""

    filename: str
    status: str   # added | modified | removed | renamed
    additions: int = 0
    deletions: int = 0
    patch: str = ""  # actual unified diff from GitHub API

    def patch_preview(self) -> str:
        """Return patch content truncated to _MAX_PATCH_CHARS."""
        if not self.patch:
            return ""
        if len(self.patch) <= _MAX_PATCH_CHARS:
            return self.patch
        return self.patch[:_MAX_PATCH_CHARS] + "\n    ... (truncated)"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
            "patch": self.patch,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FileStat:
        return cls(
            filename=data["filename"],
            status=data.get("status", "modified"),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            patch=data.get("patch", ""),
        )


@dataclass
class Commit:
    """Represents a single normalized commit from any source."""

    author: str
    message: str
    timestamp: datetime
    source: str  # "github" or "bitbucket"
    sha: str
    repo: str

    # Populated when commit detail is fetched (--no-details to skip)
    file_stats: List[FileStat] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0

    def __post_init__(self) -> None:
        if self.source not in ("github", "bitbucket"):
            raise ValueError(
                f"source must be 'github' or 'bitbucket', got: {self.source!r}"
            )
        if not self.sha:
            raise ValueError("sha must not be empty")
        if not self.repo:
            raise ValueError("repo must not be empty")

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def first_line_message(self) -> str:
        """Return only the first line of the commit message."""
        return self.message.split("\n")[0].strip()

    @property
    def has_detail(self) -> bool:
        """True if file-level detail has been fetched for this commit."""
        return len(self.file_stats) > 0

    @property
    def changed_files(self) -> List[str]:
        """Return just the list of filenames changed."""
        return [f.filename for f in self.file_stats]

    def file_detail_summary(self, max_files: int = 10) -> str:
        """Human-readable summary of files changed with diff content, used in AI prompts."""
        if not self.file_stats:
            return ""
        lines = []
        for fs in self.file_stats[:max_files]:
            lines.append(
                f"    [{fs.status:8s}] {fs.filename} (+{fs.additions} -{fs.deletions})"
            )
            patch = fs.patch_preview()
            if patch:
                # Indent patch lines so they're visually nested under the file
                for patch_line in patch.splitlines():
                    lines.append(f"      {patch_line}")
        if len(self.file_stats) > max_files:
            remaining = len(self.file_stats) - max_files
            lines.append(f"    ... and {remaining} more file(s)")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "author": self.author,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "sha": self.sha,
            "repo": self.repo,
            "file_stats": [f.to_dict() for f in self.file_stats],
            "additions": self.additions,
            "deletions": self.deletions,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Commit:
        """Deserialize from a dict (as produced by :meth:`to_dict`)."""
        ts = datetime.fromisoformat(data["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        file_stats = [FileStat.from_dict(f) for f in data.get("file_stats", [])]
        return cls(
            author=data["author"],
            message=data["message"],
            timestamp=ts,
            source=data["source"],
            sha=data["sha"],
            repo=data["repo"],
            file_stats=file_stats,
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
        )

    def __hash__(self) -> int:
        return hash((self.sha, self.source, self.repo))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Commit):
            return NotImplemented
        return (
            self.sha == other.sha
            and self.source == other.source
            and self.repo == other.repo
        )


@dataclass
class DeveloperSummary:
    """Aggregated analysis result for a single developer."""

    author: str
    commits: List[Commit]
    categories: Dict[str, int]
    impact_score: float
    ai_summary: str
    key_contributions: List[str]
    themes: List[str]

    # Optional fields populated when AI analysis is available
    reasoning: str = field(default="")

    def total_commits(self) -> int:
        return len(self.commits)

    def dominant_category(self) -> str:
        if not self.categories:
            return "unknown"
        return max(self.categories, key=lambda k: self.categories[k])

    def is_high_impact(self) -> bool:
        return self.impact_score >= 8.0

    def is_low_value(self) -> bool:
        return self.impact_score <= 3.0
