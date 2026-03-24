from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

from app.models.commit import Commit
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_COMMITS_PER_CALL = 20
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 2.0  # seconds

# Default service endpoint — override with GEMINI_TUNNEL_URL env var.
_DEFAULT_TUNNEL_URL = "https://gal.d1.galileo-eu.dev.gcp.com/generate"

# Temperature for structured JSON responses — low value keeps output deterministic.
_DEFAULT_TEMPERATURE = 0.2

# System instruction sent with every request to set the AI's persona and output contract.
_SYSTEM_INSTRUCTION = (
    "You are a senior engineering impact analyst with deep expertise in software development, "
    "code quality, and developer productivity. "
    "Your job is to evaluate a developer's commits — including the actual files changed and line diffs — "
    "and produce a fair, evidence-based impact assessment. "
    "Rules:\n"
    "1. Judge impact by WHAT WAS ACTUALLY CHANGED (file paths, line counts, system criticality), "
    "not just the commit message wording. A vague message like 'fix' on a core infrastructure file "
    "may be high impact; a grand message on a comment-only change is low impact.\n"
    "2. Consider breadth (number of files/systems touched), depth (lines changed), "
    "and criticality (infrastructure, security, core business logic vs. docs/tests).\n"
    "3. Be calibrated: scores 8-10 are for genuinely significant contributions; "
    "scores 4-6 are solid everyday work; scores 1-3 indicate minimal or low-quality changes.\n"
    "4. Always respond with valid JSON only — no markdown fences, no prose outside the JSON object."
)


# ---------------------------------------------------------------------------
# Fallback response returned when the AI call fails
# ---------------------------------------------------------------------------

def _fallback_response(base_score: float, author: str) -> Dict[str, Any]:
    return {
        "impact_score": base_score,
        "summary": (
            f"{author}'s contributions were analyzed heuristically. "
            "AI analysis was unavailable at this time."
        ),
        "key_contributions": [
            "Contributions assessed via keyword-based heuristics only."
        ],
        "themes": ["general engineering"],
        "reasoning": "AI analysis failed; heuristic base score used as-is.",
    }


def _extract_text(response_json: Dict[str, Any]) -> Optional[str]:
    """Extract the generated text from the tunnel service response.

    Tries common response shapes in order:
      {"text": "..."}
      {"response": "..."}
      {"content": "..."}
      {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}  (Vertex passthrough)
    """
    if "text" in response_json:
        return str(response_json["text"])
    if "response" in response_json:
        return str(response_json["response"])
    if "content" in response_json and isinstance(response_json["content"], str):
        return response_json["content"]
    # Vertex AI passthrough format
    try:
        return str(
            response_json["candidates"][0]["content"]["parts"][0]["text"]
        )
    except (KeyError, IndexError, TypeError):
        pass
    return None


class VertexAIAnalyzer:
    """Sends prompts to a local Gemini tunnel service and parses the response."""

    def __init__(
        self,
        project: Optional[str],
        location: str,
        tunnel_url: Optional[str] = None,
        tunnel_token: Optional[str] = None,
    ) -> None:
        """Configure the analyzer to use the local tunnel endpoint.

        Args:
            project:      GCP project ID (informational only; passed through for logging).
            location:     Vertex AI region label (informational only).
            tunnel_url:   Override the tunnel endpoint URL. Falls back to the
                          ``GEMINI_TUNNEL_URL`` env var, then ``http://localhost:8080/generate``.
            tunnel_token: Bearer token for the tunnel service. Falls back to the
                          ``GEMINI_TUNNEL_TOKEN`` env var.
        """
        self._project = project
        self._location = location
        self._tunnel_url: str = (
            tunnel_url
            or os.environ.get("GEMINI_TUNNEL_URL", _DEFAULT_TUNNEL_URL)
        )
        self._session = requests.Session()
        headers = {"Content-Type": "application/json"}
        token = tunnel_token or os.environ.get("GEMINI_TUNNEL_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
            logger.info("Tunnel auth token configured.")
        else:
            logger.warning("GEMINI_TUNNEL_TOKEN is not set — tunnel requests will be unauthenticated and may return 401.")
        self._session.headers.update(headers)
        if os.environ.get("DISABLE_SSL_VERIFY", "").lower() in ("1", "true", "yes"):
            self._session.verify = False
            logger.warning("SSL verification disabled (DISABLE_SSL_VERIFY=true).")
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.info(
            "VertexAIAnalyzer initialised — tunnel endpoint: %s (project=%s, location=%s)",
            self._tunnel_url,
            project,
            location,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def analyze_developer(
        self,
        author: str,
        commits: List[Commit],
        categories: Dict[str, int],
        base_score: float,
    ) -> Dict[str, Any]:
        """Run Gemini analysis for a single developer via the tunnel service.

        Args:
            author:     Normalised developer name.
            commits:    All commits attributed to this developer.
            categories: Category counts from heuristic analysis.
            base_score: Heuristic impact score (1-10).

        Returns:
            Dict with keys:
            - ``impact_score`` (float): AI-assigned score 1-10.
            - ``summary`` (str): 2-3 sentence narrative.
            - ``key_contributions`` (list[str]): 3-5 bullet points.
            - ``themes`` (list[str]): Recurring themes.
            - ``reasoning`` (str): Explanation of score.
        """
        recent_commits = sorted(commits, key=lambda c: c.timestamp, reverse=True)[
            :_MAX_COMMITS_PER_CALL
        ]
        prompt = self._build_prompt(author, commits, recent_commits, categories, base_score)

        logger.info(
            "Sending prompt to tunnel (%s) for %s (%d commits, base_score=%.1f)",
            self._tunnel_url,
            author,
            len(commits),
            base_score,
        )

        backoff = _INITIAL_BACKOFF
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                http_response = self._session.post(
                    self._tunnel_url,
                    json={
                        "prompt": prompt,
                        "temperature": _DEFAULT_TEMPERATURE,
                        "system_instruction": _SYSTEM_INSTRUCTION,
                    },
                    timeout=60,
                )
                http_response.raise_for_status()
                response_json: Dict[str, Any] = http_response.json()
                text = _extract_text(response_json)

                if not text:
                    logger.warning(
                        "Tunnel returned no usable text for %s (attempt %d/%d). Body: %.200s",
                        author, attempt, _MAX_RETRIES, http_response.text,
                    )
                else:
                    result = self._parse_response(text)
                    if result:
                        logger.info(
                            "AI analysis complete for %s: score=%.1f",
                            author,
                            result.get("impact_score", base_score),
                        )
                        return result
                    logger.warning(
                        "Could not parse AI response for %s (attempt %d/%d). Retrying.",
                        author, attempt, _MAX_RETRIES,
                    )

            except requests.exceptions.ConnectionError:
                logger.warning(
                    "Could not connect to tunnel at %s (attempt %d/%d). "
                    "Is the tunnel running?",
                    self._tunnel_url, attempt, _MAX_RETRIES,
                )
            except requests.exceptions.Timeout:
                logger.warning(
                    "Tunnel request timed out for %s (attempt %d/%d).",
                    author, attempt, _MAX_RETRIES,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Tunnel call failed for %s (attempt %d/%d): %s",
                    author, attempt, _MAX_RETRIES, exc,
                )

            if attempt < _MAX_RETRIES:
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

        logger.error(
            "All %d tunnel attempts failed for %s. Using heuristic fallback.",
            _MAX_RETRIES,
            author,
        )
        return _fallback_response(base_score, author)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        author: str,
        all_commits: List[Commit],
        recent_commits: List[Commit],
        categories: Dict[str, int],
        base_score: float,
    ) -> str:
        """Build the structured prompt sent to Gemini.

        Includes both commit messages AND file-level change context when available,
        so the AI can reason beyond potentially misleading commit messages.
        """
        has_file_detail = any(c.has_detail for c in recent_commits)
        total_additions = sum(c.additions for c in all_commits)
        total_deletions = sum(c.deletions for c in all_commits)

        # Build per-commit block
        commit_blocks: List[str] = []
        for c in recent_commits:
            block = f"- [{c.timestamp.strftime('%Y-%m-%d')}] ({c.repo}) {c.message}"
            if c.has_detail:
                block += f"  (+{c.additions} -{c.deletions} lines, {len(c.file_stats)} file(s))"
                detail = c.file_detail_summary(max_files=5)
                if detail:
                    block += f"\n{detail}"
            commit_blocks.append(block)

        commit_section = "\n".join(commit_blocks)

        # Category summary
        cat_str = ", ".join(
            f"{k}: {v}" for k, v in sorted(categories.items(), key=lambda x: -x[1]) if v > 0
        ) or "none"

        total = len(all_commits)

        # Build file-context note
        file_context_note = ""
        if has_file_detail:
            file_context_note = (
                f"Total lines changed across all commits: +{total_additions} -{total_deletions}\n"
                "Note: File paths and line counts are provided alongside messages — "
                "use BOTH the actual file changes AND the commit message to assess impact. "
                "Do NOT rely solely on the commit message wording as it may be imprecise.\n\n"
            )
        else:
            file_context_note = (
                "Note: File-level detail was not available for this analysis. "
                "Classification is based on commit messages only.\n\n"
            )

        prompt = (
            f"Analyze the engineering impact of developer: {author}\n\n"
            f"Period stats:\n"
            f"  Total commits  : {total}\n"
            f"  Categories     : {cat_str}\n"
            f"  Heuristic score: {base_score}/10 (use as a reference, not a constraint)\n\n"
            f"{file_context_note}"
            f"Commits (most recent first, up to {_MAX_COMMITS_PER_CALL}):\n"
            f"{commit_section}\n\n"
            "Return ONLY this JSON object:\n"
            "{\n"
            '  "impact_score": <float 1.0-10.0>,\n'
            '  "summary": "<2-3 sentences describing this developer\'s overall impact and work quality>",\n'
            '  "key_contributions": ["<specific contribution referencing actual files/systems>", ...],\n'
            '  "themes": ["<theme 1>", "<theme 2>"],\n'
            '  "reasoning": "<cite specific commits, files, or patterns that drove your score>"\n'
            "}"
        )
        return prompt

    @staticmethod
    def _parse_response(text: str) -> Optional[Dict[str, Any]]:
        """Extract and validate the JSON payload from Gemini's response.

        Gemini sometimes wraps JSON in a markdown code fence; we strip it
        before attempting to parse.

        Args:
            text: Raw text returned by the model.

        Returns:
            Parsed dict if successful, ``None`` otherwise.
        """
        if not text:
            return None

        # Strip markdown code fences if present
        stripped = text.strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", stripped)
        if fence_match:
            stripped = fence_match.group(1).strip()
        else:
            # Try to extract the first {...} block
            brace_match = re.search(r"\{[\s\S]+\}", stripped)
            if brace_match:
                stripped = brace_match.group(0)

        try:
            data: Dict[str, Any] = json.loads(stripped)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("JSON parse error: %s | Raw text: %.200s", exc, text)
            return None

        # Validate required fields and types
        required_keys = {"impact_score", "summary", "key_contributions", "themes", "reasoning"}
        if not required_keys.issubset(data.keys()):
            missing = required_keys - data.keys()
            logger.debug("AI response missing keys: %s", missing)
            return None

        # Coerce / clamp score
        try:
            score = float(data["impact_score"])
            data["impact_score"] = round(max(1.0, min(10.0, score)), 2)
        except (TypeError, ValueError):
            logger.debug("Could not coerce impact_score: %r", data.get("impact_score"))
            return None

        # Ensure list fields are actually lists
        for list_key in ("key_contributions", "themes"):
            if not isinstance(data[list_key], list):
                data[list_key] = [str(data[list_key])]

        # Ensure string fields are strings
        for str_key in ("summary", "reasoning"):
            if not isinstance(data[str_key], str):
                data[str_key] = str(data[str_key])

        return data
