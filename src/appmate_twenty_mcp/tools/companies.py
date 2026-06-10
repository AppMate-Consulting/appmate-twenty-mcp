"""Company CRUD tools for Twenty MCP."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from appmate_twenty_mcp.client import TwentyClient


def register_company_tools(mcp: FastMCP, client: TwentyClient) -> None:
    """Register all company-related MCP tools."""

    @mcp.tool()
    def search_companies(
        name: str | None = None,
        domain_name: str | None = None,
        business_unit: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search companies by name, domain, or business unit.

        Args:
            name: Company name (partial, case-insensitive).
            domain_name: Website domain (e.g. "appmate.com.au").
            business_unit: Filter by SELECT field value (e.g. "SCULPTURE_GC").
            limit: Max results (default 20, max 100).
        """
        limit = min(limit, 100)
        filters: list[str] = []
        filter_args: dict[str, Any] = {}

        if name:
            filters.append('name: { ilike: $name }')
            filter_args["name"] = f"%{name}%"
        if domain_name:
            filters.append('domainName: { ilike: $domainName }')
            filter_args["domainName"] = f"%{domain_name}%"
        if business_unit:
            filters.append('businessUnit: { eq: $businessUnit }')
            filter_args["businessUnit"] = business_unit

        filter_str = ", ".join(filters) if filters else ""
        query = f"""
        query SearchCompanies({', '.join(f'${k}: String' for k in filter_args)}) {{
          companies(first: {limit}{f', filter: {{ {filter_str} }}' if filter_str else ''}) {{
            edges {{
              node {{
                id
                name
                domainName
                businessUnit
                address
                employees
                annualRecurringRevenue
                idealCustomerProfile
                createdAt
                updatedAt
              }}
            }}
          }}
        }}
        """
        data = client.graphql(query, filter_args)
        edges = data.get("companies", {}).get("edges", [])
        return [e["node"] for e in edges]

    @mcp.tool()
    def get_company_by_id(company_id: str) -> dict[str, Any]:
        """Fetch a single company by UUID with full detail including contacts.

        Args:
            company_id: Twenty UUID of the company.
        """
        query = """
        query GetCompany($id: UUID!) {
          companies(filter: { id: { eq: $id } }, first: 1) {
            edges {
              node {
                id
                name
                domainName
                businessUnit
                address
                employees
                annualRecurringRevenue
                idealCustomerProfile
                createdAt
                updatedAt
                companyGroup { id name }
                people { edges { node { id name { firstName lastName } emails } } }
              }
            }
          }
        }
        """
        data = client.graphql(query, {"id": company_id})
        edges = data.get("companies", {}).get("edges", [])
        return edges[0]["node"] if edges else {}

    @mcp.tool()
    def create_company(
        name: str,
        business_unit: str | None = None,
        domain_name: str | None = None,
        address: str | None = None,
        employees: int | None = None,
    ) -> dict[str, Any]:
        """Create a new company record.

        Args:
            name: Company name (required).
            business_unit: SELECT value — must be UPPERCASE (e.g. "SCULPTURE_GC").
            domain_name: Website domain.
            address: Full address string.
            employees: Headcount.
        """
        data_input: dict[str, Any] = {"name": name}
        if business_unit is not None:
            data_input["businessUnit"] = business_unit
        if domain_name is not None:
            data_input["domainName"] = domain_name
        if address is not None:
            data_input["address"] = address
        if employees is not None:
            data_input["employees"] = employees

        mutation = """
        mutation CreateCompany($data: CompanyCreateInput!) {
          createCompany(data: $data) { id name domainName businessUnit createdAt }
        }
        """
        data = client.graphql(mutation, {"data": data_input})
        return data.get("createCompany", {})

    @mcp.tool()
    def update_company(
        company_id: str,
        name: str | None = None,
        business_unit: str | None = None,
        domain_name: str | None = None,
        address: str | None = None,
        employees: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing company by UUID.

        Args:
            company_id: Twenty UUID of the company.
            name: New company name.
            business_unit: SELECT value — must be UPPERCASE.
            domain_name: Website domain.
            address: Full address string.
            employees: Headcount.
        """
        data_input: dict[str, Any] = {}
        if name is not None:
            data_input["name"] = name
        if business_unit is not None:
            data_input["businessUnit"] = business_unit
        if domain_name is not None:
            data_input["domainName"] = domain_name
        if address is not None:
            data_input["address"] = address
        if employees is not None:
            data_input["employees"] = employees

        mutation = """
        mutation UpdateCompany($id: ID!, $data: CompanyUpdateInput!) {
          updateCompany(id: $id, data: $data) { id name domainName businessUnit updatedAt }
        }
        """
        data = client.graphql(mutation, {"id": company_id, "data": data_input})
        return data.get("updateCompany", {})

    @mcp.tool()
    def upsert_company(
        name: str,
        business_unit: str | None = None,
        domain_name: str | None = None,
        address: str | None = None,
        employees: int | None = None,
    ) -> dict[str, Any]:
        """Search by name, update if found, create if not. Returns the record.

        Args:
            name: Company name to match (exact).
            business_unit: SELECT value — must be UPPERCASE.
            domain_name: Website domain.
            address: Full address string.
            employees: Headcount.
        """
        existing = search_companies(name=name, limit=1)
        if existing:
            return update_company(
                company_id=existing[0]["id"],
                name=name,
                business_unit=business_unit,
                domain_name=domain_name,
                address=address,
                employees=employees,
            )
        return create_company(
            name=name,
            business_unit=business_unit,
            domain_name=domain_name,
            address=address,
            employees=employees,
        )
