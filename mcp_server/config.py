from __future__ import annotations

import argparse
import os
from dataclasses import dataclass


@dataclass
class Settings:
    api_url: str
    # Only required for stdio transport, where the whole process acts as one
    # fixed vtodo account. sse transport resolves a different account per
    # request via OAuth instead -- see mcp_server/server.py:_VtodoTokenVerifier.
    api_token: str | None
    transport: str = "stdio"
    host: str = "0.0.0.0"
    port: int = 8001
    # The canonical public URL MCP clients use to reach this server's
    # streamable-HTTP endpoint (must include the streamable_http_path, "/mcp"
    # by default). Only meaningful for sse transport, where it becomes the
    # OAuth resource identifier (RFC 8707/9728).
    resource_server_url: str = ""

    @property
    def whoami_url(self) -> str:
        return f"{self.api_url}/api/v1/mcp/whoami/"

    @property
    def issuer_url(self) -> str:
        """The vtodo Django app's OAuth authorization server identity --
        must exactly match the `issuer` django-oauth-toolkit reports at
        /.well-known/oauth-authorization-server (config/urls.py)."""
        return f"{self.api_url}/o"


def load_settings() -> Settings:
    parser = argparse.ArgumentParser(description="vtodo MCP server")
    parser.add_argument("--api-url", default=None, help="vtodo API base URL")
    parser.add_argument("--api-token", default=None, help="vtodo API token (stdio mode only)")
    parser.add_argument("--transport", default=None, help="Transport: stdio or sse")
    parser.add_argument("--host", default=None, help="Host to bind (SSE mode)")
    parser.add_argument("--port", default=None, type=int, help="Port to bind (SSE mode)")
    args, _ = parser.parse_known_args()

    api_url = args.api_url or os.environ.get("VTODO_API_URL", "http://localhost:8000")
    transport = args.transport or os.environ.get("VTODO_MCP_TRANSPORT", "stdio")
    api_token = args.api_token or os.environ.get("VTODO_API_TOKEN") or None

    if transport == "stdio" and not api_token:
        raise ValueError(
            "API token is required for stdio transport. Set VTODO_API_TOKEN env var or pass --api-token."
        )

    host = args.host or os.environ.get("VTODO_MCP_HOST", "0.0.0.0")
    port = args.port or int(os.environ.get("VTODO_MCP_PORT", "8001"))
    resource_server_url = os.environ.get("VTODO_MCP_PUBLIC_URL", f"http://{host}:{port}/mcp")

    return Settings(
        api_url=api_url.rstrip("/"),
        api_token=api_token,
        transport=transport,
        host=host,
        port=port,
        resource_server_url=resource_server_url,
    )
