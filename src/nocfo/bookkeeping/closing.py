"""Period closing orchestration and dependency checks."""

import asyncio
from dataclasses import dataclass
from datetime import date

import structlog

from nocfo.fortnox.api.client import FortnoxClient
from nocfo.fortnox.api.financial_years import FinancialYearService
from nocfo.fortnox.api.invoices import InvoiceService
from nocfo.fortnox.api.supplier_invoices import SupplierInvoiceService

logger = structlog.get_logger()


@dataclass
class ClosingCheck:
    """Result of a period closing readiness check."""

    period_end: date
    is_ready: bool
    checks: dict[str, bool]
    issues: list[str]


class ClosingService:
    """Orchestrates month-end and year-end closing procedures."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client
        self._financial_years = FinancialYearService(client)
        self._invoices = InvoiceService(client)
        self._supplier_invoices = SupplierInvoiceService(client)

    async def check_period(self, period_end: date) -> ClosingCheck:
        """Check if a period is ready to be closed.

        Verifies:
        1. Period is not already locked
        2. All customer invoices for the period are booked
        3. All supplier invoices for the period are booked
        4. Reconciliation is complete (checked via caller)
        """
        issues: list[str] = []
        checks: dict[str, bool] = {}

        # Fetch all checks concurrently
        locked, unbooked_invoices, unbooked_supplier = await asyncio.gather(
            self._financial_years.get_locked_period(),
            self._invoices.list(filter_type="unbooked"),
            self._supplier_invoices.list(filter_type="unbooked"),
        )

        # Check locked period
        if locked and locked.end_date >= period_end:
            checks["not_already_locked"] = False
            issues.append(f"Period already locked through {locked.end_date}")
        else:
            checks["not_already_locked"] = True

        # Check unbooked customer invoices
        period_unbooked = [
            inv for inv in unbooked_invoices if inv.invoice_date and inv.invoice_date <= period_end
        ]
        checks["all_invoices_booked"] = len(period_unbooked) == 0
        if period_unbooked:
            issues.append(f"{len(period_unbooked)} unbooked customer invoice(s) in period")

        # Check unbooked supplier invoices
        period_unbooked_supplier = [
            inv for inv in unbooked_supplier if inv.invoice_date and inv.invoice_date <= period_end
        ]
        checks["all_supplier_invoices_booked"] = len(period_unbooked_supplier) == 0
        if period_unbooked_supplier:
            issues.append(
                f"{len(period_unbooked_supplier)} unbooked supplier invoice(s) in period"
            )

        is_ready = all(checks.values())

        logger.info(
            "closing_check_complete",
            period_end=period_end.isoformat(),
            is_ready=is_ready,
            issues=issues,
        )

        return ClosingCheck(
            period_end=period_end,
            is_ready=is_ready,
            checks=checks,
            issues=issues,
        )
