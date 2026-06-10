"""Opportunity (pipeline) tools for Twenty MCP."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from appmate_twenty_mcp.client import TwentyClient


def register_opportunity_tools(mcp: FastMCP, client: TwentyClient) -> None:
    """Register opportunity/pipeline-related MCP tools."""

    @mcp.tool()
    def search_opportunities(
        name: str | None = None,
        stage: str | None = None,
        company_id: str | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search opportunities by name, stage, company, or amount range.

        Args:
            name: Partial match on opportunity name.
            stage: Pipeline stage (e.g. "NEW", "MEETING", "PROPOSAL", "WON", "LOST").
            company_id: UUID of linked company.
            min_amount: Minimum amount (in dollars, converted to micros internally).
            max_amount: Maximum amount (in dollars, converted to micros internally).
            limit: Max results (default 20, max 100).
        """
        limit = min(limit, 100)
        filters: list[str] = []
        filter_args: dict[str, Any] = {}

        if name:
            filters.append('name: { ilike: $name }')
            filter_args["name"] = f"%{name}%"
        if stage:
            filters.append('stage: { eq: $stage }')
            filter_args["stage"] = stage
        if company_id:
            filters.append('companyId: { eq: $companyId }')
            filter_args["companyId"] = company_id
        if min_amount is not None:
            filters.append('amount: { gte: $minAmount }')
            filter_args["minAmount"] = str(int(min_amount * 1_000_000))
        if max_amount is not None:
            filters.append('amount: { lte: $maxAmount }')
            filter_args["maxAmount"] = str(int(max_amount * 1_000_000))

        filter_str = ", ".join(filters) if filters else ""
        query = f"""
        query SearchOpportunities({', '.join(f'${k}: String' for k in filter_args)}) {{
          opportunities(first: {limit}{f', filter: {{ {filter_str} }}' if filter_str else ''}) {{
            edges {{
              node {{
                id
                name
                amount
                stage
                closeDate
                probability
                companyId
                pointOfContactId
                createdAt
                updatedAt
              }}
            }}
          }}
        }}
        """
        data = client.graphql(query, filter_args)
        edges = data.get("opportunities", {}).get("edges", [])
        return [e["node"] for e in edges]

    @mcp.tool()
    def create_opportunity(
        name: str,
        stage: str,
        amount: float | None = None,
        company_id: str | None = None,
        point_of_contact_id: str | None = None,
        close_date: str | None = None,
        probability: int | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new pipeline opportunity.

        Args:
            name: Opportunity name.
            stage: Pipeline stage (use list_pipeline_stages to discover values).
            amount: Dollar amount (converted to micros internally).
            company_id: UUID of linked company.
            point_of_contact_id: UUID of linked person.
            close_date: Expected close date (ISO8601).
            probability: 0-100 chance of closing.
            extra_fields: Workspace custom fields → values, passed through verbatim,
                e.g. {"assessmentScore": 84, "riskLevel": "MODERATE",
                "assessmentBrief": {"markdown": "..."}} (RICH_TEXT takes {"markdown"}).
        """
        data_input: dict[str, Any] = {"name": name, "stage": stage}
        data_input.update(extra_fields or {})
        if amount is not None:
            data_input["amount"] = int(amount * 1_000_000)
        if company_id is not None:
            data_input["companyId"] = company_id
        if point_of_contact_id is not None:
            data_input["pointOfContactId"] = point_of_contact_id
        if close_date is not None:
            data_input["closeDate"] = close_date
        if probability is not None:
            data_input["probability"] = probability

        mutation = """
        mutation CreateOpportunity($data: OpportunityCreateInput!) {
          createOpportunity(data: $data) { id name stage amount closeDate }
        }
        """
        result = client.graphql(mutation, {"data": data_input})
        return result.get("createOpportunity", {})

    @mcp.tool()
    def update_opportunity(
        opportunity_id: str,
        name: str | None = None,
        stage: str | None = None,
        amount: float | None = None,
        company_id: str | None = None,
        point_of_contact_id: str | None = None,
        close_date: str | None = None,
        probability: int | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing opportunity by UUID.

        Args:
            opportunity_id: Twenty UUID of the opportunity.
            name: New opportunity name.
            stage: Pipeline stage.
            amount: Dollar amount (converted to micros internally).
            company_id: UUID of linked company.
            point_of_contact_id: UUID of linked person.
            close_date: Expected close date (ISO8601).
            probability: 0-100 chance of closing.
            extra_fields: Workspace custom fields → values, passed through verbatim
                (RICH_TEXT fields take {"markdown": "..."}).
        """
        data_input: dict[str, Any] = {}
        data_input.update(extra_fields or {})
        if name is not None:
            data_input["name"] = name
        if stage is not None:
            data_input["stage"] = stage
        if amount is not None:
            data_input["amount"] = int(amount * 1_000_000)
        if company_id is not None:
            data_input["companyId"] = company_id
        if point_of_contact_id is not None:
            data_input["pointOfContactId"] = point_of_contact_id
        if close_date is not None:
            data_input["closeDate"] = close_date
        if probability is not None:
            data_input["probability"] = probability

        mutation = """
        mutation UpdateOpportunity($id: ID!, $data: OpportunityUpdateInput!) {
          updateOpportunity(id: $id, data: $data) { id name stage amount closeDate updatedAt }
        }
        """
        result = client.graphql(mutation, {"id": opportunity_id, "data": data_input})
        return result.get("updateOpportunity", {})

    @mcp.tool()
    def list_pipeline_stages() -> list[str]:
        """Return the available pipeline stage values for opportunities.

        Stage is a SELECT field on opportunity, not a standalone object — there is
        no `pipelineStages` query in Twenty v2. Discover the values via GraphQL
        enum introspection, falling back to the metadata API for older/renamed
        enum types.
        """
        # Primary: introspect the stage SELECT enum
        query = """
        query StageEnum {
          __type(name: "OpportunityStageEnum") {
            enumValues { name }
          }
        }
        """
        try:
            data = client.graphql(query)
            type_info = data.get("__type")
            if type_info and type_info.get("enumValues"):
                return [v["name"] for v in type_info["enumValues"]]
        except Exception:
            pass

        # Fallback: metadata API — find the opportunity object's stage field options.
        # Response shape varies across Twenty versions; normalize the common ones.
        meta = client.rest_get("/rest/metadata/objects")
        raw = meta.get("data", meta)
        if isinstance(raw, dict):
            raw = raw.get("objects", raw.get("edges", []))
        objects = [o.get("node", o) for o in raw] if isinstance(raw, list) else []
        for obj in objects:
            if obj.get("nameSingular") != "opportunity":
                continue
            fields = obj.get("fields") or obj.get("fieldsList") or []
            fields = [f.get("node", f) for f in fields]
            for field in fields:
                if field.get("name") == "stage":
                    options = field.get("options") or []
                    return [opt.get("value") for opt in options if opt.get("value")]
        return []
