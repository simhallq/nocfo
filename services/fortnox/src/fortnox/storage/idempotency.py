"""Idempotency tracking to prevent double-posting vouchers."""

import hashlib
from datetime import date
from decimal import Decimal

import aiosqlite
import structlog

logger = structlog.get_logger()


def compute_idempotency_key(
    transaction_date: date,
    account_pairs: list[tuple[int, Decimal, Decimal]],
    description: str,
) -> str:
    """Compute a deterministic hash key for a voucher.

    Key = hash(date + sorted account/amount pairs + description)
    """
    parts = [transaction_date.isoformat(), description.strip().lower()]

    # Sort by account number for deterministic ordering
    sorted_pairs = sorted(account_pairs, key=lambda x: x[0])
    for account, debit, credit in sorted_pairs:
        parts.append(f"{account}:{debit}:{credit}")

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class IdempotencyStore:
    """Tracks posted vouchers to prevent duplicates."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def exists(self, key: str) -> bool:
        """Check if a voucher with this idempotency key was already posted."""
        cursor = await self._db.execute(
            "SELECT 1 FROM posted_vouchers WHERE idempotency_key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row is not None

    async def try_claim(self, key: str) -> bool:
        """Atomically claim an idempotency key. Returns True if claimed (new).

        Uses INSERT OR IGNORE to avoid TOCTOU races between exists() and record().
        """
        cursor = await self._db.execute(
            """
            INSERT OR IGNORE INTO posted_vouchers
                (idempotency_key, voucher_series, voucher_number,
                 transaction_date, description, total_amount)
            VALUES (?, '', 0, '', '', 0)
            """,
            (key,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def record(
        self,
        key: str,
        voucher_series: str,
        voucher_number: int,
        transaction_date: date,
        description: str,
        total_amount: Decimal,
    ) -> None:
        """Update a claimed idempotency record with the actual voucher details."""
        await self._db.execute(
            """
            UPDATE posted_vouchers
            SET voucher_series = ?, voucher_number = ?,
                transaction_date = ?, description = ?, total_amount = ?
            WHERE idempotency_key = ?
            """,
            (
                voucher_series,
                voucher_number,
                transaction_date.isoformat(),
                description,
                str(total_amount),
                key,
            ),
        )
        await self._db.commit()
        logger.info(
            "voucher_recorded",
            key=key[:8],
            series=voucher_series,
            number=voucher_number,
        )

    async def get_posted_count(self) -> int:
        """Get total number of posted vouchers tracked."""
        cursor = await self._db.execute("SELECT COUNT(*) FROM posted_vouchers")
        row = await cursor.fetchone()
        return row[0] if row else 0
