from __future__ import annotations

import argparse
import os
from dataclasses import dataclass


@dataclass
class Settings:
    api_url: str
    api_token: str


def load_settings() -> Settings:
    parser = argparse.ArgumentParser(description="vtodo MCP server")
    parser.add_argument("--api-url", default=None, help="vtodo API base URL")
    parser.add_argument("--api-token", default=None, help="vtodo API token")
    args, _ = parser.parse_known_args()

    api_url = args.api_url or os.environ.get("VTODO_API_URL", "http://localhost:8000")
    api_token = args.api_token or os.environ.get("VTODO_API_TOKEN", "")

    if not api_token:
        raise ValueError(
            "API token is required. Set VTODO_API_TOKEN env var or pass --api-token."
        )

    return Settings(api_url=api_url.rstrip("/"), api_token=api_token)
