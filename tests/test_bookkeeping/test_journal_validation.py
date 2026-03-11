"""Tests for pre-write voucher validation."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from nocfo.bookkeeping.journal import JournalService, VoucherValidationError
from nocfo.fortnox.models import Account, FinancialYear, LockedPeriod, VoucherRow


@pytest.fixture
def mock_journal_service(fake_token_manager):
    """JournalService with mocked dependencies."""
    client = MagicMock()
    client.get = AsyncMock()
    client.post = AsyncMock()

    idempotency = MagicMock()
    idempotency.try_claim = AsyncMock(return_value=True)
    idempotency.record = AsyncMock()

    service = JournalService(client=client, idempotency_store=idempotency)
    return service


@pytest.fixture
def sample_rows():
    return [
        VoucherRow(account=7210, debit=Decimal("1000")),
        VoucherRow(account=1930, credit=Decimal("1000")),
    ]


class TestVoucherContextValidation:
    @pytest.mark.asyncio
    async def test_valid_context_passes(self, mock_journal_service, sample_rows):
        svc = mock_journal_service

        svc._financial_year_service.get_by_date = AsyncMock(
            return_value=FinancialYear(
                id=1, from_date=date(2024, 1, 1), to_date=date(2024, 12, 31)
            )
        )
        svc._financial_year_service.get_locked_period = AsyncMock(return_value=None)
        svc._account_service.get = AsyncMock(
            side_effect=lambda num: Account(number=num, description=f"Account {num}")
        )

        # Should not raise
        await svc.validate_voucher_context(date(2024, 6, 15), sample_rows)

    @pytest.mark.asyncio
    async def test_no_financial_year_raises(self, mock_journal_service, sample_rows):
        svc = mock_journal_service

        svc._financial_year_service.get_by_date = AsyncMock(return_value=None)
        svc._financial_year_service.get_locked_period = AsyncMock(return_value=None)
        svc._account_service.get = AsyncMock(
            side_effect=lambda num: Account(number=num, description=f"Account {num}")
        )

        with pytest.raises(VoucherValidationError, match="No financial year found"):
            await svc.validate_voucher_context(date(2025, 6, 15), sample_rows)

    @pytest.mark.asyncio
    async def test_locked_period_raises(self, mock_journal_service, sample_rows):
        svc = mock_journal_service

        svc._financial_year_service.get_by_date = AsyncMock(
            return_value=FinancialYear(
                id=1, from_date=date(2024, 1, 1), to_date=date(2024, 12, 31)
            )
        )
        svc._financial_year_service.get_locked_period = AsyncMock(
            return_value=LockedPeriod(end_date=date(2024, 6, 30))
        )
        svc._account_service.get = AsyncMock(
            side_effect=lambda num: Account(number=num, description=f"Account {num}")
        )

        with pytest.raises(VoucherValidationError, match="locked period"):
            await svc.validate_voucher_context(date(2024, 5, 15), sample_rows)

    @pytest.mark.asyncio
    async def test_date_after_locked_period_passes(
        self, mock_journal_service, sample_rows
    ):
        svc = mock_journal_service

        svc._financial_year_service.get_by_date = AsyncMock(
            return_value=FinancialYear(
                id=1, from_date=date(2024, 1, 1), to_date=date(2024, 12, 31)
            )
        )
        svc._financial_year_service.get_locked_period = AsyncMock(
            return_value=LockedPeriod(end_date=date(2024, 6, 30))
        )
        svc._account_service.get = AsyncMock(
            side_effect=lambda num: Account(number=num, description=f"Account {num}")
        )

        # July 1 is after June 30 locked period — should pass
        await svc.validate_voucher_context(date(2024, 7, 1), sample_rows)

    @pytest.mark.asyncio
    async def test_inactive_account_raises(self, mock_journal_service, sample_rows):
        svc = mock_journal_service

        svc._financial_year_service.get_by_date = AsyncMock(
            return_value=FinancialYear(
                id=1, from_date=date(2024, 1, 1), to_date=date(2024, 12, 31)
            )
        )
        svc._financial_year_service.get_locked_period = AsyncMock(return_value=None)

        async def mock_get_account(num):
            if num == 7210:
                return Account(number=7210, description="Löner", active=False)
            return Account(number=num, description=f"Account {num}")

        svc._account_service.get = AsyncMock(side_effect=mock_get_account)

        with pytest.raises(VoucherValidationError, match="inactive"):
            await svc.validate_voucher_context(date(2024, 6, 15), sample_rows)

    @pytest.mark.asyncio
    async def test_unknown_account_raises(self, mock_journal_service, sample_rows):
        svc = mock_journal_service

        svc._financial_year_service.get_by_date = AsyncMock(
            return_value=FinancialYear(
                id=1, from_date=date(2024, 1, 1), to_date=date(2024, 12, 31)
            )
        )
        svc._financial_year_service.get_locked_period = AsyncMock(return_value=None)

        async def mock_get_account(num):
            if num == 7210:
                raise Exception("Not found")
            return Account(number=num, description=f"Account {num}")

        svc._account_service.get = AsyncMock(side_effect=mock_get_account)

        with pytest.raises(VoucherValidationError, match="not found"):
            await svc.validate_voucher_context(date(2024, 6, 15), sample_rows)

    @pytest.mark.asyncio
    async def test_multiple_errors_reported(self, mock_journal_service, sample_rows):
        svc = mock_journal_service

        svc._financial_year_service.get_by_date = AsyncMock(return_value=None)
        svc._financial_year_service.get_locked_period = AsyncMock(
            return_value=LockedPeriod(end_date=date(2025, 12, 31))
        )
        svc._account_service.get = AsyncMock(
            side_effect=lambda num: Account(
                number=num, description=f"Account {num}", active=False
            )
        )

        with pytest.raises(VoucherValidationError) as exc_info:
            await svc.validate_voucher_context(date(2024, 6, 15), sample_rows)

        msg = str(exc_info.value)
        assert "No financial year" in msg
        assert "locked period" in msg
        assert "inactive" in msg
