from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class Commit:
    """Represents a single normalized commit from any source."""

    author: str
    message: str
    timestamp: datetime
    source: str  # "github" or "bitbucket"
    sha: str
    repo: str

    def __post_init__(self) -> None:
        if self.source not in ("github", "bitbucket"):
            raise ValueError(
                f"source must be 'github' or 'bitbucket', got: {self.source!r}"
            )
        if not self.sha:
            raise ValueError("sha must not be empty")
        if not self.repo:
            raise ValueError("repo must not be empty")

    def first_line_message(self) -> str:
        """Return only the first line of the commit message."""
        return self.message.split("\n")[0].strip()

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
