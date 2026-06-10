"""Note tools for Twenty MCP — lead briefs and summaries attached to CRM records.

Target relations (company/person/opportunity/custom objects) vary per workspace —
relations can be deactivated or replaced with custom objects in the Data Model.
These tools introspect NoteTargetCreateInput at call time and report unsupported
targets as warnings instead of failing the whole operation. See QUIRKS.md #14.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from appmate_twenty_mcp.client import TwentyClient

STANDARD_TARGET_FIELDS = ("companyId", "personId", "opportunityId")


def register_note_tools(mcp: FastMCP, client: TwentyClient) -> None:
    """Register note-related MCP tools."""

    @mcp.tool()
    def create_note(
        title: str,
        body: str | None = None,
        company_id: str | None = None,
        person_id: str | None = None,
        opportunity_id: str | None = None,
        extra_targets: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a note, optionally attached to CRM records via noteTargets.

        Args:
            title: Note title shown in Twenty list views.
            body: Markdown body (rendered via bodyV2 RICH_TEXT).
            company_id: UUID of company to attach (if workspace supports it).
            person_id: UUID of person to attach (if workspace supports it).
            opportunity_id: UUID of opportunity to attach (if workspace supports it).
            extra_targets: Workspace-specific noteTarget input fields → UUID,
                e.g. {"targetProjectId": "..."} — call get_note_target_fields to discover.

        Unsupported targets are skipped and reported in the returned "warnings" list.
        """
        data_input: dict[str, Any] = {"title": title}
        if body is not None:
            data_input["bodyV2"] = client.body_v2(body)

        mutation = """
        mutation CreateNote($data: NoteCreateInput!) {
          createNote(data: $data) { id title bodyV2 createdAt }
        }
        """
        result = client.graphql(mutation, {"data": data_input})
        note = result.get("createNote", {})
        note_id = note.get("id")

        requested: dict[str, str] = {}
        standard = (company_id, person_id, opportunity_id)
        for field, value in zip(STANDARD_TARGET_FIELDS, standard, strict=True):
            if value:
                requested[field] = value
        requested.update(extra_targets or {})

        if note_id and requested:
            available = client.input_fields("NoteTargetCreateInput")
            warnings: list[str] = []
            targets: list[dict[str, Any]] = []
            for field, target_id in requested.items():
                if field not in available:
                    other = sorted(f for f in available if f.endswith("Id") and f != "noteId")
                    warnings.append(
                        f"noteTarget field '{field}' is not available in this workspace; "
                        f"available targets: {other}"
                    )
                    continue
                targets.append(_link_note(client, note_id, field, target_id))
            if targets:
                note["noteTargets"] = targets
            if warnings:
                note["warnings"] = warnings

        return note

    @mcp.tool()
    def list_notes(
        target_field: str | None = None,
        target_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent notes, optionally filtered by a linked record.

        Args:
            target_field: NoteTarget id field to filter on, e.g. "companyId" or
                "targetProjectId" — call get_note_target_fields to discover.
            target_id: UUID the target_field must equal.
            limit: Max results (default 20, max 100).
        """
        limit = min(limit, 100)
        target_fields = sorted(
            f for f in client.object_fields("NoteTarget") if f.endswith("Id") and f != "noteId"
        )
        if target_field and target_field not in target_fields:
            raise ValueError(
                f"noteTarget field '{target_field}' does not exist in this workspace; "
                f"available: {target_fields}"
            )

        target_selection = "\n".join(target_fields)
        query = f"""
        query ListNotes {{
          notes(first: {limit}, orderBy: {{ createdAt: DescNullsLast }}) {{
            edges {{
              node {{
                id
                title
                bodyV2
                createdAt
                noteTargets {{
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
        data = client.graphql(query)
        edges = data.get("notes", {}).get("edges", [])
        results = [e["node"] for e in edges]

        if target_field and target_id:
            results = [
                n
                for n in results
                if any(
                    t["node"].get(target_field) == target_id
                    for t in n.get("noteTargets", {}).get("edges", [])
                )
            ]
        return results

    @mcp.tool()
    def get_note_target_fields() -> dict[str, list[str]]:
        """Discover which record types notes can attach to in this workspace."""
        create_fields = sorted(
            f
            for f in client.input_fields("NoteTargetCreateInput")
            if f.endswith("Id") and f not in ("id", "noteId")
        )
        return {"note_target_id_fields": create_fields}


def _link_note(
    client: TwentyClient, note_id: str, target_field: str, target_id: str
) -> dict[str, Any]:
    mutation = """
    mutation CreateNoteTarget($data: NoteTargetCreateInput!) {
      createNoteTarget(data: $data) { id }
    }
    """
    result = client.graphql(mutation, {"data": {"noteId": note_id, target_field: target_id}})
    return result.get("createNoteTarget", {})
