from __future__ import annotations

import re
from typing import Dict, List

from app.models.commit import Commit
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Keyword definitions for each category
# ---------------------------------------------------------------------------

_CATEGORY_PATTERNS: Dict[str, re.Pattern[str]] = {
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
        r"configuration|env|environment|build|builds|built|release|releases|"
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

# Category weights used when calculating a heuristic impact score
_CATEGORY_WEIGHTS: Dict[str, float] = {
    "infra": 1.5,
    "feature": 1.3,
    "bugfix": 1.2,
    "refactor": 1.0,
    "test": 0.8,
    "docs": 0.5,
}

# Default weight for commits that don't match any category
_DEFAULT_WEIGHT = 1.0

# Score is clamped to this range
_MIN_SCORE = 1.0
_MAX_SCORE = 10.0


class HeuristicAnalyzer:
    """Rule-based commit classifier and impact score calculator."""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def classify_commit(self, message: str) -> str:
        """Classify a commit message into a category.

        Categories are checked in priority order:
        ``bugfix > infra > test > docs > refactor > feature``.
        The first matching category wins so that more specific categories
        (e.g. "fix") take precedence over broad ones (e.g. "improve").

        Args:
            message: Commit subject line (first line of the commit message).

        Returns:
            One of: ``feature``, ``bugfix``, ``refactor``, ``infra``,
            ``test``, ``docs``.  Defaults to ``feature`` when no keywords
            match.
        """
        if not message:
            return "feature"

        # Priority-ordered check
        priority_order = ["bugfix", "infra", "test", "docs", "refactor", "feature"]
        for category in priority_order:
            if _CATEGORY_PATTERNS[category].search(message):
                return category

        # Fallback: generic commit most likely adds something
        return "feature"

    def get_category_weights(self) -> Dict[str, float]:
        """Return the weight mapping for each commit category.

        Returns:
            Dict of ``{category: weight}`` used in impact score calculation.
        """
        return dict(_CATEGORY_WEIGHTS)

    def analyze_commits(self, commits: List[Commit]) -> Dict[str, int]:
        """Count commits per category.

        Args:
            commits: List of commits to classify.

        Returns:
            Dict of ``{category: count}``.  All categories are present in the
            output even when their count is zero.
        """
        counts: Dict[str, int] = {category: 0 for category in _CATEGORY_PATTERNS}
        for commit in commits:
            category = self.classify_commit(commit.message)
            counts[category] = counts.get(category, 0) + 1
        return counts

    def calculate_base_score(self, categories: Dict[str, int]) -> float:
        """Calculate a weighted base impact score in the range [1, 10].

        Algorithm:
        1. Compute a weighted commit count: sum of (count * weight) per category.
        2. Normalise against a reference value (30 weighted commits = score of 7)
           so that a developer with ~30 impactful commits scores around 7/10.
        3. Apply a logarithmic dampening to avoid runaway scores for extremely
           prolific committers.
        4. Clamp to [1, 10].

        Args:
            categories: Dict of ``{category: count}`` from
                :meth:`analyze_commits`.

        Returns:
            Float impact score between 1.0 and 10.0.
        """
        total_commits = sum(categories.values())
        if total_commits == 0:
            return _MIN_SCORE

        weighted_total = sum(
            count * _CATEGORY_WEIGHTS.get(cat, _DEFAULT_WEIGHT)
            for cat, count in categories.items()
        )

        # Normalise: 30 weighted points => score ~7.0
        # Using a log scale: score = 1 + 9 * log(1 + weighted) / log(1 + reference)
        import math

        reference = 30.0
        raw_score = 1.0 + 9.0 * math.log1p(weighted_total) / math.log1p(reference)

        # Bonus for diversity: if a developer touches multiple categories
        active_categories = sum(1 for v in categories.values() if v > 0)
        diversity_bonus = min((active_categories - 1) * 0.1, 0.5)
        raw_score += diversity_bonus

        score = round(max(_MIN_SCORE, min(_MAX_SCORE, raw_score)), 2)
        logger.debug(
            "Base score: weighted_total=%.1f, diversity=%d, raw=%.2f, final=%.2f",
            weighted_total,
            active_categories,
            raw_score,
            score,
        )
        return score
