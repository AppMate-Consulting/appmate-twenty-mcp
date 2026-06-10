"""Workspace tools for Twenty MCP — member lookup for task assignment."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from appmate_twenty_mcp.client import TwentyClient


def register_workspace_tools(mcp: FastMCP, client: TwentyClient) -> None:
    """Register workspace-related MCP tools."""

    @mcp.tool()
    def list_workspace_members() -> list[dict[str, Any]]:
        """List workspace members (id, name, email) — use the id as assignee_id for tasks."""
        query = """
        query ListWorkspaceMembers {
          workspaceMembers(first: 100) {
            edges {
              node {
                id
                name { firstName lastName }
                userEmail
              }
            }
          }
        }
        """
        data = client.graphql(query)
        edges = data.get("workspaceMembers", {}).get("edges", [])
        members = []
        for e in edges:
            node = e["node"]
            name = node.get("name") or {}
            members.append(
                {
                    "id": node.get("id"),
                    "name": f"{name.get('firstName', '')} {name.get('lastName', '')}".strip(),
                    "email": node.get("userEmail"),
                }
            )
        return members
