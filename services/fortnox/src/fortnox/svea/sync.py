"""Transaction sync service — fetches from Svea Bank API and stores locally.

Handles deduplication by transaction_id and provides conversion to
BankTransaction dataclass for the reconciliation engine.
"""

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import aiosqlite
import structlog

from fortnox.bookkeeping.reconciliation import BankTransaction
from fortnox.svea.api.client import SveaClient
from fortnox.svea.api.models import SveaTransaction
from fortnox.svea.api.transactions import SveaTransactionService

logger = structlog.get_logger()

_TXN_COLUMNS = "transaction_id, booking_date, amount, description, reference"


def _row_to_bank_transaction(row: aiosqlite.Row) -> BankTransaction:
    return BankTransaction(
        id=row[0],
        date=date.fromisoformat(row[1]),
        amount=Decimal(str(row[2])),
        description=row[3],
        reference=row[4] or "",
    )


@dataclass
class SyncResult:
    """Result of a transaction sync operation."""

    fetched: int
    new: int
    duplicates: int
    account_id: str


class TransactionSyncService:
    """Orchestrates fetching transactions from Svea and storing in SQLite."""

    def __init__(self, db: aiosqlite.Connection, client: SveaClient) -> None:
        self._db = db
        self._client = client
        self._txn_service = SveaTransactionService(client)

    async def sync_transactions(
        self,
        account_id: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> SyncResult:
        """Fetch new transactions and store them.

        Uses the sync cursor (latest booking_date in DB) if from_date is not specified.
        Deduplicates by transaction_id using INSERT OR IGNORE.
        """
        if from_date is None:
            cursor = await self.get_sync_cursor(account_id)
            # Overlap by 3 days to catch late-posting transactions
            from_date = cursor - timedelta(days=3) if cursor else date.today() - timedelta(days=90)

        if to_date is None:
            to_date = date.today()

        logger.info(
            "svea_sync_starting",
            account_id=account_id,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
        )

        transactions = await self._txn_service.fetch_transactions(
            account_id=account_id,
            from_date=from_date,
            to_date=to_date,
        )

        new_count = await self._store_transactions_batch(transactions, account_id)
        await self._db.commit()

        result = SyncResult(
            fetched=len(transactions),
            new=new_count,
            duplicates=len(transactions) - new_count,
            account_id=account_id,
        )
        logger.info(
            "svea_sync_complete",
            fetched=result.fetched,
            new=result.new,
            duplicates=result.duplicates,
        )
        return result

    async def _store_transactions_batch(
        self, transactions: list[SveaTransaction], account_number: str
    ) -> int:
        """Store transactions using executemany, returning count of new rows."""
        if not transactions:
            return 0

        rows = [
            (
                txn.transaction_id,
                account_number,
                txn.booking_date.isoformat(),
                txn.value_date.isoformat() if txn.value_date else None,
                float(txn.amount),
                float(txn.balance_after) if txn.balance_after is not None else None,
                txn.description,
                txn.reference,
                txn.counterparty,
                txn.transaction_type,
                json.dumps(txn.model_dump(mode="json")),
            )
            for txn in transactions
        ]

        before = self._db.total_changes
        await self._db.executemany(
            """INSERT OR IGNORE INTO svea_transactions
               (transaction_id, account_number, booking_date, value_date,
                amount, balance_after, description, reference,
                counterparty, transaction_type, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        return self._db.total_changes - before

    async def _store_transaction(self, txn: SveaTransaction, account_number: str) -> bool:
        """Store a single transaction, returning True if it was new."""
        cursor = await self._db.execute(
            """INSERT OR IGNORE INTO svea_transactions
               (transaction_id, account_number, booking_date, value_date,
                amount, balance_after, description, reference,
                counterparty, transaction_type, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                txn.transaction_id,
                account_number,
                txn.booking_date.isoformat(),
                txn.value_date.isoformat() if txn.value_date else None,
                float(txn.amount),
                float(txn.balance_after) if txn.balance_after is not None else None,
                txn.description,
                txn.reference,
                txn.counterparty,
                txn.transaction_type,
                json.dumps(txn.model_dump(mode="json")),
            ),
        )
        return cursor.rowcount > 0

    async def get_sync_cursor(self, account_number: str) -> date | None:
        """Get the latest booking_date stored for this account."""
        cursor = await self._db.execute(
            "SELECT MAX(booking_date) FROM svea_transactions WHERE account_number = ?",
            (account_number,),
        )
        row = await cursor.fetchone()
        if row and row[0]:
            return date.fromisoformat(row[0])
        return None

    async def get_bank_transactions(
        self,
        from_date: date,
        to_date: date,
        account_number: str | None = None,
    ) -> list[BankTransaction]:
        """Read stored transactions and convert to BankTransaction for reconciliation."""
        query = (
            f"SELECT {_TXN_COLUMNS} FROM svea_transactions"
            " WHERE booking_date >= ? AND booking_date <= ?"
        )
        params: list = [from_date.isoformat(), to_date.isoformat()]

        if account_number:
            query += " AND account_number = ?"
            params.append(account_number)

        query += " ORDER BY booking_date"
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_bank_transaction(row) for row in rows]

    async def get_unreconciled_transactions(
        self,
        account_number: str | None = None,
    ) -> list[BankTransaction]:
        """Get transactions not yet reconciled."""
        query = f"SELECT {_TXN_COLUMNS} FROM svea_transactions WHERE reconciled = 0"
        params: list = []

        if account_number:
            query += " AND account_number = ?"
            params.append(account_number)

        query += " ORDER BY booking_date"
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_bank_transaction(row) for row in rows]

    async def mark_reconciled(self, transaction_ids: list[str]) -> int:
        """Mark transactions as reconciled."""
        if not transaction_ids:
            return 0
        placeholders = ",".join("?" for _ in transaction_ids)
        await self._db.execute(
            f"UPDATE svea_transactions SET reconciled = 1 WHERE transaction_id IN ({placeholders})",
            transaction_ids,
        )
        await self._db.commit()
        return len(transaction_ids)

    async def get_transaction_count(self, account_number: str | None = None) -> dict:
        """Get transaction statistics."""
        base = (
            "SELECT COUNT(*), SUM(CASE WHEN reconciled = 1 THEN 1 ELSE 0 END)"
            " FROM svea_transactions"
        )
        params: list = []
        if account_number:
            base += " WHERE account_number = ?"
            params.append(account_number)

        cursor = await self._db.execute(base, params)
        row = await cursor.fetchone()
        total = row[0] or 0
        reconciled = row[1] or 0
        return {"total": total, "reconciled": reconciled, "pending": total - reconciled}
