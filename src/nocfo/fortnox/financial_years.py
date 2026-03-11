"""Financial year and locked period API operations."""

from typing import Any

import structlog

from nocfo.fortnox.client import FortnoxClient
from nocfo.fortnox.models import FinancialYear, LockedPeriod

logger = structlog.get_logger()


class FinancialYearService:
    """Operations for financial years and locked periods."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client

    async def list(self) -> list[FinancialYear]:
        """List all financial years."""
        items = await self._client.get_all_pages("/financialyears", "FinancialYears")
        return [self._parse_year(item) for item in items]

    async def get(self, year_id: int) -> FinancialYear:
        """Get a specific financial year."""
        data = await self._client.get(f"/financialyears/{year_id}")
        return self._parse_year(data["FinancialYear"])

    async def get_current(self) -> FinancialYear:
        """Get the current financial year based on today's date."""
        from datetime import date

        today = date.today().isoformat()
        data = await self._client.get(f"/financialyears/?date={today}")
        return self._parse_year(data["FinancialYear"])

    async def get_locked_period(self) -> LockedPeriod | None:
        """Get the locked period end date from company settings."""
        data = await self._client.get("/settings/company")
        locked = data.get("CompanySettings", {}).get("LockedPeriod")
        if locked:
            return LockedPeriod(end_date=locked)
        return None

    @staticmethod
    def _parse_year(data: dict[str, Any]) -> FinancialYear:
        return FinancialYear(
            id=data.get("Id"),
            from_date=data["FromDate"],
            to_date=data["ToDate"],
            accounting_method=data.get("AccountingMethod", "ACCRUAL"),
        )
