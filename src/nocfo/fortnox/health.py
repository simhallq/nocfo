"""Fortnox integration health checks."""

import asyncio
from dataclasses import dataclass, field

import structlog

from nocfo.fortnox.client import FortnoxClient
from nocfo.fortnox.financial_years import FinancialYearService

logger = structlog.get_logger()

# Lightweight read calls to verify each scope works.
# companyinformation is already verified by _check_connectivity(), so omitted here.
SCOPE_CHECKS: dict[str, str] = {
    "bookkeeping": "/vouchers/sublist/A?limit=1",
    "invoice": "/invoices?limit=1",
    "supplierinvoice": "/supplierinvoices?limit=1",
    "payment": "/invoicepayments?limit=1",
    "settings": "/settings/company",
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class HealthReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def critical_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]

    def summary(self) -> str:
        lines = []
        for c in self.checks:
            status = "OK" if c.ok else "FAIL"
            line = f"  [{status}] {c.name}"
            if c.detail:
                line += f" — {c.detail}"
            lines.append(line)
        return "\n".join(lines)


class HealthCheck:
    """Verify Fortnox integration is correctly configured."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client
        self._financial_years = FinancialYearService(client)

    async def run_all(self) -> HealthReport:
        """Run all health checks and return a report."""
        report = HealthReport()

        # Run checks concurrently
        connectivity, scope_results, fy_result = await asyncio.gather(
            self._check_connectivity(),
            self._check_scopes(),
            self._check_financial_year(),
        )

        report.checks.append(connectivity)
        report.checks.extend(scope_results)
        report.checks.append(fy_result)

        if report.healthy:
            logger.info("health_check_passed", checks=len(report.checks))
        else:
            failures = [c.name for c in report.critical_failures]
            logger.warning("health_check_failed", failures=failures)

        return report

    async def _check_connectivity(self) -> CheckResult:
        """Verify basic API connectivity."""
        try:
            data = await self._client.get("/companyinformation")
            company = data.get("CompanyInformation", {})
            name = company.get("CompanyName", "Unknown")
            return CheckResult(
                name="connectivity",
                ok=True,
                detail=f"Connected to {name}",
            )
        except Exception as e:
            return CheckResult(
                name="connectivity",
                ok=False,
                detail=str(e),
            )

    async def _check_scopes(self) -> list[CheckResult]:
        """Verify each required scope by making a lightweight read call."""

        async def check_one(scope: str, path: str) -> CheckResult:
            try:
                await self._client.get(path)
                return CheckResult(name=f"scope:{scope}", ok=True)
            except Exception as e:
                return CheckResult(
                    name=f"scope:{scope}",
                    ok=False,
                    detail=f"Missing scope or license — {e}",
                )

        scope_tasks = [
            check_one(scope, path) for scope, path in SCOPE_CHECKS.items()
        ]
        results = await asyncio.gather(*scope_tasks)
        return list(results)

    async def _check_financial_year(self) -> CheckResult:
        """Verify a financial year exists for the current date."""
        try:
            fy = await self._financial_years.get_current()
        except Exception as e:
            return CheckResult(
                name="financial_year",
                ok=False,
                detail=f"Failed to check financial year — {e}",
            )

        if fy:
            return CheckResult(
                name="financial_year",
                ok=True,
                detail=f"{fy.from_date} to {fy.to_date}",
            )
        return CheckResult(
            name="financial_year",
            ok=False,
            detail="No financial year covers today's date",
        )
