"""Tests for TransactionSyncService."""

from datetime import date
from decimal import Decimal

import aiosqlite
import pytest

from fortnox.bookkeeping.reconciliation import BankTransaction
from fortnox.svea.api.models import SveaTransaction
from fortnox.svea.sync import TransactionSyncService


@pytest.fixture
async def db(tmp_path):
    """In-memory SQLite database with svea_transactions table."""
    db_path = tmp_path / "test.db"
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.executescript("""
        CREATE TABLE svea_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT UNIQUE NOT NULL,
            account_number TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            value_date TEXT,
            amount REAL NOT NULL,
            balance_after REAL,
            description TEXT NOT NULL,
            reference TEXT DEFAULT '',
            counterparty TEXT DEFAULT '',
            transaction_type TEXT DEFAULT '',
            raw_json TEXT,
            synced_at TEXT NOT NULL DEFAULT (datetime('now')),
            reconciled INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_svea_txn_booking ON svea_transactions(booking_date);
        CREATE INDEX idx_svea_txn_reconciled ON svea_transactions(reconciled);
    """)
    yield conn
    await conn.close()


class TestTransactionSyncStorage:
    """Tests for the DB storage layer (no API calls)."""

    async def test_get_bank_transactions_empty(self, db):
        """Empty DB returns empty list."""
        sync = TransactionSyncService.__new__(TransactionSyncService)
        sync._db = db
        result = await sync.get_bank_transactions(date(2026, 1, 1), date(2026, 12, 31))
        assert result == []

    async def test_get_bank_transactions_with_data(self, db):
        """Stored transactions are converted to BankTransaction correctly."""
        await db.execute(
            """INSERT INTO svea_transactions
               (transaction_id, account_number, booking_date, amount, description, reference)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("txn-1", "9960-123", "2026-03-15", -1500.0, "Bankgiro 123-4567", "BG123"),
        )
        await db.execute(
            """INSERT INTO svea_transactions
               (transaction_id, account_number, booking_date, amount, description, reference)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("txn-2", "9960-123", "2026-03-16", 25000.0, "Inbetalning", "OCR456"),
        )
        await db.commit()

        sync = TransactionSyncService.__new__(TransactionSyncService)
        sync._db = db
        result = await sync.get_bank_transactions(date(2026, 3, 1), date(2026, 3, 31))

        assert len(result) == 2
        assert isinstance(result[0], BankTransaction)
        assert result[0].id == "txn-1"
        assert result[0].amount == Decimal("-1500.0")
        assert result[0].description == "Bankgiro 123-4567"
        assert result[1].amount == Decimal("25000.0")

    async def test_get_bank_transactions_date_filter(self, db):
        """Date filtering works correctly."""
        for i, d in enumerate(["2026-03-10", "2026-03-20", "2026-04-01"]):
            await db.execute(
                """INSERT INTO svea_transactions
                   (transaction_id, account_number, booking_date, amount, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (f"txn-{i}", "9960-123", d, -100.0, f"Payment {i}"),
            )
        await db.commit()

        sync = TransactionSyncService.__new__(TransactionSyncService)
        sync._db = db
        result = await sync.get_bank_transactions(date(2026, 3, 15), date(2026, 3, 31))

        assert len(result) == 1
        assert result[0].id == "txn-1"

    async def test_mark_reconciled(self, db):
        """Marking transactions as reconciled works."""
        for i in range(3):
            await db.execute(
                """INSERT INTO svea_transactions
                   (transaction_id, account_number, booking_date, amount, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (f"txn-{i}", "9960-123", "2026-03-15", -100.0, f"Payment {i}"),
            )
        await db.commit()

        sync = TransactionSyncService.__new__(TransactionSyncService)
        sync._db = db

        count = await sync.mark_reconciled(["txn-0", "txn-2"])
        assert count == 2

        # Verify the unreconciled transaction
        unreconciled = await sync.get_unreconciled_transactions()
        assert len(unreconciled) == 1
        assert unreconciled[0].id == "txn-1"

    async def test_get_sync_cursor(self, db):
        """Sync cursor returns latest booking date."""
        for d in ["2026-03-10", "2026-03-20", "2026-03-15"]:
            await db.execute(
                """INSERT INTO svea_transactions
                   (transaction_id, account_number, booking_date, amount, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (f"txn-{d}", "9960-123", d, -100.0, "Test"),
            )
        await db.commit()

        sync = TransactionSyncService.__new__(TransactionSyncService)
        sync._db = db
        cursor = await sync.get_sync_cursor("9960-123")
        assert cursor == date(2026, 3, 20)

    async def test_get_sync_cursor_empty(self, db):
        """Empty DB returns None cursor."""
        sync = TransactionSyncService.__new__(TransactionSyncService)
        sync._db = db
        cursor = await sync.get_sync_cursor("9960-123")
        assert cursor is None

    async def test_deduplication(self, db):
        """Inserting duplicate transaction_id is silently ignored."""
        sync = TransactionSyncService.__new__(TransactionSyncService)
        sync._db = db

        txn = SveaTransaction(
            transaction_id="txn-dup",
            booking_date=date(2026, 3, 15),
            amount=Decimal("-1000"),
            description="Test payment",
        )

        inserted1 = await sync._store_transaction(txn, "9960-123")
        await db.commit()
        inserted2 = await sync._store_transaction(txn, "9960-123")
        await db.commit()

        # First insert should succeed, second should be a duplicate
        assert inserted1 is True
        assert inserted2 is False

        # Only one row in DB
        cursor = await db.execute("SELECT COUNT(*) FROM svea_transactions")
        row = await cursor.fetchone()
        assert row[0] == 1

    async def test_transaction_count(self, db):
        """Transaction statistics are correct."""
        for i in range(5):
            await db.execute(
                """INSERT INTO svea_transactions
                   (transaction_id, account_number, booking_date, amount, description, reconciled)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f"txn-{i}", "9960-123", "2026-03-15", -100.0, f"Payment {i}", 1 if i < 3 else 0),
            )
        await db.commit()

        sync = TransactionSyncService.__new__(TransactionSyncService)
        sync._db = db
        stats = await sync.get_transaction_count()
        assert stats == {"total": 5, "reconciled": 3, "pending": 2}
