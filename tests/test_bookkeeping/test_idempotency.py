"""Tests for idempotency tracking."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from nocfo.storage.database import Database
from nocfo.storage.idempotency import IdempotencyStore, compute_idempotency_key


@pytest.fixture
async def idempotency_db():
    """Provide an in-memory DB with migrations applied."""
    db = Database(db_path=Path(":memory:"))
    conn = await db.connect()
    yield conn
    await db.close()


class TestComputeIdempotencyKey:
    def test_deterministic(self):
        key1 = compute_idempotency_key(
            date(2024, 12, 1),
            [(7210, Decimal("1000"), Decimal("0")), (1930, Decimal("0"), Decimal("1000"))],
            "Test payment",
        )
        key2 = compute_idempotency_key(
            date(2024, 12, 1),
            [(7210, Decimal("1000"), Decimal("0")), (1930, Decimal("0"), Decimal("1000"))],
            "Test payment",
        )
        assert key1 == key2

    def test_different_description(self):
        key1 = compute_idempotency_key(
            date(2024, 12, 1),
            [(7210, Decimal("1000"), Decimal("0"))],
            "Payment A",
        )
        key2 = compute_idempotency_key(
            date(2024, 12, 1),
            [(7210, Decimal("1000"), Decimal("0"))],
            "Payment B",
        )
        assert key1 != key2

    def test_different_date(self):
        key1 = compute_idempotency_key(
            date(2024, 12, 1),
            [(7210, Decimal("1000"), Decimal("0"))],
            "Test",
        )
        key2 = compute_idempotency_key(
            date(2024, 12, 2),
            [(7210, Decimal("1000"), Decimal("0"))],
            "Test",
        )
        assert key1 != key2

    def test_order_independent(self):
        """Account pairs should be sorted, so order shouldn't matter."""
        key1 = compute_idempotency_key(
            date(2024, 12, 1),
            [(7210, Decimal("1000"), Decimal("0")), (1930, Decimal("0"), Decimal("1000"))],
            "Test",
        )
        key2 = compute_idempotency_key(
            date(2024, 12, 1),
            [(1930, Decimal("0"), Decimal("1000")), (7210, Decimal("1000"), Decimal("0"))],
            "Test",
        )
        assert key1 == key2


class TestIdempotencyStore:
    @pytest.mark.asyncio
    async def test_exists_returns_false_for_new(self, idempotency_db):
        store = IdempotencyStore(idempotency_db)
        assert await store.exists("nonexistent") is False

    @pytest.mark.asyncio
    async def test_try_claim_and_record(self, idempotency_db):
        store = IdempotencyStore(idempotency_db)

        # First claim succeeds
        assert await store.try_claim("abc123") is True
        # Second claim fails (duplicate)
        assert await store.try_claim("abc123") is False

        await store.record(
            key="abc123",
            voucher_series="A",
            voucher_number=1,
            transaction_date=date(2024, 12, 1),
            description="Test",
            total_amount=Decimal("1000"),
        )

        assert await store.exists("abc123") is True
        assert await store.get_posted_count() == 1
