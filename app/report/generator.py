from __future__ import annotations

import os
import textwrap
from datetime import datetime
from typing import List

from app.models.commit import DeveloperSummary
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Terminal width used for console formatting
_TERM_WIDTH = 80
_SEPARATOR = "=" * _TERM_WIDTH
_THIN_SEP = "-" * _TERM_WIDTH


class ReportGenerator:
    """Generates human-readable reports (console + Markdown) from developer summaries."""

    # ------------------------------------------------------------------
    # Console report
    # ------------------------------------------------------------------

    def generate_console_report(
        self,
        summaries: List[DeveloperSummary],
        repos: List[str],
        since: datetime,
        until: datetime,
        source: str,
    ) -> None:
        """Print a formatted impact report to stdout.

        Args:
            summaries: Developer summaries sorted by impact score descending.
            repos:     Repository names that were analyzed.
            since:     Start of the analysis window.
            until:     End of the analysis window.
            source:    Data source label (e.g. "github", "bitbucket", "both").
        """
        lines: List[str] = []

        # ---- Header ----
        lines.append(_SEPARATOR)
        lines.append("  AI ENGINEERING IMPACT ANALYZER")
        lines.append(_SEPARATOR)
        lines.append(f"  Source      : {source.upper()}")
        lines.append(f"  Repositories: {', '.join(repos)}")
        lines.append(f"  Period      : {_fmt_date(since)} → {_fmt_date(until)}")
        lines.append(f"  Developers  : {len(summaries)}")
        lines.append(_SEPARATOR)

        if not summaries:
            lines.append("  No commits found in the specified period.")
            lines.append(_SEPARATOR)
            print("\n".join(lines))
            return

        # ---- Top contributor banner ----
        top = summaries[0]
        lines.append(f"  TOP CONTRIBUTOR: {top.author}  (score {top.impact_score:.1f}/10)")
        lines.append(_SEPARATOR)

        # ---- Per-developer entries ----
        for rank, summary in enumerate(summaries, start=1):
            badge = _score_badge(summary.impact_score)
            flag = ""
            if summary.is_high_impact():
                flag = "  *** HIGH IMPACT ***"
            elif summary.is_low_value():
                flag = "  (low-value)"

            lines.append(f"\n  #{rank}  {summary.author}{flag}")
            lines.append(f"      Score : {summary.impact_score:.1f}/10  {badge}")
            lines.append(f"      Commits: {summary.total_commits()}")

            # Category breakdown
            cat_parts = [
                f"{cat}={cnt}"
                for cat, cnt in sorted(summary.categories.items(), key=lambda x: -x[1])
                if cnt > 0
            ]
            if cat_parts:
                lines.append(f"      Categories: {', '.join(cat_parts)}")

            # AI summary (word-wrapped)
            if summary.ai_summary:
                wrapped = textwrap.fill(
                    summary.ai_summary,
                    width=_TERM_WIDTH - 6,
                    initial_indent="      ",
                    subsequent_indent="      ",
                )
                lines.append(f"\n{wrapped}")

            # Key contributions
            if summary.key_contributions:
                lines.append("\n      Key Contributions:")
                for contrib in summary.key_contributions:
                    wrapped_contrib = textwrap.fill(
                        f"• {contrib}",
                        width=_TERM_WIDTH - 8,
                        initial_indent="        ",
                        subsequent_indent="          ",
                    )
                    lines.append(wrapped_contrib)

            # Themes
            if summary.themes:
                lines.append(f"\n      Themes: {', '.join(summary.themes)}")

            lines.append(f"\n  {_THIN_SEP}")

        lines.append(_SEPARATOR)
        print("\n".join(lines))

    # ------------------------------------------------------------------
    # Markdown report
    # ------------------------------------------------------------------

    def generate_markdown_report(
        self,
        summaries: List[DeveloperSummary],
        repos: List[str],
        since: datetime,
        until: datetime,
        source: str,
    ) -> str:
        """Generate a Markdown-formatted impact report.

        Args:
            summaries: Developer summaries sorted by impact score descending.
            repos:     Repository names that were analyzed.
            since:     Start of the analysis window.
            until:     End of the analysis window.
            source:    Data source label.

        Returns:
            Full Markdown string ready for writing to a file.
        """
        lines: List[str] = []

        # ---- Document header ----
        lines.append("# AI Engineering Impact Analyzer Report")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| **Source** | {source.upper()} |")
        lines.append(f"| **Repositories** | {', '.join(f'`{r}`' for r in repos)} |")
        lines.append(f"| **Period** | {_fmt_date(since)} → {_fmt_date(until)} |")
        lines.append(f"| **Developers** | {len(summaries)} |")
        lines.append(f"| **Generated** | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} |")
        lines.append("")

        if not summaries:
            lines.append("> No commits found in the specified period.")
            return "\n".join(lines)

        # ---- Top contributor ----
        top = summaries[0]
        lines.append(
            f"> **Top Contributor:** {top.author} with a score of "
            f"**{top.impact_score:.1f}/10**"
        )
        lines.append("")

        # ---- Summary table ----
        lines.append("## Developer Rankings")
        lines.append("")
        lines.append("| Rank | Developer | Score | Commits | Dominant Category | Themes |")
        lines.append("|------|-----------|-------|---------|-------------------|--------|")
        for rank, s in enumerate(summaries, 1):
            badge = _md_badge(s.impact_score)
            themes_str = ", ".join(s.themes[:2]) if s.themes else "—"
            lines.append(
                f"| {rank} | {s.author} | {badge} | {s.total_commits()} "
                f"| {s.dominant_category()} | {themes_str} |"
            )
        lines.append("")

        # ---- Detailed sections ----
        lines.append("## Detailed Analysis")
        lines.append("")

        for rank, summary in enumerate(summaries, start=1):
            flag_parts = []
            if summary.is_high_impact():
                flag_parts.append("HIGH IMPACT")
            if summary.is_low_value():
                flag_parts.append("LOW VALUE")
            flag_str = f" _{', '.join(flag_parts)}_" if flag_parts else ""

            lines.append(
                f"### {rank}. {summary.author}{flag_str} "
                f"— Score: **{summary.impact_score:.1f}/10**"
            )
            lines.append("")

            # Metadata table
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| Total Commits | {summary.total_commits()} |")
            lines.append(f"| Dominant Category | {summary.dominant_category()} |")
            lines.append("")

            # Category breakdown
            cat_items = [
                f"- **{cat}**: {cnt}"
                for cat, cnt in sorted(summary.categories.items(), key=lambda x: -x[1])
                if cnt > 0
            ]
            if cat_items:
                lines.append("**Commit Categories:**")
                lines.extend(cat_items)
                lines.append("")

            # AI Summary
            if summary.ai_summary:
                lines.append("**Impact Summary:**")
                lines.append("")
                lines.append(summary.ai_summary)
                lines.append("")

            # Key contributions
            if summary.key_contributions:
                lines.append("**Key Contributions:**")
                lines.append("")
                for contrib in summary.key_contributions:
                    lines.append(f"- {contrib}")
                lines.append("")

            # Themes
            if summary.themes:
                lines.append(f"**Themes:** {', '.join(summary.themes)}")
                lines.append("")

            # Reasoning (when available)
            if summary.reasoning:
                lines.append(f"> _Reasoning: {summary.reasoning}_")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def save_report(self, content: str, path: str = "report.md") -> None:
        """Write *content* to *path*, creating parent directories as needed.

        Args:
            content: Report string to write.
            path:    Destination file path.
        """
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        logger.info("Report saved to: %s", path)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _score_badge(score: float) -> str:
    """Return an ASCII badge representing the score tier."""
    if score >= 8.0:
        return "[★★★ EXCELLENT]"
    if score >= 6.0:
        return "[★★☆ GOOD]"
    if score >= 4.0:
        return "[★☆☆ AVERAGE]"
    return "[☆☆☆ LOW]"


def _md_badge(score: float) -> str:
    """Return a Markdown-friendly score string with emoji indicator."""
    if score >= 8.0:
        return f"**{score:.1f}** 🌟"
    if score >= 6.0:
        return f"**{score:.1f}** ✅"
    if score >= 4.0:
        return f"**{score:.1f}** ⚠️"
    return f"**{score:.1f}** 🔴"
