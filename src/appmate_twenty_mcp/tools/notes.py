"""Note tools for Twenty MCP — lead briefs and summaries attached to CRM records."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from appmate_twenty_mcp.client import TwentyClient


def register_note_tools(mcp: FastMCP, client: TwentyClient) -> None:
    """Register note-related MCP tools."""

    @mcp.tool()
    def create_note(
        title: str,
        body: str | None = None,
        company_id: str | None = None,
        person_id: str | None = None,
        opportunity_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a note, optionally attached to a company, person, and/or opportunity.

        Args:
            title: Note title shown in Twenty list views.
            body: Markdown body (rendered via bodyV2 RICH_TEXT).
            company_id: UUID of company to attach via noteTarget.
            person_id: UUID of person to attach via noteTarget.
            opportunity_id: UUID of opportunity to attach via noteTarget.
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

        targets: list[dict[str, Any]] = []
        if note_id and company_id:
            targets.append(_link_note(client, note_id, "companyId", company_id))
        if note_id and person_id:
            targets.append(_link_note(client, note_id, "personId", person_id))
        if note_id and opportunity_id:
            targets.append(_link_note(client, note_id, "opportunityId", opportunity_id))
        if targets:
            note["noteTargets"] = targets

        return note

    @mcp.tool()
    def list_notes(
        company_id: str | None = None,
        person_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent notes, optionally filtered by linked company or person.

        Args:
            company_id: Only notes attached to this company UUID.
            person_id: Only notes attached to this person UUID.
            limit: Max results (default 20, max 100).
        """
        limit = min(limit, 100)
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
                      companyId
                      personId
                      opportunityId
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

        def _targets(note: dict[str, Any]) -> list[dict[str, Any]]:
            return [t["node"] for t in note.get("noteTargets", {}).get("edges", [])]

        if company_id:
            results = [
                n for n in results if any(t.get("companyId") == company_id for t in _targets(n))
            ]
        if person_id:
            results = [
                n for n in results if any(t.get("personId") == person_id for t in _targets(n))
            ]
        return results


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
