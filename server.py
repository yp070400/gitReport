#!/usr/bin/env python3
"""FastAPI backend server for the React dashboard."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.ai.vertex import VertexAIAnalyzer
from app.analyzer.heuristic import HeuristicAnalyzer
from app.analyzer.normalizer import CommitNormalizer
from app.github.client import GitHubClient
from app.report.generator import ReportGenerator
from app.utils.config import load_config
from app.utils.logger import get_logger
from main import build_developer_summaries

logger = get_logger("server")

app = FastAPI(title="AI Engineering Impact Analyzer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    repos: List[str]
    months: int = 3
    source: str = "github"
    github_token: Optional[str] = None
    gemini_token: Optional[str] = None
    no_ai: bool = False
    no_details: bool = False


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/report")
def get_report():
    if not os.path.exists("report.json"):
        return {"error": "No report found. Run a scan first."}
    with open("report.json", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/scan")
def scan(req: ScanRequest):
    config = load_config()

    until = datetime.now(tz=timezone.utc)
    since = until - timedelta(days=req.months * 30)

    all_commits = []

    if req.source in ("github", "both"):
        token = req.github_token or config.github_token
        gh_client = GitHubClient(token=token)
        for repo in req.repos:
            commits = gh_client.fetch_commits(
                repo=repo,
                since=since,
                until=until,
                fetch_details=not req.no_details,
            )
            logger.info("Fetched %d commits from %s", len(commits), repo)
            all_commits.extend(commits)

    if not all_commits:
        return {"error": "No commits found for the specified repos and time range."}

    normalizer = CommitNormalizer()
    normalized = normalizer.normalize_commits(all_commits)
    deduped = normalizer.deduplicate(normalized)
    grouped = normalizer.group_by_author(deduped)

    heuristic = HeuristicAnalyzer()

    ai_analyzer = None
    if not req.no_ai:
        try:
            ai_analyzer = VertexAIAnalyzer(
                project=config.google_cloud_project,
                location=config.google_cloud_location,
                tunnel_url=config.gemini_tunnel_url,
                tunnel_token=req.gemini_token or config.gemini_tunnel_token,
            )
        except Exception as exc:
            logger.warning("Failed to initialize AI analyzer: %s", exc)

    summaries = build_developer_summaries(grouped, heuristic, ai_analyzer)
    summaries.sort(key=lambda s: s.impact_score, reverse=True)

    reporter = ReportGenerator()

    markdown = reporter.generate_markdown_report(
        summaries=summaries, repos=req.repos, since=since, until=until, source=req.source,
    )
    reporter.save_report(content=markdown, path="report.md")

    report_json = reporter.generate_json_report(
        summaries=summaries, repos=req.repos, since=since, until=until, source=req.source,
    )
    reporter.save_json_report(data=report_json, path="report.json")

    return report_json


# Serve React build in production
_dist = os.path.join(os.path.dirname(__file__), "dashboard", "dist")
if os.path.exists(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
