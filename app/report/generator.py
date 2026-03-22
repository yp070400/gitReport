from __future__ import annotations

import os
import textwrap
from datetime import datetime, timezone
from typing import List

from app.models.commit import DeveloperSummary
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TERM_WIDTH = 80
_SEPARATOR = "=" * _TERM_WIDTH
_THIN_SEP = "-" * _TERM_WIDTH

_CATEGORY_EMOJI = {
    "feature":  "✨",
    "bugfix":   "🐛",
    "refactor": "♻️",
    "infra":    "⚙️",
    "test":     "🧪",
    "docs":     "📝",
}

_RANK_MEDAL = {1: "🥇", 2: "🥈", 3: "🥉"}


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
        lines: List[str] = []

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

        top = summaries[0]
        lines.append(f"  TOP CONTRIBUTOR: {top.author}  (score {top.impact_score:.1f}/10)")
        lines.append(_SEPARATOR)

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

            total_add = sum(c.additions for c in summary.commits)
            total_del = sum(c.deletions for c in summary.commits)
            if total_add or total_del:
                lines.append(f"      Lines  : +{total_add} -{total_del}")

            cat_parts = [
                f"{cat}={cnt}"
                for cat, cnt in sorted(summary.categories.items(), key=lambda x: -x[1])
                if cnt > 0
            ]
            if cat_parts:
                lines.append(f"      Categories: {', '.join(cat_parts)}")

            if summary.ai_summary:
                wrapped = textwrap.fill(
                    summary.ai_summary,
                    width=_TERM_WIDTH - 6,
                    initial_indent="      ",
                    subsequent_indent="      ",
                )
                lines.append(f"\n{wrapped}")

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
        lines: List[str] = []

        # ── Title ──────────────────────────────────────────────────────
        lines.append("# 📊 AI Engineering Impact Report")
        lines.append("")

        # ── Meta banner ────────────────────────────────────────────────
        lines.append('<table><tr>')
        lines.append(f'<td><b>🗂 Source</b></td><td>{source.upper()}</td>')
        lines.append(f'<td><b>📁 Repos</b></td><td>{", ".join(f"<code>{r}</code>" for r in repos)}</td>')
        lines.append(f'<td><b>📅 Period</b></td><td>{_fmt_date(since)} → {_fmt_date(until)}</td>')
        lines.append(f'<td><b>👥 Developers</b></td><td>{len(summaries)}</td>')
        lines.append(f'<td><b>🕒 Generated</b></td><td>{datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</td>')
        lines.append('</tr></table>')
        lines.append("")

        if not summaries:
            lines.append("> ⚠️ No commits found in the specified period.")
            return "\n".join(lines)

        # ── Executive summary ──────────────────────────────────────────
        total_commits = sum(s.total_commits() for s in summaries)
        total_add = sum(c.additions for s in summaries for c in s.commits)
        total_del = sum(c.deletions for s in summaries for c in s.commits)
        high_impact = [s for s in summaries if s.is_high_impact()]
        low_value   = [s for s in summaries if s.is_low_value()]
        avg_score   = sum(s.impact_score for s in summaries) / len(summaries)

        lines.append("## 🔍 Executive Summary")
        lines.append("")
        lines.append('<table><tr>')
        lines.append(f'<td align="center"><b>📝 Total Commits</b><br/><h2>{total_commits}</h2></td>')
        lines.append(f'<td align="center"><b>👥 Contributors</b><br/><h2>{len(summaries)}</h2></td>')
        lines.append(f'<td align="center"><b>➕ Lines Added</b><br/><h2>{total_add:,}</h2></td>')
        lines.append(f'<td align="center"><b>➖ Lines Removed</b><br/><h2>{total_del:,}</h2></td>')
        lines.append(f'<td align="center"><b>⭐ Avg Score</b><br/><h2>{avg_score:.1f}/10</h2></td>')
        lines.append(f'<td align="center"><b>🌟 High Impact</b><br/><h2>{len(high_impact)}</h2></td>')
        lines.append('</tr></table>')
        lines.append("")

        # ── Podium ─────────────────────────────────────────────────────
        lines.append("## 🏆 Leaderboard")
        lines.append("")

        top10 = summaries[:10]
        cols_per_row = 5

        lines.append('<table>')
        for row_start in range(0, len(top10), cols_per_row):
            row_devs = top10[row_start:row_start + cols_per_row]
            lines.append('<tr>')
            for rank_idx, s in enumerate(row_devs, start=row_start + 1):
                medal = _RANK_MEDAL.get(rank_idx, f"#{rank_idx}")
                bar   = _score_bar(s.impact_score)
                lines.append(
                    f'<td align="center" width="20%">'
                    f'{medal}<br/><b>{s.author}</b><br/>'
                    f'<code>{bar}</code><br/>'
                    f'<b>{s.impact_score:.1f}/10</b><br/>'
                    f'<sub>{s.total_commits()} commits</sub>'
                    f'</td>'
                )
            # Pad last row if needed
            for _ in range(cols_per_row - len(row_devs)):
                lines.append('<td></td>')
            lines.append('</tr>')
        lines.append('</table>')
        lines.append("")

        # ── Rankings table ─────────────────────────────────────────────
        lines.append("## 📋 Developer Rankings")
        lines.append("")
        lines.append("| Rank | Developer | Score | Bar | Commits | +Lines | -Lines | Top Category | Themes |")
        lines.append("|:----:|-----------|:-----:|-----|:-------:|-------:|-------:|:------------:|--------|")

        for rank, s in enumerate(summaries, 1):
            medal     = _RANK_MEDAL.get(rank, f"`#{rank}`")
            score_str = _md_score(s.impact_score)
            bar       = f"`{_score_bar(s.impact_score)}`"
            add       = sum(c.additions for c in s.commits)
            dele      = sum(c.deletions for c in s.commits)
            add_str   = f"+{add:,}" if add else "—"
            del_str   = f"-{dele:,}" if dele else "—"
            cat_emoji = _CATEGORY_EMOJI.get(s.dominant_category(), "")
            themes    = ", ".join(s.themes[:2]) if s.themes else "—"
            flag      = " 🌟" if s.is_high_impact() else (" 🔴" if s.is_low_value() else "")
            lines.append(
                f"| {medal} | {s.author}{flag} | {score_str} | {bar} "
                f"| {s.total_commits()} | {add_str} | {del_str} "
                f"| {cat_emoji} {s.dominant_category()} | {themes} |"
            )
        lines.append("")

        # ── Category distribution ──────────────────────────────────────
        lines.append("## 📊 Team Commit Distribution")
        lines.append("")

        all_cats: dict = {}
        for s in summaries:
            for cat, cnt in s.categories.items():
                all_cats[cat] = all_cats.get(cat, 0) + cnt

        total_cat = sum(all_cats.values()) or 1
        lines.append("| Category | Count | Distribution |")
        lines.append("|----------|------:|-------------|")
        for cat, cnt in sorted(all_cats.items(), key=lambda x: -x[1]):
            if cnt == 0:
                continue
            emoji   = _CATEGORY_EMOJI.get(cat, "")
            pct     = cnt / total_cat * 100
            bar_len = int(pct / 5)  # max 20 blocks for 100%
            bar     = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"| {emoji} **{cat}** | {cnt} | `{bar}` {pct:.0f}% |")
        lines.append("")

        # ── Detailed per-developer sections ────────────────────────────
        lines.append("## 🧑‍💻 Detailed Analysis")
        lines.append("")

        for rank, summary in enumerate(summaries, start=1):
            medal = _RANK_MEDAL.get(rank, f"#{rank}")
            flags = []
            if summary.is_high_impact():
                flags.append("🌟 HIGH IMPACT")
            if summary.is_low_value():
                flags.append("🔴 LOW VALUE")
            flag_str = "  " + " · ".join(flags) if flags else ""

            add  = sum(c.additions for c in summary.commits)
            dele = sum(c.deletions for c in summary.commits)

            lines.append(
                f"### {medal} {summary.author}{flag_str}"
            )
            lines.append("")

            # Score bar card
            bar = _score_bar(summary.impact_score)
            lines.append(
                f"> **Impact Score: {summary.impact_score:.1f}/10**  "
                f"`{bar}`  {_tier_label(summary.impact_score)}"
            )
            lines.append("")

            # Stats row
            lines.append('<table><tr>')
            lines.append(f'<td><b>📝 Commits</b><br/>{summary.total_commits()}</td>')
            lines.append(f'<td><b>➕ Added</b><br/>+{add:,}</td>')
            lines.append(f'<td><b>➖ Removed</b><br/>-{dele:,}</td>')
            lines.append(f'<td><b>🏷 Top Category</b><br/>{_CATEGORY_EMOJI.get(summary.dominant_category(),"")} {summary.dominant_category()}</td>')
            lines.append(f'<td><b>🎯 Themes</b><br/>{", ".join(summary.themes) if summary.themes else "—"}</td>')
            lines.append('</tr></table>')
            lines.append("")

            # Category breakdown mini-chart
            if any(v > 0 for v in summary.categories.values()):
                lines.append("**Commit Breakdown:**")
                lines.append("")
                lines.append("| Category | Count | Bar |")
                lines.append("|----------|------:|-----|")
                cat_total = summary.total_commits() or 1
                for cat, cnt in sorted(summary.categories.items(), key=lambda x: -x[1]):
                    if cnt == 0:
                        continue
                    emoji   = _CATEGORY_EMOJI.get(cat, "")
                    pct     = cnt / cat_total * 100
                    bar_len = int(pct / 10)
                    bar_str = "█" * bar_len + "░" * (10 - bar_len)
                    lines.append(f"| {emoji} {cat} | {cnt} | `{bar_str}` {pct:.0f}% |")
                lines.append("")

            # AI Summary
            if summary.ai_summary:
                lines.append("**📌 Impact Summary:**")
                lines.append("")
                lines.append(f"> {summary.ai_summary}")
                lines.append("")

            # Key contributions
            if summary.key_contributions:
                lines.append("**🔑 Key Contributions:**")
                lines.append("")
                for contrib in summary.key_contributions:
                    lines.append(f"- {contrib}")
                lines.append("")

            # Reasoning
            if summary.reasoning:
                lines.append("<details>")
                lines.append("<summary>💡 Score Reasoning</summary>")
                lines.append("")
                lines.append(f"> {summary.reasoning}")
                lines.append("")
                lines.append("</details>")
                lines.append("")

            # Top changed files (if detail available)
            all_files: dict = {}
            for commit in summary.commits:
                for fs in commit.file_stats:
                    key = fs.filename
                    prev = all_files.get(key, (0, 0))
                    all_files[key] = (prev[0] + fs.additions, prev[1] + fs.deletions)

            if all_files:
                top_files = sorted(all_files.items(), key=lambda x: x[1][0] + x[1][1], reverse=True)[:8]
                lines.append("**📂 Most Changed Files:**")
                lines.append("")
                lines.append("| File | +Added | -Removed |")
                lines.append("|------|-------:|---------:|")
                for fname, (fadd, fdel) in top_files:
                    lines.append(f"| `{fname}` | +{fadd} | -{fdel} |")
                lines.append("")

            lines.append("---")
            lines.append("")

        # ── Footer ─────────────────────────────────────────────────────
        lines.append("<sub>")
        lines.append(
            f"Generated by **AI Engineering Impact Analyzer** · "
            f"{datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
            f"Source: {source.upper()}"
        )
        lines.append("</sub>")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def save_report(self, content: str, path: str = "report.md") -> None:
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


def _score_bar(score: float, width: int = 10) -> str:
    """Unicode block progress bar for a 1–10 score."""
    filled = int(round(score / 10 * width))
    return "█" * filled + "░" * (width - filled)


def _tier_label(score: float) -> str:
    if score >= 9.0:
        return "⭐ OUTSTANDING"
    if score >= 8.0:
        return "🌟 EXCELLENT"
    if score >= 6.0:
        return "✅ GOOD"
    if score >= 4.0:
        return "⚠️ AVERAGE"
    return "🔴 LOW"


def _md_score(score: float) -> str:
    if score >= 8.0:
        return f"**{score:.1f}** 🌟"
    if score >= 6.0:
        return f"**{score:.1f}** ✅"
    if score >= 4.0:
        return f"**{score:.1f}** ⚠️"
    return f"**{score:.1f}** 🔴"


def _score_badge(score: float) -> str:
    if score >= 8.0:
        return "[★★★ EXCELLENT]"
    if score >= 6.0:
        return "[★★☆ GOOD]"
    if score >= 4.0:
        return "[★☆☆ AVERAGE]"
    return "[☆☆☆ LOW]"
