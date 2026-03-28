"""Svea Bank transaction fetching service.

Calls bankapi.svea.com/psu/bank-account and /psu/bank-account/{id}/transaction
to fetch account info and transactions.

The endpoint structure mirrors the BaaS API:
- GET /psu/bank-account → list all accounts
- GET /psu/bank-account/{bankAccountId}/transaction → paginated transactions
"""

from datetime import date
from typing import Any

import structlog

from fortnox.svea.api.client import SveaClient
from fortnox.svea.api.models import SveaAccount, SveaTransaction

logger = structlog.get_logger()


class SveaTransactionService:
    """Fetches accounts and transactions from Svea Bank API."""

    def __init__(self, client: SveaClient) -> None:
        self._client = client

    async def list_accounts(self) -> list[SveaAccount]:
        """Fetch all bank accounts."""
        data = await self._client.get("/psu/bank-account")
        accounts_raw = (
            data if isinstance(data, list)
            else data.get("bankAccounts", data.get("data", []))
        )
        if isinstance(accounts_raw, dict):
            accounts_raw = [accounts_raw]

        accounts = []
        for raw in accounts_raw:
            accounts.append(self._parse_account(raw))
        logger.info("svea_accounts_fetched", count=len(accounts))
        return accounts

    async def fetch_transactions(
        self,
        account_id: str,
        from_date: date | None = None,
        to_date: date | None = None,
        max_pages: int = 50,
    ) -> list[SveaTransaction]:
        """Fetch transactions for an account, handling pagination.

        The BaaS API uses offset-based pagination with max 100 per page.
        The regular banking API likely follows the same pattern.
        """
        all_transactions: list[SveaTransaction] = []
        page = 0
        page_size = 100

        while page < max_pages:
            params: dict[str, Any] = {
                "offset": page * page_size,
                "limit": page_size,
            }
            if from_date:
                params["from"] = from_date.isoformat()
            if to_date:
                params["to"] = to_date.isoformat()

            data = await self._client.get(
                f"/psu/bank-account/{account_id}/transaction",
                params=params,
            )

            # Handle different response shapes
            txns_raw = (
                data if isinstance(data, list)
                else data.get("transactions", data.get("data", []))
            )
            if isinstance(txns_raw, dict):
                txns_raw = [txns_raw]

            if not txns_raw:
                break

            for raw in txns_raw:
                all_transactions.append(self._parse_transaction(raw))

            # Check if there are more pages
            if len(txns_raw) < page_size:
                break
            page += 1

        logger.info(
            "svea_transactions_fetched",
            account_id=account_id,
            count=len(all_transactions),
            pages=page + 1,
        )
        return all_transactions

    async def get_account_balance(self, account_id: str) -> dict[str, Any]:
        """Fetch current balance for a specific account."""
        data = await self._client.get(f"/psu/bank-account/{account_id}")
        return data

    @staticmethod
    def _parse_account(raw: dict[str, Any]) -> SveaAccount:
        """Parse API response into SveaAccount model.

        Field names based on BaaS API reference (camelCase).
        Actual field names may differ — will be refined after first live call.
        """
        return SveaAccount(
            account_id=str(
                raw.get("bankAccountId", raw.get("id", raw.get("accountId", "")))
            ),
            account_number=str(
                raw.get("accountNumber", raw.get("number", raw.get("bban", "")))
            ),
            name=raw.get("name", raw.get("accountName", raw.get("label", ""))),
            balance=raw.get("balance", raw.get("currentBalance", raw.get("amount", 0))),
            available_balance=raw.get(
                "availableBalance", raw.get("available", raw.get("balance", 0))
            ),
            currency=raw.get("currency", "SEK"),
            account_type=raw.get("accountType", raw.get("type", "")),
        )

    @staticmethod
    def _parse_transaction(raw: dict[str, Any]) -> SveaTransaction:
        """Parse API response into SveaTransaction model.

        Field names based on BaaS API reference.
        """
        return SveaTransaction(
            transaction_id=str(
                raw.get("transactionId", raw.get("id", raw.get("txnId", "")))
            ),
            booking_date=raw.get("bookingDate", raw.get("date", raw.get("valueDate", ""))),
            value_date=raw.get("valueDate", raw.get("processingDate", None)),
            amount=raw.get("amount", 0),
            balance_after=raw.get("balance", raw.get("balanceAfter", None)),
            description=raw.get("description", raw.get("text", raw.get("message", ""))),
            reference=raw.get("reference", raw.get("ref", "")),
            counterparty=raw.get("counterparty", raw.get("sender", raw.get("receiver", ""))),
            transaction_type=raw.get(
                "transactionTypeName", raw.get("type", raw.get("category", ""))
            ),
        )
