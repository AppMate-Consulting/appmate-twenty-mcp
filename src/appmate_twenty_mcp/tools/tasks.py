"""Task and activity tools for Twenty MCP.

Target relations (company/person/custom objects) vary per workspace — relations
can be deactivated or replaced with custom objects in the Data Model. These tools
introspect TaskTargetCreateInput at call time and report unsupported targets as
warnings instead of failing the whole operation. See QUIRKS.md #14.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from appmate_twenty_mcp.client import TwentyClient

STANDARD_TARGET_FIELDS = ("companyId", "personId")


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
        extra_targets: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a task, optionally linked to CRM records via taskTargets.

        Args:
            title: Stable task title (avoid dynamic data in title — put it in body).
            body: Task description / markdown body.
            assignee_id: UUID of workspace member to assign (see list_workspace_members).
            company_id: UUID of linked company (if workspace supports it).
            person_id: UUID of linked person (if workspace supports it).
            due_at: Due date (ISO8601, e.g. "2026-05-01T09:00:00.000Z").
            extra_targets: Workspace-specific taskTarget input fields → UUID,
                e.g. {"targetProjectId": "..."} — call get_task_target_fields to discover.

        Unsupported targets are skipped and reported in the returned "warnings" list.
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

        requested: dict[str, str] = {}
        for field, value in zip(STANDARD_TARGET_FIELDS, (company_id, person_id), strict=True):
            if value:
                requested[field] = value
        requested.update(extra_targets or {})

        if task_id and requested:
            available = client.input_fields("TaskTargetCreateInput")
            warnings: list[str] = []
            targets: list[dict[str, Any]] = []
            for field, target_id in requested.items():
                if field not in available:
                    other = sorted(f for f in available if f.endswith("Id") and f != "taskId")
                    warnings.append(
                        f"taskTarget field '{field}' is not available in this workspace; "
                        f"available targets: {other}"
                    )
                    continue
                targets.append(_link_task(client, task_id, field, target_id))
            if targets:
                task["taskTargets"] = targets
            if warnings:
                task["warnings"] = warnings

        return task

    @mcp.tool()
    def list_tasks(
        assignee_id: str | None = None,
        target_field: str | None = None,
        target_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filtering.

        Args:
            assignee_id: Filter by assignee UUID.
            target_field: TaskTarget id field to filter on, e.g. "companyId" or
                "targetProjectId" — call get_task_target_fields to discover.
            target_id: UUID the target_field must equal.
            limit: Max results (default 20, max 100).
        """
        limit = min(limit, 100)
        target_fields = sorted(
            f for f in client.object_fields("TaskTarget") if f.endswith("Id") and f != "taskId"
        )
        if target_field and target_field not in target_fields:
            raise ValueError(
                f"taskTarget field '{target_field}' does not exist in this workspace; "
                f"available: {target_fields}"
            )

        filters: list[str] = []
        filter_args: dict[str, Any] = {}
        if assignee_id:
            filters.append("assigneeId: { eq: $assigneeId }")
            filter_args["assigneeId"] = assignee_id

        filter_str = f", filter: {{ {', '.join(filters)} }}" if filters else ""
        target_selection = "\n".join(target_fields)
        query = f"""
        query ListTasks({", ".join(f"${k}: String" for k in filter_args)}) {{
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
                      {target_selection}
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

        if target_field and target_id:
            results = [
                t
                for t in results
                if any(
                    te["node"].get(target_field) == target_id
                    for te in t.get("taskTargets", {}).get("edges", [])
                )
            ]
        return results

    @mcp.tool()
    def get_task_target_fields() -> dict[str, list[str]]:
        """Discover which record types tasks can attach to in this workspace."""
        create_fields = sorted(
            f
            for f in client.input_fields("TaskTargetCreateInput")
            if f.endswith("Id") and f not in ("id", "taskId")
        )
        return {"task_target_id_fields": create_fields}


def _link_task(
    client: TwentyClient, task_id: str, target_field: str, target_id: str
) -> dict[str, Any]:
    mutation = """
    mutation CreateTaskTarget($data: TaskTargetCreateInput!) {
      createTaskTarget(data: $data) { id }
    }
    """
    result = client.graphql(mutation, {"data": {"taskId": task_id, target_field: target_id}})
    return result.get("createTaskTarget", {})
