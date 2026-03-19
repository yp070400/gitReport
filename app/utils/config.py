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
    # Tunnel endpoint for Gemini — overrides the default http://localhost/generate
    gemini_tunnel_url: Optional[str] = field(default=None)
    # Proxy URL applied to all outbound HTTP requests (GitHub API + tunnel)
    # e.g. "http://user:pass@proxy-host:8080"
    http_proxy: Optional[str] = field(default=None)
    https_proxy: Optional[str] = field(default=None)

    def proxies(self) -> dict:
        """Return a requests-compatible proxies dict."""
        result = {}
        if self.http_proxy:
            result["http"] = self.http_proxy
        if self.https_proxy:
            result["https"] = self.https_proxy
        # If only one is set, use it for both
        if self.http_proxy and "https" not in result:
            result["https"] = self.http_proxy
        if self.https_proxy and "http" not in result:
            result["http"] = self.https_proxy
        return result


def load_config() -> Config:
    """Load configuration from environment variables.

    Optional environment variables:
        GOOGLE_CLOUD_PROJECT  – GCP project ID (informational; not required for tunnel mode).
        GOOGLE_CLOUD_LOCATION – Vertex AI region label (default: us-central1).
        GITHUB_TOKEN          – Personal access token or fine-grained token for GitHub.
        BITBUCKET_TOKEN       – Bitbucket App Password or access token.
        GEMINI_TUNNEL_URL     – Override the local tunnel endpoint (default: http://localhost/generate).
        HTTP_PROXY            – Proxy URL for HTTP requests  (e.g. http://proxy:8080).
        HTTPS_PROXY           – Proxy URL for HTTPS requests (e.g. http://proxy:8080).

    Returns:
        Populated :class:`Config` instance.
    """
    project: Optional[str] = os.environ.get("GOOGLE_CLOUD_PROJECT") or None
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or "us-central1"
    github_token: Optional[str] = os.environ.get("GITHUB_TOKEN") or None
    bitbucket_token: Optional[str] = os.environ.get("BITBUCKET_TOKEN") or None
    tunnel_url: Optional[str] = os.environ.get("GEMINI_TUNNEL_URL") or None
    http_proxy: Optional[str] = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or None
    https_proxy: Optional[str] = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None

    return Config(
        google_cloud_project=project,
        google_cloud_location=location,
        github_token=github_token,
        bitbucket_token=bitbucket_token,
        gemini_tunnel_url=tunnel_url,
        http_proxy=http_proxy,
        https_proxy=https_proxy,
    )
