# AppMate Twenty MCP Bridge

Production-grade [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for [Twenty CRM](https://twenty.com) — built for self-hosted instances with real-world quirks handled.

## Why Not the Community Server?

The community `jezweb/twenty-mcp` is a good starting point for Twenty Cloud, but self-hosted instances behind Cloudflare and with custom objects hit walls it doesn't handle. See [QUIRKS.md](QUIRKS.md) for the full breakdown of edge cases this bridge solves.

**Key differences:**
- Cloudflare bot detection workaround
- JWT workspace extraction + `x-request-metadata` header
- GraphQL vs REST per-operation (Person CRUD uses REST to avoid the `emails` silent-drop bug)
- Built-in rate limit throttling
- Upsert helpers for idempotent syncs

## Quick Start

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for package management
- A Twenty CRM API key (Settings → API & Webhooks)

### Installation

```bash
git clone https://github.com/AppMate-Consulting/appmate-twenty-mcp.git
cd appmate-twenty-mcp
uv sync
```

### Environment

```bash
export TWENTY_API_KEY="your-jwt-api-key"
export TWENTY_BASE_URL="https://crm.yourdomain.com"   # omit for Twenty Cloud
```

### Run the Server

```bash
uv run twenty-mcp
```

The server starts on stdio and waits for MCP tool calls from your agent.

### Connect from Hermes

Add to your `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  twenty-crm:
    command:
      - "uv"
      - "run"
      - "--project"
      - "/path/to/appmate-twenty-mcp"
      - "python"
      - "-m"
      - "appmate_twenty_mcp.server"
    env:
      TWENTY_API_KEY: "${TWENTY_API_KEY}"
      TWENTY_BASE_URL: "${TWENTY_BASE_URL}"
```

Restart Hermes. The bridge will be available as a native MCP toolset.

## Available Tools

### Companies
- `search_companies` — by name, domain, business unit
- `get_company_by_id` — full record with contacts
- `create_company` / `update_company`
- `upsert_company` — search then create-or-update

### People (Contacts)
- `search_people` — by name, email, company
- `create_person` / `update_person` — via REST (avoids GraphQL email bug)
- `upsert_person` — dedup by email

### Tasks
- `create_task` — with optional company/person linking
- `list_tasks` — filter by assignee or company

### Opportunities
- `search_opportunities` — by stage, company, amount range
- `create_opportunity` / `update_opportunity`
- `list_pipeline_stages` — discover available stage values (enum introspection; stage is a SELECT field, not an object)

### Notes
- `create_note` — markdown note, optionally attached to company/person/opportunity via noteTargets
- `list_notes` — recent notes, filter by linked company or person

### Workspace
- `list_workspace_members` — id/name/email; use the id as `assignee_id` when creating tasks

## Architecture

```
Hermes / Claude / Any MCP host
    │
    └──▶ stdio
         │
    appmate-twenty-mcp (Python / FastMCP)
         │
    ┌───────┐
 GraphQL   REST
    │       │
    └──────┘
         │
    Twenty CRM (self-hosted)
```

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Lint
ruff check src

# Type check
pyright

# Test
pytest
```

## License

MIT — AppMate Consulting
