#!/usr/bin/env python3
"""AI Engineering Impact Analyzer – CLI entry point.

Usage examples::

    python main.py --source=github --github-repo=owner/repo --months=3
    python main.py --source=bitbucket --bitbucket-repo=workspace/repo --months=3
    python main.py --source=both --github-repo=owner/repo --bitbucket-repo=ws/repo --months=6
    python main.py --source=github --github-repo=owner/repo --no-ai --output=report.md
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from app.ai.vertex import VertexAIAnalyzer
from app.analyzer.heuristic import HeuristicAnalyzer
from app.analyzer.normalizer import CommitNormalizer
from app.bitbucket.client import BitbucketClient
from app.github.client import GitHubClient
from app.models.commit import Commit, DeveloperSummary
from app.report.generator import ReportGenerator
from app.utils.config import load_config
from app.utils.logger import get_logger

logger = get_logger("main")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="AI Engineering Impact Analyzer – analyze developer contributions using Vertex AI Gemini.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap(),
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=["github", "bitbucket", "both"],
        help="Data source(s) to analyze.",
    )
    parser.add_argument(
        "--github-repo",
        metavar="OWNER/REPO",
        default=None,
        help="GitHub repository in owner/repo format.",
    )
    parser.add_argument(
        "--bitbucket-repo",
        metavar="WORKSPACE/REPO",
        default=None,
        help="Bitbucket repository in workspace/repo_slug format.",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=3,
        metavar="N",
        help="Number of months to look back (default: 3).",
    )
    parser.add_argument(
        "--output",
        default="report.md",
        metavar="FILE",
        help="Output Markdown report path (default: report.md).",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        default=False,
        help="Skip Vertex AI analysis and use heuristic scores only.",
    )
    return parser


def textwrap() -> str:
    return (
        "Examples:\n"
        "  python main.py --source=github --github-repo=octocat/Hello-World\n"
        "  python main.py --source=bitbucket --bitbucket-repo=my-workspace/my-repo --months=6\n"
        "  python main.py --source=both --github-repo=org/backend --bitbucket-repo=org/frontend\n"
        "  python main.py --source=github --github-repo=org/repo --no-ai --output=results.md\n"
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_args(args: argparse.Namespace, config) -> None:  # type: ignore[type-arg]
    """Raise SystemExit with a helpful message on invalid argument combinations."""
    if args.source in ("github", "both"):
        if not args.github_repo:
            _die("--github-repo is required when --source is 'github' or 'both'.")
        if not config.github_token:
            logger.warning(
                "GITHUB_TOKEN is not set. Proceeding unauthenticated (public repos only, "
                "60 req/hr rate limit). Set GITHUB_TOKEN to access private repos."
            )

    if args.source in ("bitbucket", "both"):
        if not args.bitbucket_repo:
            _die("--bitbucket-repo is required when --source is 'bitbucket' or 'both'.")
        if not config.bitbucket_token:
            _die(
                "BITBUCKET_TOKEN environment variable is not set.\n"
                "Create a Bitbucket App Password with 'repository:read' permission:\n"
                "  export BITBUCKET_TOKEN=your_app_password"
            )

    if args.months < 1 or args.months > 24:
        _die("--months must be between 1 and 24.")


def _die(message: str) -> None:
    print(f"\n[ERROR] {message}\n", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------


def fetch_commits(
    args: argparse.Namespace,
    config,  # type: ignore[type-arg]
    since: datetime,
    until: datetime,
) -> List[Commit]:
    """Fetch raw commits from the configured source(s)."""
    all_commits: List[Commit] = []

    if args.source in ("github", "both"):
        logger.info("Connecting to GitHub API...")
        gh_client = GitHubClient(token=config.github_token)
        gh_commits = gh_client.fetch_commits(
            repo=args.github_repo,
            since=since,
            until=until,
        )
        logger.info("Fetched %d commits from GitHub.", len(gh_commits))
        all_commits.extend(gh_commits)

    if args.source in ("bitbucket", "both"):
        logger.info("Connecting to Bitbucket API...")
        bb_client = BitbucketClient(token=config.bitbucket_token)
        bb_commits = bb_client.fetch_commits(
            repo=args.bitbucket_repo,
            since=since,
            until=until,
        )
        logger.info("Fetched %d commits from Bitbucket.", len(bb_commits))
        all_commits.extend(bb_commits)

    return all_commits


def build_developer_summaries(
    grouped: Dict[str, List[Commit]],
    heuristic: HeuristicAnalyzer,
    ai_analyzer: Optional[VertexAIAnalyzer],
) -> List[DeveloperSummary]:
    """Build a DeveloperSummary for every author."""
    summaries: List[DeveloperSummary] = []

    for author, commits in grouped.items():
        categories = heuristic.analyze_commits(commits)
        base_score = heuristic.calculate_base_score(categories)

        if ai_analyzer is not None:
            logger.info("Running AI analysis for: %s", author)
            ai_result = ai_analyzer.analyze_developer(
                author=author,
                commits=commits,
                categories=categories,
                base_score=base_score,
            )
            impact_score = ai_result.get("impact_score", base_score)
            ai_summary = ai_result.get("summary", "")
            key_contributions = ai_result.get("key_contributions", [])
            themes = ai_result.get("themes", [])
            reasoning = ai_result.get("reasoning", "")
        else:
            impact_score = base_score
            ai_summary = (
                f"{author} contributed {len(commits)} commit(s) "
                f"with a dominant focus on {_dominant(categories)}. "
                "Heuristic analysis used (AI disabled)."
            )
            key_contributions = _heuristic_contributions(commits, categories)
            themes = _heuristic_themes(categories)
            reasoning = ""

        summaries.append(
            DeveloperSummary(
                author=author,
                commits=commits,
                categories=categories,
                impact_score=round(float(impact_score), 2),
                ai_summary=ai_summary,
                key_contributions=key_contributions,
                themes=themes,
                reasoning=reasoning,
            )
        )

    return summaries


# ---------------------------------------------------------------------------
# Heuristic fallback helpers (used when --no-ai is set)
# ---------------------------------------------------------------------------


def _dominant(categories: Dict[str, int]) -> str:
    if not categories or all(v == 0 for v in categories.values()):
        return "general work"
    return max(categories, key=lambda k: categories[k])


def _heuristic_contributions(commits: List[Commit], categories: Dict[str, int]) -> List[str]:
    """Generate a short list of key contributions from heuristic data only."""
    contributions: List[str] = []

    # Pick the top 3 most recent distinct commit messages
    seen: set[str] = set()
    for commit in sorted(commits, key=lambda c: c.timestamp, reverse=True):
        msg = commit.message[:120]
        if msg not in seen:
            contributions.append(msg)
            seen.add(msg)
        if len(contributions) >= 3:
            break

    if not contributions:
        contributions.append("Contributions analyzed via heuristic categorization.")

    return contributions


def _heuristic_themes(categories: Dict[str, int]) -> List[str]:
    """Derive themes from top-2 categories."""
    sorted_cats = sorted(
        ((cat, cnt) for cat, cnt in categories.items() if cnt > 0),
        key=lambda x: -x[1],
    )
    return [cat for cat, _ in sorted_cats[:2]] or ["general engineering"]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # ---- Load config ----
    config = load_config()

    # ---- Validate arguments ----
    validate_args(args, config)

    # ---- Compute date range ----
    until = datetime.now(tz=timezone.utc)
    # Use 30-day months as an approximation
    since = until - timedelta(days=args.months * 30)
    logger.info(
        "Analysis window: %s → %s (%d month(s))",
        since.strftime("%Y-%m-%d"),
        until.strftime("%Y-%m-%d"),
        args.months,
    )

    # ---- Fetch commits ----
    raw_commits = fetch_commits(args, config, since, until)
    if not raw_commits:
        logger.warning("No commits found in the specified window. Exiting.")
        sys.exit(0)
    logger.info("Total raw commits fetched: %d", len(raw_commits))

    # ---- Normalize & deduplicate ----
    normalizer = CommitNormalizer()
    normalized = normalizer.normalize_commits(raw_commits)
    deduped = normalizer.deduplicate(normalized)
    logger.info("After normalization and deduplication: %d commits", len(deduped))

    # ---- Group by author ----
    grouped = normalizer.group_by_author(deduped)
    logger.info("Unique developers: %d", len(grouped))

    # ---- Heuristic analysis ----
    heuristic = HeuristicAnalyzer()

    # ---- AI analysis (optional) ----
    ai_analyzer: Optional[VertexAIAnalyzer] = None
    if not args.no_ai:
        try:
            ai_analyzer = VertexAIAnalyzer(
                project=config.google_cloud_project,
                location=config.google_cloud_location,
                tunnel_url=config.gemini_tunnel_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to initialize Vertex AI (%s). Falling back to heuristic-only mode.",
                exc,
            )

    # ---- Build summaries ----
    summaries = build_developer_summaries(grouped, heuristic, ai_analyzer)

    # ---- Sort by impact score descending ----
    summaries.sort(key=lambda s: s.impact_score, reverse=True)

    # ---- Determine repos list and source label ----
    repos: List[str] = []
    if args.source in ("github", "both") and args.github_repo:
        repos.append(args.github_repo)
    if args.source in ("bitbucket", "both") and args.bitbucket_repo:
        repos.append(args.bitbucket_repo)

    # ---- Generate reports ----
    reporter = ReportGenerator()

    logger.info("Generating console report...")
    reporter.generate_console_report(
        summaries=summaries,
        repos=repos,
        since=since,
        until=until,
        source=args.source,
    )

    logger.info("Generating Markdown report...")
    markdown = reporter.generate_markdown_report(
        summaries=summaries,
        repos=repos,
        since=since,
        until=until,
        source=args.source,
    )

    reporter.save_report(content=markdown, path=args.output)
    print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
