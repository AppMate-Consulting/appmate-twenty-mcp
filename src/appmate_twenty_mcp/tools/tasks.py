"""Task and activity tools for Twenty MCP."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from appmate_twenty_mcp.client import TwentyClient


def register_task_tools(mcp: FastMCP, client: TwentyClient) -> None:
    """Register task-related MCP tools."""

    @mcp.tool()
    def create_task(
        title: str,
        body: str | None = None,
        assignee_id: str | None = None,
        company_id: str | None = None,
        person_id: str | None = None,
        due_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a task linked to a company, person, or standalone.

        Args:
            title: Stable task title (avoid dynamic data in title — put it in body).
            body: Task description / markdown body.
            assignee_id: UUID of workspace member to assign.
            company_id: UUID of linked company (creates taskTarget).
            person_id: UUID of linked person (creates taskTarget).
            due_at: Due date (ISO8601, e.g. "2026-05-01T09:00:00.000Z").
        """
        data_input: dict[str, Any] = {"title": title}
        if body is not None:
            data_input["bodyV2"] = client.body_v2(body)
        if assignee_id is not None:
            data_input["assigneeId"] = assignee_id
        if due_at is not None:
            data_input["dueAt"] = due_at

        mutation = """
        mutation CreateTask($data: TaskCreateInput!) {
          createTask(data: $data) { id title bodyV2 dueAt assigneeId }
        }
        """
        result = client.graphql(mutation, {"data": data_input})
        task = result.get("createTask", {})
        task_id = task.get("id")

        # Link task to targets via createTaskTarget
        if task_id and company_id:
            _link_task_to_company(client, task_id, company_id)
        if task_id and person_id:
            _link_task_to_person(client, task_id, person_id)

        return task

    @mcp.tool()
    def list_tasks(
        assignee_id: str | None = None,
        company_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filtering.

        Args:
            assignee_id: Filter by assignee UUID.
            company_id: Filter by linked company UUID.
            limit: Max results (default 20, max 100).
        """
        limit = min(limit, 100)
        filters: list[str] = []
        filter_args: dict[str, Any] = {}

        if assignee_id:
            filters.append("assigneeId: { eq: $assigneeId }")
            filter_args["assigneeId"] = assignee_id

        filter_str = f", filter: {{ {', '.join(filters)} }}" if filters else ""
        query = f"""
        query ListTasks({', '.join(f'${k}: String' for k in filter_args)}) {{
          tasks(first: {limit}{filter_str}) {{
            edges {{
              node {{
                id
                title
                bodyV2
                dueAt
                status
                assigneeId
                taskTargets {{
                  edges {{
                    node {{
                      id
                      companyId
                      personId
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        data = client.graphql(query, filter_args)
        edges = data.get("tasks", {}).get("edges", [])
        results = [e["node"] for e in edges]

        if company_id:
            results = [
                t for t in results
                if any(
                    te["node"].get("companyId") == company_id
                    for te in t.get("taskTargets", {}).get("edges", [])
                )
            ]
        return results


def _link_task_to_company(client: TwentyClient, task_id: str, company_id: str) -> dict[str, Any]:
    mutation = """
    mutation CreateTaskTarget($data: TaskTargetCreateInput!) {
      createTaskTarget(data: $data) { id }
    }
    """
    return client.graphql(mutation, {"data": {"taskId": task_id, "companyId": company_id}})


def _link_task_to_person(client: TwentyClient, task_id: str, person_id: str) -> dict[str, Any]:
    mutation = """
    mutation CreateTaskTarget($data: TaskTargetCreateInput!) {
      createTaskTarget(data: $data) { id }
    }
    """
    return client.graphql(mutation, {"data": {"taskId": task_id, "personId": person_id}})
