"""Shared test fixtures."""

import pytest

from nocfo.fortnox.api.auth import TokenManager


@pytest.fixture
def mock_settings(monkeypatch):
    """Provide test settings."""
    monkeypatch.setenv("FORTNOX_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("FORTNOX_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("DATABASE_PATH", ":memory:")

    # Clear cached settings so env changes take effect
    from nocfo.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def fake_token_manager():
    """A TokenManager with pre-set test tokens (no disk I/O)."""
    manager = TokenManager.__new__(TokenManager)
    manager._access_token = "test-token"
    manager._refresh_token = "test-refresh"
    manager._expires_at = 9999999999.0
    manager._store = None
    return manager


@pytest.fixture
def sample_voucher_response():
    """Realistic Fortnox voucher API response."""
    return {
        "Voucher": {
            "Description": "Löneutbetalning december",
            "VoucherSeries": "A",
            "VoucherNumber": 42,
            "TransactionDate": "2024-12-25",
            "Year": 2024,
            "ReferenceNumber": "REF-001",
            "VoucherRows": [
                {
                    "Account": 7210,
                    "Debit": 35000.0,
                    "Credit": 0,
                    "TransactionInformation": "Löner tjänstemän",
                },
                {
                    "Account": 1930,
                    "Debit": 0,
                    "Credit": 35000.0,
                    "TransactionInformation": "Företagskonto",
                },
            ],
        }
    }


@pytest.fixture
def sample_vouchers_list_response():
    """Paginated voucher list response."""
    return {
        "MetaInformation": {
            "@CurrentPage": 1,
            "@TotalPages": 1,
            "@TotalResources": 2,
        },
        "Vouchers": [
            {
                "Description": "Löneutbetalning",
                "VoucherSeries": "A",
                "VoucherNumber": 1,
                "TransactionDate": "2024-12-01",
                "Year": 2024,
                "VoucherRows": [
                    {"Account": 7210, "Debit": 30000.0, "Credit": 0},
                    {"Account": 1930, "Debit": 0, "Credit": 30000.0},
                ],
            },
            {
                "Description": "Kontorsmaterial",
                "VoucherSeries": "A",
                "VoucherNumber": 2,
                "TransactionDate": "2024-12-05",
                "Year": 2024,
                "VoucherRows": [
                    {"Account": 5410, "Debit": 500.0, "Credit": 0},
                    {"Account": 1930, "Debit": 0, "Credit": 500.0},
                ],
            },
        ],
    }


@pytest.fixture
def sample_accounts_response():
    """Chart of accounts response."""
    return {
        "MetaInformation": {"@CurrentPage": 1, "@TotalPages": 1},
        "Accounts": [
            {"Number": 1930, "Description": "Företagskonto", "Active": True},
            {"Number": 2650, "Description": "Momsredovisningskonto", "Active": True},
            {"Number": 7210, "Description": "Löner tjänstemän", "Active": True},
        ],
    }


@pytest.fixture
def sample_invoices_response():
    """Invoice list response."""
    return {
        "MetaInformation": {"@CurrentPage": 1, "@TotalPages": 1},
        "Invoices": [
            {
                "DocumentNumber": 1001,
                "CustomerNumber": "100",
                "InvoiceDate": "2024-12-01",
                "DueDate": "2024-12-31",
                "Total": 12500.0,
                "Balance": 12500.0,
                "Booked": True,
                "Cancelled": False,
                "Currency": "SEK",
                "OCR": "10012",
            },
        ],
    }


@pytest.fixture
def sample_company_info_response():
    """Company information response."""
    return {
        "CompanyInformation": {
            "CompanyName": "Test AB",
            "OrganizationNumber": "556677-8899",
            "Address": "Testgatan 1",
        }
    }
