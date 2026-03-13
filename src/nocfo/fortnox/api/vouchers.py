"""Voucher (verifikation) API operations."""

from typing import Any

import structlog

from nocfo.fortnox.api.client import FortnoxClient
from nocfo.fortnox.api.models import Voucher, VoucherRow

logger = structlog.get_logger()


class VoucherService:
    """CRUD operations for Fortnox vouchers."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client

    async def list(
        self,
        financial_year: int | None = None,
        voucher_series: str = "A",
    ) -> list[Voucher]:
        """List all vouchers, optionally filtered by year and series."""
        params: dict[str, Any] = {}
        if financial_year:
            params["financialyear"] = financial_year

        path = f"/vouchers/sublist/{voucher_series}"
        items = await self._client.get_all_pages(path, "Vouchers", params=params)
        return [self._parse_voucher(item) for item in items]

    async def get(self, voucher_series: str, voucher_number: int) -> Voucher:
        """Get a single voucher by series and number."""
        data = await self._client.get(f"/vouchers/{voucher_series}/{voucher_number}")
        return self._parse_voucher(data["Voucher"])

    async def create(self, voucher: Voucher) -> Voucher:
        """Create a new voucher in Fortnox."""
        payload = {
            "Voucher": {
                "Description": voucher.description,
                "VoucherSeries": voucher.voucher_series,
                "TransactionDate": voucher.transaction_date.isoformat(),
                "VoucherRows": [
                    {
                        "Account": row.account,
                        "Debit": str(row.debit),
                        "Credit": str(row.credit),
                        "TransactionInformation": row.transaction_information,
                    }
                    for row in voucher.rows
                ],
            }
        }
        if voucher.reference_number:
            payload["Voucher"]["ReferenceNumber"] = voucher.reference_number

        data = await self._client.post("/vouchers/", json_data=payload)
        result = self._parse_voucher(data["Voucher"])
        logger.info(
            "voucher_created",
            series=result.voucher_series,
            number=result.voucher_number,
        )
        return result

    @staticmethod
    def _parse_voucher(data: dict[str, Any]) -> Voucher:
        """Parse a Fortnox voucher response into a Voucher model."""
        rows = [
            VoucherRow(
                account=row["Account"],
                debit=row.get("Debit", 0),
                credit=row.get("Credit", 0),
                transaction_information=row.get("TransactionInformation", ""),
            )
            for row in data.get("VoucherRows", [])
        ]
        return Voucher(
            description=data.get("Description", ""),
            voucher_series=data.get("VoucherSeries", "A"),
            transaction_date=data["TransactionDate"],
            rows=rows,
            voucher_number=data.get("VoucherNumber"),
            year=data.get("Year"),
            reference_number=data.get("ReferenceNumber", ""),
        )
