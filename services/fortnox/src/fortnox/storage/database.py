"""SQLite database setup and migrations via aiosqlite."""

from pathlib import Path

import aiosqlite
import structlog

from fortnox.config import get_settings

logger = structlog.get_logger()

MIGRATIONS: list[str] = [
    # Migration 1: Initial schema
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );

    CREATE TABLE IF NOT EXISTS posted_vouchers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idempotency_key TEXT UNIQUE NOT NULL,
        voucher_series TEXT NOT NULL,
        voucher_number INTEGER NOT NULL,
        transaction_date TEXT NOT NULL,
        description TEXT NOT NULL,
        total_amount REAL NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS reconciliation_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bank_transaction_id TEXT UNIQUE NOT NULL,
        ledger_voucher_series TEXT,
        ledger_voucher_number INTEGER,
        match_type TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        status TEXT NOT NULL DEFAULT 'pending',
        matched_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS job_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_name TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at TEXT,
        result TEXT,
        error TEXT
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
        action TEXT NOT NULL,
        entity_type TEXT,
        entity_id TEXT,
        details TEXT,
        user_initiated INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_posted_vouchers_key ON posted_vouchers(idempotency_key);
    CREATE INDEX IF NOT EXISTS idx_reconciliation_bank_id
        ON reconciliation_state(bank_transaction_id);
    CREATE INDEX IF NOT EXISTS idx_job_runs_name ON job_runs(job_name);
    CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
    """,
    # Migration 2: Svea Bank integration
    """
    CREATE TABLE IF NOT EXISTS svea_transactions (
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

    CREATE TABLE IF NOT EXISTS svea_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id TEXT UNIQUE,
        supplier_invoice_id INTEGER,
        recipient_name TEXT NOT NULL,
        recipient_account TEXT NOT NULL,
        account_type TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT NOT NULL DEFAULT 'SEK',
        reference TEXT DEFAULT '',
        due_date TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        batch_id TEXT,
        signed_at TEXT,
        executed_at TEXT,
        fortnox_voucher_series TEXT,
        fortnox_voucher_number INTEGER,
        error TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_svea_txn_booking ON svea_transactions(booking_date);
    CREATE INDEX IF NOT EXISTS idx_svea_txn_reconciled ON svea_transactions(reconciled);
    CREATE INDEX IF NOT EXISTS idx_svea_pay_status ON svea_payments(status);
    CREATE INDEX IF NOT EXISTS idx_svea_pay_due ON svea_payments(due_date);
    CREATE INDEX IF NOT EXISTS idx_svea_pay_batch ON svea_payments(batch_id);
    """,
]


class Database:
    """Async SQLite database manager."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or get_settings().database_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        """Open database connection and run migrations."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(str(self._db_path))
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA foreign_keys=ON")
        await self._migrate()
        logger.info("database_connected", path=str(self._db_path))
        return self._connection

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if not self._connection:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    async def _migrate(self) -> None:
        """Run pending migrations."""
        conn = self._connection
        if not conn:
            return

        # Check current version
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
        row = await cursor.fetchone()
        current_version = row[0] if row and row[0] is not None else 0

        # Run pending migrations
        for i, migration in enumerate(MIGRATIONS, start=1):
            if i > current_version:
                logger.info("running_migration", version=i)
                await conn.executescript(migration)
                await conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))
                await conn.commit()

        logger.debug("migrations_complete", version=len(MIGRATIONS))
