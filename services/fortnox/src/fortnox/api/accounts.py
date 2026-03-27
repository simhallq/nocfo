"""Chart of accounts API operations."""

from typing import Any

import structlog

from fortnox.api.client import FortnoxClient
from fortnox.api.models import Account

logger = structlog.get_logger()


class AccountService:
    """Operations for chart of accounts."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client

    async def list(self, financial_year: int | None = None) -> list[Account]:
        """List all accounts."""
        params: dict[str, Any] = {}
        if financial_year:
            params["financialyear"] = financial_year

        items = await self._client.get_all_pages("/accounts", "Accounts", params=params)
        return [self._parse_account(item) for item in items]

    async def get(self, account_number: int) -> Account:
        """Get a single account by number."""
        data = await self._client.get(f"/accounts/{account_number}")
        return self._parse_account(data["Account"])

    @staticmethod
    def _parse_account(data: dict[str, Any]) -> Account:
        return Account(
            number=data["Number"],
            description=data.get("Description", ""),
            active=data.get("Active", True),
            balance_brought_forward=data.get("BalanceBroughtForward", 0),
            sru=data.get("SRU"),
            year=data.get("Year"),
        )
