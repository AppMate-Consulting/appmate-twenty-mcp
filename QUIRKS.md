# Twenty CRM Quirks & Workarounds

This document is the handover artefact for installing `appmate-twenty-mcp` on a self-hosted Twenty instance. It explains why this bridge exists instead of using the community `jezweb/twenty-mcp` server, and what edge cases are handled automatically.

> Origin: Every workaround below was discovered through production failures against 
> a self-hosted Twenty instance behind Cloudflare with JWT workspace keys and 
> custom objects.

---

## 1. Cloudflare Bot Detection — HTTP 403 "Error 1010"

### Symptom
Every API request returns `HTTP 403 Error 1010: Access denied` regardless of API key validity.

### Root Cause
Twenty's default self-hosted install sits behind Cloudflare. Cloudflare blocks Python's default `urllib` user-agent and many programmatic HTTP libraries.

### Fix
Override the `User-Agent` header on every request:

```http
User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36
```

**Where we handle it:** `client.py` — injected into every GraphQL and REST request via `httpx.Client` base headers.

**Community server status:** `jezweb/twenty-mcp` does **not** set this header. It would fail immediately against a Cloudflare-protected instance.

---

## 2. Workspace Discovery — JWT Payload Extraction

### Symptom
Requests return `HTTP 401 "Workspace not found"` even with a valid API key.

### Root Cause
Twenty API keys are JWTs. The workspace ID is embedded in the JWT payload, not the key string itself. The API requires the workspace ID via a custom header.

### Fix
1. Split the JWT on `.`
2. Base64-decode the payload segment
3. Extract `workspaceId`
4. Encode it as base64 JSON in the `x-request-metadata` header:

```python
import base64, json

payload = json.loads(base64.urlsafe_b64decode(jwt_payload_part))
workspace_id = payload["workspaceId"]

headers["x-request-metadata"] = base64.b64encode(
    json.dumps({"workspaceId": workspace_id}).encode()
).decode()
```

**Where we handle it:** `client.py` in `TwentyClient.__init__()` — automatic on every request.

**Community server status:** `jezweb/twenty-mcp` does **not** set this header. It only passes `Authorization` and `Content-Type`.

---

## 3. GraphQL vs REST Per-Operation

### The Rule
Some operations work in GraphQL. Others silently fail or drop fields in GraphQL and **must** use REST.

| Operation | Preferred API | Why |
|-----------|---------------|-----|
| `createCompany` / `updateCompany` | GraphQL | Works correctly |
| `createPerson` / `updatePerson` | **REST** | GraphQL silently drops `emails` field even when passed as a composite object |
| `createTask` / `listTasks` | GraphQL | Works correctly |
| `createOpportunity` / `updateOpportunity` | GraphQL | Works correctly |
| `createTaskTarget` (link task → company/person) | GraphQL | Polymorphic relation, only GraphQL exposes it |

### The `emails` Bug (Person via GraphQL)

**Wrong:**
```graphql
mutation {
  createPerson(data: {
    name: { firstName: "Brad", lastName: "Legassick" },
    emails: { primaryEmail: "brad@example.com", additionalEmails: [] }
  }) { id }
}
```
This creates the person with `emails: null`. No error. The field just vanishes.

**Right:**
```http
POST /rest/people
{
  "name": { "firstName": "Brad", "lastName": "Legassick" },
  "emails": { "primaryEmail": "brad@example.com", "additionalEmails": [] }
}
```

**Where we handle it:** `tools/people.py` — `create_person` and `update_person` always use REST.

**Community server status:** Unknown — if `jezweb/twenty-mcp` uses GraphQL for people, it has this bug.

---

## 4. Composite Field Shapes

### Person Fields
These require **object payloads**, not plain strings:

| Field | Shape |
|-------|-------|
| `emails` | `{"primaryEmail": "...", "additionalEmails": []}` |
| `phones` | `{"primaryPhoneNumber": "...", "primaryPhoneCountryCode": "AU", "primaryPhoneCallingCode": "+61", "additionalPhones": []}` |
| `xLink` | `{"primaryLinkLabel": "", "primaryLinkUrl": "", "secondaryLinks": []}` |

### Querying Composite Fields
In GraphQL, query them as **scalars** (returns the full object), not with subfields:

**Wrong:**
```graphql
query { people { edges { node { emails { primaryEmail } } } } }
# → "Sub field metadata not found for composite type: EMAILS"
```

**Right:**
```graphql
query { people { edges { node { emails } } } }
# → returns full object: { "primaryEmail": "...", "additionalEmails": [] }
```

---

## 5. `bodyV2` (RICH_TEXT) Requires Structured Object

**Wrong:**
```json
{ "bodyV2": "Some notes here" }
```
→ `"Invalid object value for field bodyV2"`

**Right:**
```json
{ "bodyV2": { "markdown": "Some notes here" } }
```

**Where we handle it:** `client.py` — `body_v2()` helper. Used in `create_task`.

---

## 6. SELECT Values Must Be UPPERCASE

When creating a SELECT field programmatically via REST metadata API, lowercase `value` in options returns:

```
HTTP 400: "Multiple validation errors occurred while creating fields"
```

**Wrong:**
```json
{ "options": [{ "value": "small", "label": "Small", "color": "blue" }] }
```

**Right:**
```json
{ "options": [{ "value": "SMALL", "label": "Small", "color": "blue" }] }
```

This applies to all SELECT field option values across all objects.

**Where we handle it:** Documented in tool descriptions (e.g. `business_unit` parameter notes).

---

## 7. Custom Object `name` Field — List View Labels

Twenty's list view for custom objects uses the built-in `name` field as the record label. If you create/update a custom object record without setting `name`, every row shows **"Untitled"**.

**Right:**
```python
{ "name": "Moo Moo Gold Coast — 2026-04-23", "venueName": "Moo Moo Gold Coast" }
```

---

## 8. RELATION Fields Cannot Be Created Programmatically

In Twenty v2.0.0+, both REST and GraphQL metadata APIs reject RELATION field creation:

- **REST:** `POST /rest/metadata/fields` with `type: "RELATION"` → `HTTP 400`
- **GraphQL:** `createOneFieldMetadataItem` mutation does **not exist**

**Workaround:** Create a TEXT field as a lightweight substitute, populate it with the target object's name/ID, then add the real RELATION field manually via **Settings → Data Model UI** when clickable relations are needed.

---

## 9. No Native Upsert

Twenty does not support upsert. Every sync script must implement:

1. Query with `filter: { name: { eq: "..." } }`
2. If found → `updateX(id=..., data=...)`
3. If not found → `createX(data=...)`

**Where we handle it:** `upsert_company` and `upsert_person` tools in the bridge.

---

## 10. Rate Limits

- 100 requests / minute
- 60 records per batch
- Implemented in `client.py` via `_throttle()` — auto-sleeps between requests.

---

## 11. Date Normalization for Dedup

Twenty returns ISO8601 dates (`2026-04-23T00:00:00.000Z`) while most local stores use `YYYY-MM-DD`. Both sides of a dedup key must use the same normalization.

**Helper:** `client.norm_date(value)` → always returns `YYYY-MM-DD`.

---

## 12. Whitespace in `TWENTY_API_KEY` → Illegal Header Value

### Symptom

`httpx.LocalProtocolError: Illegal header value b'Bearer eyJ...\n'` before any request reaches the server.

### Root Cause

A multi-line shell export (closing quote on the next line) or a trailing newline from `echo`-style key provisioning embeds `\n` in the env var. HTTP header values cannot contain newlines, so httpx refuses to send the request.

### Fix

`client.py` strips whitespace from `TWENTY_API_KEY` and `TWENTY_BASE_URL` on init. Still worth fixing the source export — other consumers of the same env var (curl, Rails, agents) will hit the same wall.

---

## 13. `pipelineStages` Query Does Not Exist

### Symptom

`GraphQL error: Cannot query field "pipelineStages"` (or empty results) when listing stages.

### Root Cause

Opportunity stage is a SELECT **field** on the opportunity object, not a standalone object. The `pipelineStages` top-level query never existed in Twenty v2 — same class of bug as the singular `company(id:)` query (fixed in `633d8f7`).

### Fix

`list_pipeline_stages` introspects the `OpportunityStageEnum` GraphQL enum, with a metadata-API fallback (`/rest/metadata/objects` → opportunity → `stage` field options) for versions where the enum type is named differently.

---

## Summary Table: Why Not the Community Server?

| Quirk | `jezweb/twenty-mcp` | `appmate-twenty-mcp` |
|-------|---------------------|----------------------|
| Cloudflare User-Agent | ❌ Missing | ✅ Handled |
| JWT workspace header | ❌ Missing | ✅ Handled |
| Person emails via GraphQL | ❓ Unknown (likely buggy) | ✅ Uses REST |
| Composite field normalization | ❓ Unknown | ✅ Helpers provided |
| `bodyV2` structured input | ❓ Unknown | ✅ Handled |
| Rate limit throttling | ❌ Missing | ✅ Built-in |
| Self-hosted first | ❓ Designed for Twenty Cloud? | ✅ Self-hosted optimized |

**Bottom line:** The community server is a good starting point for Twenty Cloud. For self-hosted instances with Cloudflare, custom objects, and real-world edge cases, you need this bridge.
