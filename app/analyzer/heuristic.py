from __future__ import annotations

import math
import re
from typing import Dict, List, Tuple

from app.models.commit import Commit
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Message keyword patterns
# ---------------------------------------------------------------------------

_MESSAGE_PATTERNS: Dict[str, re.Pattern[str]] = {
    "feature": re.compile(
        r"\b(feat|feature|add|adds|added|implement|implements|implemented|"
        r"new|create|creates|created|introduce|introduces|introduced|"
        r"support|supports|supported|enable|enables|enabled|build|builds|built)\b",
        re.IGNORECASE,
    ),
    "bugfix": re.compile(
        r"\b(fix|fixes|fixed|bug|bugs|bugfix|patch|patches|patched|hotfix|"
        r"resolve|resolves|resolved|close|closes|closed|issue|revert|reverts|reverted|"
        r"repair|repairs|repaired|correct|corrects|corrected)\b",
        re.IGNORECASE,
    ),
    "refactor": re.compile(
        r"\b(refactor|refactors|refactored|restructure|restructures|restructured|"
        r"clean|cleans|cleaned|cleanup|reorganize|reorganizes|reorganized|"
        r"simplify|simplifies|simplified|improve|improves|improved|improvement|"
        r"optimize|optimizes|optimized|optimization|consolidate|move|rename|"
        r"extract|split|merge)\b",
        re.IGNORECASE,
    ),
    "infra": re.compile(
        r"\b(deploy|deploys|deployed|deployment|ci|cd|docker|dockerfile|"
        r"kubernetes|k8s|helm|terraform|pipeline|pipelines|config|configs|"
        r"configuration|env|environment|release|releases|"
        r"version|bump|upgrade|upgrades|upgraded|dependency|dependencies|"
        r"ansible|chef|puppet|nginx|apache|aws|gcp|azure|cloud|infra|"
        r"infrastructure|devops|workflow|action|actions|makefile|gradle|maven|"
        r"yarn|npm|pip|poetry|cargo|gemfile)\b",
        re.IGNORECASE,
    ),
    "test": re.compile(
        r"\b(test|tests|tested|testing|spec|specs|coverage|unittest|"
        r"pytest|jest|mocha|jasmine|cypress|e2e|integration|unit|"
        r"assert|mock|mocks|mocked|fixture|fixtures|stub|stubs|snapshot|"
        r"tdd|bdd|benchmark|benchmarks)\b",
        re.IGNORECASE,
    ),
    "docs": re.compile(
        r"\b(doc|docs|documentation|readme|changelog|comment|comments|"
        r"commented|wiki|guide|guides|tutorial|tutorials|example|examples|"
        r"license|licence|contributing|authors|todo|fixme|note|notes|"
        r"docstring|jsdoc|typedoc|swagger|openapi)\b",
        re.IGNORECASE,
    ),
}

# ---------------------------------------------------------------------------
# File path patterns — each entry is (regex, category, score_contribution)
# Higher score = stronger signal from this file pattern
# ---------------------------------------------------------------------------

_FILE_PATTERNS: List[Tuple[re.Pattern[str], str, float]] = [
    # --- infra (strongest file signals) ---
    (re.compile(r"(^|/)Dockerfile[^/]*$", re.IGNORECASE), "infra", 3.0),
    (re.compile(r"(^|/)docker-compose[^/]*\.(ya?ml)$", re.IGNORECASE), "infra", 3.0),
    (re.compile(r"\.tf$|\.tfvars$", re.IGNORECASE), "infra", 3.0),
    (re.compile(r"(^|/)\.github/workflows/", re.IGNORECASE), "infra", 3.0),
    (re.compile(r"(^|/)(k8s|kubernetes|helm)/", re.IGNORECASE), "infra", 2.5),
    (re.compile(r"(^|/)Makefile$", re.IGNORECASE), "infra", 2.0),
    (re.compile(r"\.sh$", re.IGNORECASE), "infra", 1.5),
    (re.compile(r"(^|/)(requirements|requirements-.*)\.(txt|in)$", re.IGNORECASE), "infra", 1.5),
    (re.compile(r"(^|/)package\.json$", re.IGNORECASE), "infra", 1.5),
    (re.compile(r"(^|/)(pom\.xml|build\.gradle|build\.gradle\.kts)$", re.IGNORECASE), "infra", 1.5),
    (re.compile(r"(^|/)(pyproject\.toml|setup\.py|setup\.cfg)$", re.IGNORECASE), "infra", 1.5),
    (re.compile(r"\.(ya?ml)$", re.IGNORECASE), "infra", 1.0),  # generic yaml (lower weight)
    (re.compile(r"(^|/)\.env[^/]*$", re.IGNORECASE), "infra", 1.0),

    # --- test ---
    (re.compile(r"(^|/)(tests?|__tests?__|spec)/", re.IGNORECASE), "test", 3.0),
    (re.compile(r"(^|/)test_[^/]+\.py$", re.IGNORECASE), "test", 3.0),
    (re.compile(r"(^|/)[^/]+_test\.py$", re.IGNORECASE), "test", 3.0),
    (re.compile(r"(^|/)[^/]+\.(spec|test)\.(ts|tsx|js|jsx)$", re.IGNORECASE), "test", 3.0),
    (re.compile(r"(^|/)[^/]+Test\.java$"), "test", 3.0),
    (re.compile(r"(^|/)[^/]+_test\.go$"), "test", 3.0),
    (re.compile(r"(^|/)conftest\.py$", re.IGNORECASE), "test", 2.0),

    # --- docs ---
    (re.compile(r"(^|/)README[^/]*$", re.IGNORECASE), "docs", 3.0),
    (re.compile(r"(^|/)CHANGELOG[^/]*$", re.IGNORECASE), "docs", 3.0),
    (re.compile(r"(^|/)CONTRIBUTING[^/]*$", re.IGNORECASE), "docs", 2.5),
    (re.compile(r"(^|/)(docs?|documentation|wiki)/", re.IGNORECASE), "docs", 2.5),
    (re.compile(r"\.md$|\.rst$|\.adoc$", re.IGNORECASE), "docs", 2.0),

    # --- feature / bugfix have weak file signals; message keywords dominate ---
    (re.compile(r"(^|/)(src|lib|app|core|api|service|controller|handler|model|view)/", re.IGNORECASE), "feature", 1.0),
]

# Category weights for impact score calculation
_CATEGORY_WEIGHTS: Dict[str, float] = {
    "infra": 1.5,
    "feature": 1.3,
    "bugfix": 1.2,
    "refactor": 1.0,
    "test": 0.8,
    "docs": 0.5,
}

_DEFAULT_WEIGHT = 1.0
_MIN_SCORE = 1.0
_MAX_SCORE = 10.0

# Score contributions
_FILE_SIGNAL_WEIGHT = 2.0    # files are 2x more reliable than message keywords
_MESSAGE_SIGNAL_WEIGHT = 1.0


class HeuristicAnalyzer:
    """Commit classifier that combines file-path patterns and message keywords.

    Classification strategy (score-based):
    1. Score each category using file path patterns (higher weight — more reliable).
    2. Score each category using message keywords (lower weight — often misleading).
    3. The category with the highest combined score wins.
    4. Ties are broken by category priority: bugfix > infra > test > docs > refactor > feature.
    """

    _PRIORITY_ORDER = ["bugfix", "infra", "test", "docs", "refactor", "feature"]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def classify_commit(self, commit: Commit) -> str:
        """Classify a commit using both file changes and commit message.

        Args:
            commit: The commit to classify.

        Returns:
            One of: ``feature``, ``bugfix``, ``refactor``, ``infra``, ``test``, ``docs``.
        """
        scores: Dict[str, float] = {cat: 0.0 for cat in _MESSAGE_PATTERNS}

        # --- Score from file paths (higher weight) ---
        if commit.has_detail:
            for filename in commit.changed_files:
                for pattern, category, contribution in _FILE_PATTERNS:
                    if pattern.search(filename):
                        scores[category] = scores.get(category, 0.0) + (contribution * _FILE_SIGNAL_WEIGHT)

        # --- Score from commit message (lower weight) ---
        message = commit.message or ""
        for category, pattern in _MESSAGE_PATTERNS.items():
            if pattern.search(message):
                scores[category] = scores.get(category, 0.0) + _MESSAGE_SIGNAL_WEIGHT

        # --- Pick winner ---
        max_score = max(scores.values()) if scores else 0.0
        if max_score == 0.0:
            return "feature"  # fallback

        # Among categories sharing the top score, use priority order
        top_categories = [cat for cat, s in scores.items() if s == max_score]
        for cat in self._PRIORITY_ORDER:
            if cat in top_categories:
                return cat

        return "feature"

    def classify_commit_with_reason(self, commit: Commit) -> Tuple[str, str]:
        """Like :meth:`classify_commit` but also returns a human-readable reason.

        Returns:
            Tuple of (category, reason_string).
        """
        category = self.classify_commit(commit)
        if commit.has_detail:
            matched_files = [
                f for f in commit.changed_files
                if any(p.search(f) for p, c, _ in _FILE_PATTERNS if c == category)
            ]
            if matched_files:
                sample = matched_files[:2]
                return category, f"files: {', '.join(sample)}"
        return category, f"message: '{commit.message[:60]}'"

    def get_category_weights(self) -> Dict[str, float]:
        """Return the weight mapping for each commit category."""
        return dict(_CATEGORY_WEIGHTS)

    def analyze_commits(self, commits: List[Commit]) -> Dict[str, int]:
        """Count commits per category.

        Returns:
            Dict of ``{category: count}``. All categories present even when zero.
        """
        counts: Dict[str, int] = {category: 0 for category in _MESSAGE_PATTERNS}
        for commit in commits:
            category = self.classify_commit(commit)
            counts[category] = counts.get(category, 0) + 1
        return counts

    def calculate_base_score(self, categories: Dict[str, int]) -> float:
        """Calculate a weighted base impact score in the range [1, 10].

        Considers both commit counts per category AND total lines changed
        across all commits when file detail is available.
        """
        total_commits = sum(categories.values())
        if total_commits == 0:
            return _MIN_SCORE

        weighted_total = sum(
            count * _CATEGORY_WEIGHTS.get(cat, _DEFAULT_WEIGHT)
            for cat, count in categories.items()
        )

        # log scale: ~30 weighted commits => ~7.0
        reference = 30.0
        raw_score = 1.0 + 9.0 * math.log1p(weighted_total) / math.log1p(reference)

        # Diversity bonus
        active_categories = sum(1 for v in categories.values() if v > 0)
        diversity_bonus = min((active_categories - 1) * 0.1, 0.5)
        raw_score += diversity_bonus

        score = round(max(_MIN_SCORE, min(_MAX_SCORE, raw_score)), 2)
        logger.debug(
            "Base score: weighted_total=%.1f, diversity=%d, raw=%.2f, final=%.2f",
            weighted_total, active_categories, raw_score, score,
        )
        return score
