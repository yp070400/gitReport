from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    google_cloud_project: Optional[str] = field(default=None)
    google_cloud_location: str = "us-central1"
    github_token: Optional[str] = field(default=None)
    bitbucket_token: Optional[str] = field(default=None)
    # Tunnel endpoint for Gemini — overrides the default http://localhost:8080/generate
    gemini_tunnel_url: Optional[str] = field(default=None)
    # Bearer token for the tunnel service (AUTH_TOKEN on the server side)
    gemini_tunnel_token: Optional[str] = field(default=None)


def load_config() -> Config:
    """Load configuration from environment variables.

    Optional environment variables:
        GOOGLE_CLOUD_PROJECT  – GCP project ID (informational; not required for tunnel mode).
        GOOGLE_CLOUD_LOCATION – Vertex AI region label (default: us-central1).
        GITHUB_TOKEN          – Personal access token or fine-grained token for GitHub.
        BITBUCKET_TOKEN       – Bitbucket App Password or access token.
        GEMINI_TUNNEL_URL     – Service endpoint (default: https://gal.d1.galileo-eu.dev.gcp.com/generate).
        GEMINI_TUNNEL_TOKEN   – Bearer token for the service (set AUTH_TOKEN on server side).
        BITBUCKET_SERVER_URL  – Bitbucket Server base URL (default: https://stash.gto.db.com).
        BITBUCKET_TOKEN       – Personal Access Token for Bitbucket Server.

    Returns:
        Populated :class:`Config` instance.
    """
    project: Optional[str] = os.environ.get("GOOGLE_CLOUD_PROJECT") or None
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or "us-central1"
    github_token: Optional[str] = os.environ.get("GITHUB_TOKEN") or None
    bitbucket_token: Optional[str] = os.environ.get("BITBUCKET_TOKEN") or None
    tunnel_url: Optional[str] = os.environ.get("GEMINI_TUNNEL_URL") or None
    tunnel_token: Optional[str] = os.environ.get("GEMINI_TUNNEL_TOKEN") or None

    return Config(
        google_cloud_project=project,
        google_cloud_location=location,
        github_token=github_token,
        bitbucket_token=bitbucket_token,
        gemini_tunnel_url=tunnel_url,
        gemini_tunnel_token=tunnel_token,
    )
