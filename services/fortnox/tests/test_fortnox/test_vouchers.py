"""Tests for voucher service."""

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from fortnox.api.client import FortnoxClient
from fortnox.api.models import Voucher, VoucherRow
from fortnox.api.vouchers import VoucherService


class TestVoucherService:
    @pytest.mark.asyncio
    @respx.mock
    async def test_get_voucher(self, mock_settings, fake_token_manager, sample_voucher_response):
        token_manager = fake_token_manager

        respx.get("https://api.fortnox.se/3/vouchers/A/42").mock(
            return_value=httpx.Response(200, json=sample_voucher_response)
        )

        async with FortnoxClient(token_manager=token_manager) as client:
            service = VoucherService(client)
            voucher = await service.get("A", 42)

        assert voucher.voucher_number == 42
        assert voucher.description == "Löneutbetalning december"
        assert len(voucher.rows) == 2
        assert voucher.rows[0].debit == Decimal("35000")

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_voucher(self, mock_settings, fake_token_manager, sample_voucher_response):
        token_manager = fake_token_manager

        respx.post("https://api.fortnox.se/3/vouchers/").mock(
            return_value=httpx.Response(201, json=sample_voucher_response)
        )

        voucher = Voucher(
            description="Löneutbetalning december",
            transaction_date=date(2024, 12, 25),
            rows=[
                VoucherRow(account=7210, debit=Decimal("35000")),
                VoucherRow(account=1930, credit=Decimal("35000")),
            ],
        )

        async with FortnoxClient(token_manager=token_manager) as client:
            service = VoucherService(client)
            result = await service.create(voucher)

        assert result.voucher_number == 42

    @pytest.mark.asyncio
    @respx.mock
    async def test_list_vouchers(
        self, mock_settings, fake_token_manager, sample_vouchers_list_response
    ):
        token_manager = fake_token_manager

        respx.get("https://api.fortnox.se/3/vouchers/sublist/A").mock(
            return_value=httpx.Response(200, json=sample_vouchers_list_response)
        )

        async with FortnoxClient(token_manager=token_manager) as client:
            service = VoucherService(client)
            vouchers = await service.list(voucher_series="A")

        assert len(vouchers) == 2
        assert vouchers[0].voucher_number == 1
        assert vouchers[1].voucher_number == 2
