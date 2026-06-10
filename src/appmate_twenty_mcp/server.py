"""MCP server entry point for AppMate Twenty CRM bridge.

Usage:
    uv run twenty-mcp
    # or
    python -m appmate_twenty_mcp.server

Environment:
    TWENTY_API_KEY — API key from Settings → API & Webhooks
    TWENTY_BASE_URL — Self-hosted URL (default: https://api.twenty.com)
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from appmate_twenty_mcp.client import TwentyClient
from appmate_twenty_mcp.tools.companies import register_company_tools
from appmate_twenty_mcp.tools.notes import register_note_tools
from appmate_twenty_mcp.tools.opportunities import register_opportunity_tools
from appmate_twenty_mcp.tools.people import register_people_tools
from appmate_twenty_mcp.tools.tasks import register_task_tools
from appmate_twenty_mcp.tools.workspace import register_workspace_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("twenty-mcp")


def create_server() -> FastMCP:
    """Build and configure the MCP server with all Twenty tools."""
    mcp = FastMCP("appmate-twenty-mcp")

    api_key = os.environ.get("TWENTY_API_KEY")
    base_url = os.environ.get("TWENTY_BASE_URL")

    if not api_key:
        logger.error("TWENTY_API_KEY environment variable is required")
        raise SystemExit(1)

    client = TwentyClient(api_key=api_key, base_url=base_url)
    logger.info("Connected to Twenty at %s (workspace %s)", client.base_url, client.workspace_id)

    register_company_tools(mcp, client)
    register_people_tools(mcp, client)
    register_task_tools(mcp, client)
    register_opportunity_tools(mcp, client)
    register_note_tools(mcp, client)
    register_workspace_tools(mcp, client)

    logger.info(
        "Bridge ready with tools: companies, people, tasks, opportunities, notes, workspace"
    )
    return mcp


def main() -> None:
    """Run the MCP server on stdio."""
    mcp = create_server()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
