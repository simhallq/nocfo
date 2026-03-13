"""HTTP client for the Browser API server."""

from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

DEFAULT_BASE_URL = "http://localhost:8790"
DEFAULT_TIMEOUT = 120.0


class BrowserApiClient:
    """Client for the NoCFO Browser API server.

    Mirrors the FortnoxClient pattern but talks to the local browser API
    instead of the Fortnox REST API.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url
        self._token = token
        self._timeout = timeout
        self._client: httpx.Client | None = None

    def __enter__(self) -> "BrowserApiClient":
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout),
            headers=headers,
        )
        return self

    def __exit__(self, *args: Any) -> None:
        if self._client:
            self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Make an HTTP request to the browser API."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'with' context manager.")
        response = self._client.request(method, path, json=json_data)
        response.raise_for_status()
        return response

    def health(self) -> dict[str, Any]:
        """GET /health — Server + Chrome + session status."""
        return self._request("GET", "/health").json()

    def login(self) -> dict[str, Any]:
        """POST /auth/login — Start BankID login flow.

        Returns {"status": "authenticated"} or {"status": "timeout"}.
        """
        return self._request("POST", "/auth/login").json()

    def auth_status(self) -> bool:
        """GET /auth/status — Check if Fortnox session is active."""
        data = self._request("GET", "/auth/status").json()
        return data.get("authenticated", False)

    def reconcile(
        self,
        account: int,
        matches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """POST /reconciliation/run — Execute bank reconciliation."""
        return self._request(
            "POST",
            "/reconciliation/run",
            json_data={"account": account, "matches": matches},
        ).json()

    def close_period(self, period: str) -> dict[str, Any]:
        """POST /period/close — Lock a period."""
        return self._request(
            "POST",
            "/period/close",
            json_data={"period": period},
        ).json()

    def download_report(self, report_type: str, period: str) -> bytes:
        """POST /reports/download — Download a financial report.

        Returns raw file bytes.
        """
        response = self._request(
            "POST",
            "/reports/download",
            json_data={"type": report_type, "period": period},
        )
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            # Error response
            data = response.json()
            raise RuntimeError(data.get("message", "Report download failed"))
        return response.content

    def list_rules(self) -> dict[str, Any]:
        """POST /rules/list — List current Regelverk."""
        return self._request("POST", "/rules/list").json()

    def sync_rules(self, rules: list[dict[str, Any]]) -> dict[str, Any]:
        """POST /rules/sync — Sync rules to Fortnox."""
        return self._request(
            "POST",
            "/rules/sync",
            json_data={"rules": rules},
        ).json()

    def start_auth(self, customer_id: str) -> dict[str, Any]:
        """POST /auth/start — Initiate BankID auth for a customer."""
        return self._request(
            "POST",
            "/auth/start",
            json_data={"customer_id": customer_id},
        ).json()

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        """GET /operation/{id} — Poll operation status."""
        return self._request("GET", f"/operation/{operation_id}").json()

    def session_status(self, customer_id: str) -> dict[str, Any]:
        """GET /auth/session/{customer_id} — Check stored session."""
        return self._request("GET", f"/auth/session/{customer_id}").json()
