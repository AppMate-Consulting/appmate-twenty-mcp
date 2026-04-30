"""Person (contact) CRUD tools for Twenty MCP.

CRITICAL: GraphQL createPerson/updatePerson silently drops the `emails` field.
We use REST for create/update to avoid this bug.
See QUIRKS.md for details.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from appmate_twenty_mcp.client import TwentyClient


def register_people_tools(mcp: FastMCP, client: TwentyClient) -> None:
    """Register all person-related MCP tools."""

    @mcp.tool()
    def search_people(
        name: str | None = None,
        email: str | None = None,
        company_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search contacts by name, email, or linked company.

        Args:
            name: Partial match on firstName or lastName (case-insensitive).
            email: Partial match on primaryEmail (case-insensitive).
            company_id: Exact company UUID.
            limit: Max results (default 20, max 100).
        """
        limit = min(limit, 100)
        filters: list[str] = []
        filter_args: dict[str, Any] = {}

        if name:
            filters.append('name: { firstName: { ilike: $name }, lastName: { ilike: $name } }')
            filter_args["name"] = f"%{name}%"
        if email:
            filters.append('emails: { primaryEmail: { ilike: $email } }')
            filter_args["email"] = f"%{email}%"
        if company_id:
            filters.append('companyId: { eq: $companyId }')
            filter_args["companyId"] = company_id

        filter_str = ", ".join(filters) if filters else ""
        query = f"""
        query SearchPeople({', '.join(f'${k}: String' for k in filter_args.keys())}) {{
          people(first: {limit}{f', filter: {{ {filter_str} }}' if filter_str else ''}) {{
            edges {{
              node {{
                id
                name {{ firstName lastName }}
                emails
                phones
                jobTitle
                companyId
                city
                createdAt
                updatedAt
              }}
            }}
          }}
        }}
        """
        data = client.graphql(query, filter_args)
        edges = data.get("people", {}).get("edges", [])
        return [e["node"] for e in edges]

    @mcp.tool()
    def create_person(
        first_name: str,
        last_name: str,
        email: str,
        company_id: str | None = None,
        job_title: str | None = None,
        phone: str | None = None,
        city: str | None = None,
        business_unit: str | None = None,
    ) -> dict[str, Any]:
        """Create a contact via REST (avoids GraphQL emails bug).

        Args:
            first_name: Given name.
            last_name: Family name.
            email: Primary email address.
            company_id: UUID of linked company.
            job_title: Role / title.
            phone: Primary phone number.
            city: City name.
            business_unit: SELECT value — must be UPPERCASE.
        """
        payload: dict[str, Any] = {
            "name": {"firstName": first_name, "lastName": last_name},
            "emails": client.emails_field(email),
        }
        if company_id is not None:
            payload["companyId"] = company_id
        if job_title is not None:
            payload["jobTitle"] = job_title
        if phone is not None:
            payload["phones"] = client.phones_field(phone)
        if city is not None:
            payload["city"] = city
        if business_unit is not None:
            payload["businessUnit"] = business_unit

        data = client.rest_post("/rest/people", payload)
        # REST returns { data: { createPerson: { id ... } } }
        return data.get("data", {}).get("createPerson", {})

    @mcp.tool()
    def update_person(
        person_id: str,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        company_id: str | None = None,
        job_title: str | None = None,
        phone: str | None = None,
        city: str | None = None,
        business_unit: str | None = None,
    ) -> dict[str, Any]:
        """Update a contact by UUID via REST.

        Args:
            person_id: Twenty UUID of the person.
            first_name: Given name.
            last_name: Family name.
            email: Primary email address.
            company_id: UUID of linked company.
            job_title: Role / title.
            phone: Primary phone number.
            city: City name.
            business_unit: SELECT value — must be UPPERCASE.
        """
        payload: dict[str, Any] = {}
        if first_name is not None or last_name is not None:
            name: dict[str, str] = {}
            if first_name is not None:
                name["firstName"] = first_name
            if last_name is not None:
                name["lastName"] = last_name
            payload["name"] = name
        if email is not None:
            payload["emails"] = client.emails_field(email)
        if company_id is not None:
            payload["companyId"] = company_id
        if job_title is not None:
            payload["jobTitle"] = job_title
        if phone is not None:
            payload["phones"] = client.phones_field(phone)
        if city is not None:
            payload["city"] = city
        if business_unit is not None:
            payload["businessUnit"] = business_unit

        data = client.rest_patch(f"/rest/people/{person_id}", payload)
        return data.get("data", {}).get("updatePerson", {})

    @mcp.tool()
    def upsert_person(
        email: str,
        first_name: str,
        last_name: str,
        company_id: str | None = None,
        job_title: str | None = None,
        phone: str | None = None,
        city: str | None = None,
        business_unit: str | None = None,
    ) -> dict[str, Any]:
        """Search by email, update if found, create if not.

        Args:
            email: Primary email (used for dedup).
            first_name: Given name.
            last_name: Family name.
            company_id: UUID of linked company.
            job_title: Role / title.
            phone: Primary phone number.
            city: City name.
            business_unit: SELECT value — must be UPPERCASE.
        """
        existing = search_people(email=email, limit=1)
        if existing:
            return update_person(
                person_id=existing[0]["id"],
                first_name=first_name,
                last_name=last_name,
                email=email,
                company_id=company_id,
                job_title=job_title,
                phone=phone,
                city=city,
                business_unit=business_unit,
            )
        return create_person(
            first_name=first_name,
            last_name=last_name,
            email=email,
            company_id=company_id,
            job_title=job_title,
            phone=phone,
            city=city,
            business_unit=business_unit,
        )
