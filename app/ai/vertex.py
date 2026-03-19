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

# Default tunnel endpoint — override with GEMINI_TUNNEL_URL env var.
_DEFAULT_TUNNEL_URL = "http://localhost/generate"


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
        proxies: Optional[Dict[str, str]] = None,
    ) -> None:
        """Configure the analyzer to use the local tunnel endpoint.

        Args:
            project:    GCP project ID (informational only; passed through for logging).
            location:   Vertex AI region label (informational only).
            tunnel_url: Override the tunnel endpoint URL. Falls back to the
                        ``GEMINI_TUNNEL_URL`` env var, then ``http://localhost/generate``.
            proxies:    Optional requests-compatible proxy dict,
                        e.g. {"http": "http://proxy:8080", "https": "http://proxy:8080"}.
        """
        self._project = project
        self._location = location
        self._tunnel_url: str = (
            tunnel_url
            or os.environ.get("GEMINI_TUNNEL_URL", _DEFAULT_TUNNEL_URL)
        )
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        if proxies:
            self._session.proxies.update(proxies)
            logger.info("Tunnel client using proxy: %s", proxies)
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
                    json={"prompt": prompt},
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
        """Build the structured prompt sent to Gemini."""
        commit_lines = "\n".join(
            f"- [{c.timestamp.strftime('%Y-%m-%d')}] ({c.repo}) {c.message}"
            for c in recent_commits
        )

        # Format categories for readability
        cat_str = ", ".join(
            f"{k}: {v}" for k, v in sorted(categories.items(), key=lambda x: -x[1]) if v > 0
        ) or "none"

        total = len(all_commits)

        prompt = (
            "You are an engineering impact analyst. "
            "Analyze the following developer's commits and provide a structured assessment.\n\n"
            f"Developer: {author}\n"
            f"Total Commits: {total}\n"
            f"Categories: {cat_str}\n"
            f"Base Heuristic Score: {base_score}/10\n\n"
            f"Recent Commits (up to {_MAX_COMMITS_PER_CALL}):\n"
            f"{commit_lines}\n\n"
            "Respond ONLY with valid JSON in this exact format:\n"
            "{\n"
            '  "impact_score": <float 1-10>,\n'
            '  "summary": "<2-3 sentence summary of developer impact>",\n'
            '  "key_contributions": ["<contribution 1>", "<contribution 2>", "<contribution 3>"],\n'
            '  "themes": ["<theme 1>", "<theme 2>"],\n'
            '  "reasoning": "<brief explanation of score>"\n'
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
