#!/usr/bin/env python3
"""AI Engineering Impact Analyzer – CLI entry point.

Usage examples::

    python main.py --source=github --github-repo=owner/repo --months=3
    python main.py --source=github --github-repo=owner/repo --no-ai
    python main.py --source=github --github-repo=owner/repo --export-commits=commits.json --no-ai
    python main.py --offline-input=commits.json
    python main.py --offline-input=commits.json --no-ai
"""
from __future__ import annotations

import argparse
import json
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
        required=False,
        default=None,
        choices=["github", "bitbucket", "both"],
        help="Data source(s) to analyze. Not required when using --offline-input.",
    )
    parser.add_argument(
        "--github-repo",
        metavar="OWNER/REPO",
        action="append",
        default=None,
        dest="github_repo",
        help="GitHub repository in owner/repo format. Repeat to scan multiple repos.",
    )
    parser.add_argument(
        "--bitbucket-repo",
        metavar="WORKSPACE/REPO",
        action="append",
        default=None,
        dest="bitbucket_repo",
        help="Bitbucket repository in workspace/repo_slug format. Repeat for multiple.",
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
    parser.add_argument(
        "--export-commits",
        metavar="FILE",
        default=None,
        help="After fetching, save commits to a JSON file for offline AI analysis later.",
    )
    parser.add_argument(
        "--offline-input",
        metavar="FILE",
        default=None,
        help="Skip live fetch — load commits from a previously exported JSON file and run AI analysis.",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        default=False,
        help="Skip per-commit file detail fetch. Faster but classification uses message only.",
    )
    return parser


def textwrap() -> str:
    return (
        "Examples:\n"
        "  python main.py --source=github --github-repo=octocat/Hello-World\n"
        "  python main.py --source=github --github-repo=org/repo --no-ai\n"
        "  python main.py --source=github --github-repo=org/repo --export-commits=commits.json --no-ai\n"
        "  python main.py --offline-input=commits.json\n"
        "  python main.py --offline-input=commits.json --no-ai\n"
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_args(args: argparse.Namespace, config) -> None:  # type: ignore[type-arg]
    """Raise SystemExit with a helpful message on invalid argument combinations."""
    # Offline mode: only need the input file, no source/token checks needed
    if args.offline_input:
        return

    if not args.source:
        _die("--source is required unless --offline-input is used.")

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
        for repo in (args.github_repo or []):
            gh_commits = gh_client.fetch_commits(
                repo=repo,
                since=since,
                until=until,
                fetch_details=not args.no_details,
            )
            logger.info("Fetched %d commits from GitHub repo: %s", len(gh_commits), repo)
            all_commits.extend(gh_commits)

    if args.source in ("bitbucket", "both"):
        logger.info("Connecting to Bitbucket API...")
        bb_client = BitbucketClient(token=config.bitbucket_token)
        for repo in (args.bitbucket_repo or []):
            bb_commits = bb_client.fetch_commits(repo=repo, since=since, until=until)
            logger.info("Fetched %d commits from Bitbucket repo: %s", len(bb_commits), repo)
            all_commits.extend(bb_commits)

    return all_commits


# ---------------------------------------------------------------------------
# Offline export / load helpers
# ---------------------------------------------------------------------------


def export_commits(commits: List[Commit], path: str, repos: List[str], source: str, since: datetime, until: datetime) -> None:
    """Save commits to a JSON file for offline AI analysis."""
    payload = {
        "metadata": {
            "repos": repos,
            "source": source,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "exported_at": datetime.now(tz=timezone.utc).isoformat(),
            "total_commits": len(commits),
        },
        "commits": [c.to_dict() for c in commits],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    logger.info("Exported %d commits to %s", len(commits), path)
    print(f"Commits exported to {path}")


def load_commits(path: str):  # type: ignore[return]
    """Load commits from an exported JSON file.

    Returns:
        Tuple of (commits, repos, source, since, until).
    """
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    meta = payload.get("metadata", {})
    repos: List[str] = meta.get("repos", ["unknown"])
    source: str = meta.get("source", "github")
    since = datetime.fromisoformat(meta.get("since", datetime.now(tz=timezone.utc).isoformat()))
    until = datetime.fromisoformat(meta.get("until", datetime.now(tz=timezone.utc).isoformat()))

    commits = [Commit.from_dict(c) for c in payload.get("commits", [])]
    logger.info("Loaded %d commits from %s (repos: %s, period: %s → %s)", len(commits), path, repos, since.date(), until.date())
    return commits, repos, source, since, until


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

    # =========================================================
    # OFFLINE MODE: load from a previously exported JSON file
    # =========================================================
    if args.offline_input:
        logger.info("Offline mode: loading commits from %s", args.offline_input)
        raw_commits, repos, source, since, until = load_commits(args.offline_input)

        if not raw_commits:
            logger.warning("No commits found in offline file. Exiting.")
            sys.exit(0)

        normalizer = CommitNormalizer()
        normalized = normalizer.normalize_commits(raw_commits)
        deduped = normalizer.deduplicate(normalized)
        grouped = normalizer.group_by_author(deduped)
        logger.info("Unique developers: %d", len(grouped))

        heuristic = HeuristicAnalyzer()
        ai_analyzer: Optional[VertexAIAnalyzer] = None
        if not args.no_ai:
            try:
                ai_analyzer = VertexAIAnalyzer(
                    project=config.google_cloud_project,
                    location=config.google_cloud_location,
                    tunnel_url=config.gemini_tunnel_url,
                    tunnel_token=config.gemini_tunnel_token,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to initialize Vertex AI (%s). Using heuristic-only.", exc)

        summaries = build_developer_summaries(grouped, heuristic, ai_analyzer)
        summaries.sort(key=lambda s: s.impact_score, reverse=True)

        reporter = ReportGenerator()
        reporter.generate_console_report(summaries=summaries, repos=repos, since=since, until=until, source=source)
        markdown = reporter.generate_markdown_report(summaries=summaries, repos=repos, since=since, until=until, source=source)
        reporter.save_report(content=markdown, path=args.output)
        print(f"\nReport saved to {args.output}")

        json_data = reporter.generate_json_report(
            summaries=summaries, repos=repos, since=since, until=until, source=source,
        )
        json_path = args.output.replace(".md", ".json") if args.output.endswith(".md") else args.output + ".json"
        reporter.save_json_report(data=json_data, path=json_path)
        print(f"JSON report saved to {json_path}")
        return

    # =========================================================
    # LIVE MODE: fetch from GitHub / Bitbucket
    # =========================================================

    # ---- Compute date range ----
    until = datetime.now(tz=timezone.utc)
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

    # ---- Export commits to file if requested ----
    if args.export_commits:
        repos_for_export: List[str] = []
        if args.source in ("github", "both"):
            repos_for_export.extend(args.github_repo or [])
        if args.source in ("bitbucket", "both"):
            repos_for_export.extend(args.bitbucket_repo or [])
        export_commits(raw_commits, args.export_commits, repos_for_export, args.source, since, until)

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
    ai_analyzer_live: Optional[VertexAIAnalyzer] = None
    if not args.no_ai:
        try:
            ai_analyzer_live = VertexAIAnalyzer(
                project=config.google_cloud_project,
                location=config.google_cloud_location,
                tunnel_url=config.gemini_tunnel_url,
                tunnel_token=config.gemini_tunnel_token,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to initialize Vertex AI (%s). Falling back to heuristic-only mode.", exc
            )

    # ---- Build summaries ----
    summaries = build_developer_summaries(grouped, heuristic, ai_analyzer_live)

    # ---- Sort by impact score descending ----
    summaries.sort(key=lambda s: s.impact_score, reverse=True)

    # ---- Determine repos list and source label ----
    repos_live: List[str] = []
    if args.source in ("github", "both"):
        repos_live.extend(args.github_repo or [])
    if args.source in ("bitbucket", "both"):
        repos_live.extend(args.bitbucket_repo or [])

    # ---- Generate reports ----
    reporter = ReportGenerator()

    logger.info("Generating console report...")
    reporter.generate_console_report(
        summaries=summaries, repos=repos_live, since=since, until=until, source=args.source,
    )

    logger.info("Generating Markdown report...")
    markdown = reporter.generate_markdown_report(
        summaries=summaries, repos=repos_live, since=since, until=until, source=args.source,
    )

    reporter.save_report(content=markdown, path=args.output)
    print(f"\nReport saved to {args.output}")

    json_data = reporter.generate_json_report(
        summaries=summaries, repos=repos_live, since=since, until=until, source=args.source,
    )
    json_path = args.output.replace(".md", ".json") if args.output.endswith(".md") else args.output + ".json"
    reporter.save_json_report(data=json_data, path=json_path)
    print(f"JSON report saved to {json_path}")


if __name__ == "__main__":
    main()
