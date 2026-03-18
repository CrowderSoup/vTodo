from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    api_url: str
    api_token: str
    transport: str = "stdio"
    host: str = "0.0.0.0"
    port: int = 8001
    mcp_token: str | None = None


def load_settings() -> Settings:
    parser = argparse.ArgumentParser(description="vtodo MCP server")
    parser.add_argument("--api-url", default=None, help="vtodo API base URL")
    parser.add_argument("--api-token", default=None, help="vtodo API token")
    parser.add_argument("--transport", default=None, help="Transport: stdio or sse")
    parser.add_argument("--host", default=None, help="Host to bind (SSE mode)")
    parser.add_argument("--port", default=None, type=int, help="Port to bind (SSE mode)")
    parser.add_argument("--mcp-token", default=None, help="Bearer token for SSE auth")
    args, _ = parser.parse_known_args()

    api_url = args.api_url or os.environ.get("VTODO_API_URL", "http://localhost:8000")
    api_token = args.api_token or os.environ.get("VTODO_API_TOKEN", "")

    if not api_token:
        raise ValueError(
            "API token is required. Set VTODO_API_TOKEN env var or pass --api-token."
        )

    transport = args.transport or os.environ.get("VTODO_MCP_TRANSPORT", "stdio")
    host = args.host or os.environ.get("VTODO_MCP_HOST", "0.0.0.0")
    port = args.port or int(os.environ.get("VTODO_MCP_PORT", "8001"))
    mcp_token = args.mcp_token or os.environ.get("VTODO_MCP_TOKEN") or None

    return Settings(
        api_url=api_url.rstrip("/"),
        api_token=api_token,
        transport=transport,
        host=host,
        port=port,
        mcp_token=mcp_token,
    )
