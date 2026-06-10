"""Twenty CRM client with all self-hosted quirks handled.

Built from real-world battle scars — see QUIRKS.md in the repo root.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import httpx


class TwentyError(Exception):
    """Raised on API errors with context."""

    def __init__(self, message: str, *, status: int | None = None, response: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.response = response


class TwentyClient:
    """GraphQL + REST client for Twenty CRM.

    Handles Cloudflare bot detection, JWT workspace extraction, composite field
    normalization, and the x-request-metadata header quirk automatically.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        # Strip whitespace defensively — a trailing newline in the env var (e.g. from a
        # multi-line shell export) becomes an illegal HTTP header value in httpx.
        self.api_key = (api_key or os.environ["TWENTY_API_KEY"]).strip()
        self.base_url = (base_url or os.environ.get("TWENTY_BASE_URL", "https://api.twenty.com")).strip().rstrip("/")

        # Extract workspace ID from JWT payload
        self.workspace_id = self._extract_workspace_id(self.api_key)

        # Shared headers for every request
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            # Cloudflare bot detection workaround — urllib user-agent is blocked
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            # Workspace discovery workaround — base64-encoded JSON header
            "x-request-metadata": base64.b64encode(
                json.dumps({"workspaceId": self.workspace_id}).encode()
            ).decode(),
        }

        # Cloudflare Access service token — required when the instance sits behind
        # an Access application (otherwise requests 302 to the Access login page).
        cf_client_id = (os.environ.get("CF_ACCESS_CLIENT_ID") or "").strip()
        cf_client_secret = (os.environ.get("CF_ACCESS_CLIENT_SECRET") or "").strip()
        if cf_client_id and cf_client_secret:
            self._headers["CF-Access-Client-Id"] = cf_client_id
            self._headers["CF-Access-Client-Secret"] = cf_client_secret

        self._client = httpx.Client(
            base_url=self.base_url,
            headers=self._headers,
            timeout=30.0,
        )

        # Rate limit: 100 req/min
        self._last_request_time: float = 0.0
        self._min_interval: float = 60.0 / 100.0

        # Introspection caches — workspaces customize the data model (relations can
        # be deactivated entirely), so queries/mutations must adapt at runtime.
        self._type_fields_cache: dict[str, set[str]] = {}
        self._input_fields_cache: dict[str, set[str]] = {}

    def _extract_workspace_id(self, api_key: str) -> str:
        """Decode JWT payload to get workspaceId."""
        parts = api_key.split(".")
        if len(parts) < 2:
            raise TwentyError("Invalid API key format — expected JWT")
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        try:
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            raise TwentyError(f"Failed to decode JWT payload: {exc}") from exc
        workspace_id = payload.get("workspaceId")
        if not workspace_id:
            raise TwentyError("JWT payload missing workspaceId")
        return workspace_id

    def _throttle(self) -> None:
        """Enforce rate limit between requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    # ── GraphQL ──────────────────────────────────────────────────────────────

    def graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query/mutation."""
        self._throttle()
        resp = self._client.post(
            "/graphql",
            json={"query": query, "variables": variables or {}},
        )
        self._handle_http_error(resp)
        data = resp.json()
        if "errors" in data:
            errors = data["errors"]
            messages = "; ".join(e.get("message", "unknown") for e in errors)
            raise TwentyError(f"GraphQL error: {messages}", response=errors)
        return data.get("data", {})

    # ── REST ─────────────────────────────────────────────────────────────────

    def rest_get(self, path: str) -> dict[str, Any]:
        """GET from Twenty REST API."""
        self._throttle()
        resp = self._client.get(path)
        self._handle_http_error(resp)
        return resp.json()

    def rest_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to Twenty REST API."""
        self._throttle()
        resp = self._client.post(path, json=payload)
        self._handle_http_error(resp)
        return resp.json()

    def rest_patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """PATCH to Twenty REST API."""
        self._throttle()
        resp = self._client.patch(path, json=payload)
        self._handle_http_error(resp)
        return resp.json()

    def rest_delete(self, path: str) -> None:
        """DELETE from Twenty REST API."""
        self._throttle()
        resp = self._client.delete(path)
        self._handle_http_error(resp)

    def _handle_http_error(self, resp: httpx.Response) -> None:
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if "cloudflareaccess.com/cdn-cgi/access/login" in location:
                raise TwentyError(
                    "Blocked by Cloudflare Access — set CF_ACCESS_CLIENT_ID and "
                    "CF_ACCESS_CLIENT_SECRET to a service token authorized for this "
                    "Access application.",
                    status=resp.status_code,
                )
            raise TwentyError(
                f"Unexpected redirect to {location[:120]} — check TWENTY_BASE_URL",
                status=resp.status_code,
            )
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise TwentyError(
                f"HTTP {resp.status_code}: {resp.reason_phrase}",
                status=resp.status_code,
                response=body,
            )

    # ── Schema introspection ─────────────────────────────────────────────────

    def object_fields(self, type_name: str) -> set[str]:
        """Field names available on a GraphQL object type (cached)."""
        if type_name not in self._type_fields_cache:
            data = self.graphql(
                "query($n: String!) { __type(name: $n) { fields { name } } }",
                {"n": type_name},
            )
            type_info = data.get("__type") or {}
            self._type_fields_cache[type_name] = {
                f["name"] for f in type_info.get("fields") or []
            }
        return self._type_fields_cache[type_name]

    def input_fields(self, type_name: str) -> set[str]:
        """Field names accepted by a GraphQL input type (cached)."""
        if type_name not in self._input_fields_cache:
            data = self.graphql(
                "query($n: String!) { __type(name: $n) { inputFields { name } } }",
                {"n": type_name},
            )
            type_info = data.get("__type") or {}
            self._input_fields_cache[type_name] = {
                f["name"] for f in type_info.get("inputFields") or []
            }
        return self._input_fields_cache[type_name]

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def norm_date(value: Any) -> str:
        """Normalize any date to YYYY-MM-DD for dedup keys."""
        if not value:
            return ""
        return str(value)[:10]

    @staticmethod
    def emails_field(primary: str, additional: list[str] | None = None) -> dict[str, Any]:
        """Build composite emails shape for Person records."""
        return {
            "primaryEmail": primary,
            "additionalEmails": additional or [],
        }

    @staticmethod
    def phones_field(
        primary: str,
        country_code: str = "AU",
        calling_code: str = "+61",
    ) -> dict[str, Any]:
        """Build composite phones shape for Person records."""
        return {
            "primaryPhoneNumber": primary,
            "primaryPhoneCountryCode": country_code,
            "primaryPhoneCallingCode": calling_code,
            "additionalPhones": [],
        }

    @staticmethod
    def body_v2(markdown: str) -> dict[str, Any]:
        """RICH_TEXT bodyV2 field requires structured object, not plain string."""
        return {"markdown": markdown}
