"""Tests for Fortnox health checks."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from fortnox.api.health import HealthCheck, HealthReport


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get = AsyncMock()
    return client


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_all_checks_pass(self, mock_client):
        mock_client.get = AsyncMock(
            side_effect=lambda path, **kw: {
                "/companyinformation": {
                    "CompanyInformation": {"CompanyName": "Test AB"}
                },
                "/financialyears/?date=" + __import__("datetime").date.today().isoformat(): {
                    "FinancialYear": {
                        "FromDate": "2024-01-01",
                        "ToDate": "2024-12-31",
                    }
                },
            }.get(path, {})
        )

        checker = HealthCheck(mock_client)
        report = await checker.run_all()

        assert report.healthy
        assert len(report.critical_failures) == 0

    @pytest.mark.asyncio
    async def test_connectivity_failure(self, mock_client):
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

        checker = HealthCheck(mock_client)
        report = await checker.run_all()

        assert not report.healthy
        connectivity = next(c for c in report.checks if c.name == "connectivity")
        assert not connectivity.ok
        assert "Connection refused" in connectivity.detail

    @pytest.mark.asyncio
    async def test_scope_failure(self, mock_client):
        async def selective_get(path, **kw):
            if "invoices" in path:
                raise Exception("Forbidden: missing scope")
            return {
                "CompanyInformation": {"CompanyName": "Test AB"},
                "FinancialYear": {"FromDate": "2024-01-01", "ToDate": "2024-12-31"},
            }

        mock_client.get = AsyncMock(side_effect=selective_get)

        checker = HealthCheck(mock_client)
        report = await checker.run_all()

        assert not report.healthy
        invoice_check = next(
            (c for c in report.checks if c.name == "scope:invoice"), None
        )
        assert invoice_check is not None
        assert not invoice_check.ok


class TestHealthReport:
    def test_empty_report_is_healthy(self):
        report = HealthReport()
        assert report.healthy

    def test_summary_format(self):
        from fortnox.api.health import CheckResult

        report = HealthReport(
            checks=[
                CheckResult(name="connectivity", ok=True, detail="Connected to Test AB"),
                CheckResult(name="scope:bookkeeping", ok=False, detail="Missing scope"),
            ]
        )
        summary = report.summary()
        assert "[OK] connectivity" in summary
        assert "[FAIL] scope:bookkeeping" in summary
