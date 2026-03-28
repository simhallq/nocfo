"""API discovery spike for Svea Bank.

Probes auth.svea.com and bankapi.svea.com to map the auth flow
and available API endpoints. Run as a script or via CLI.

Usage:
    python -m fortnox.svea.api.discovery [--probe-auth] [--probe-api] [--all]
"""

import asyncio
import json
from typing import Any

import httpx
import structlog

from fortnox.svea.api.auth import (
    SVEA_CLIENT_ID,
    SVEA_SCOPES,
    _token_endpoint,
    build_authorize_url,
    start_bankid_auth,
)

logger = structlog.get_logger()

# Candidate API paths to probe (based on BaaS API reference + common patterns)
CANDIDATE_PATHS = [
    # Account endpoints
    ("GET", "/bank-account"),
    ("GET", "/api/bank-account"),
    ("GET", "/v1/bank-account"),
    ("GET", "/psu/bank-account"),
    ("GET", "/account"),
    ("GET", "/api/account"),
    ("GET", "/accounts"),
    ("GET", "/api/accounts"),
    # Transaction endpoints
    ("GET", "/transaction"),
    ("GET", "/api/transaction"),
    ("GET", "/transactions"),
    # Payment endpoints
    ("GET", "/payment-order"),
    ("GET", "/api/payment-order"),
    ("GET", "/upcoming-payment"),
    # User/profile endpoints
    ("GET", "/user"),
    ("GET", "/api/user"),
    ("GET", "/profile"),
    ("GET", "/api/profile"),
    ("GET", "/me"),
    ("GET", "/api/me"),
    # Health/status endpoints
    ("GET", "/health"),
    ("GET", "/api/health"),
    ("GET", "/status"),
    # OpenAPI/docs
    ("GET", "/swagger/v1/swagger.json"),
    ("GET", "/openapi.json"),
    ("GET", "/api/openapi.json"),
    ("GET", "/api-docs"),
    ("GET", "/.well-known/openapi"),
]


async def probe_oidc_discovery() -> dict[str, Any]:
    """Fetch and display the OIDC discovery document."""
    print("\n=== OIDC Discovery ===")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get("https://auth.svea.com/.well-known/openid-configuration")
        data = resp.json()
        print(f"Issuer: {data.get('issuer')}")
        print(f"Token endpoint: {data.get('token_endpoint')}")
        print(f"Grant types: {data.get('grant_types_supported')}")
        print(f"Scopes: {data.get('scopes_supported')}")
        return data


async def probe_bankid_grant() -> dict[str, Any]:
    """Test the BankID QR grant type at the token endpoint.

    This probes whether we can start BankID auth directly via HTTP
    without browser automation.
    """
    print("\n=== BankID QR Grant Type Probe ===")
    result = await start_bankid_auth()
    print(f"Status: {result['status_code']}")
    if "body" in result:
        print(f"Response: {json.dumps(result['body'], indent=2)}")
    elif "body_text" in result:
        print(f"Response text: {result['body_text'][:500]}")
    return result


async def probe_bankid_grant_with_pnr(personal_number: str) -> dict[str, Any]:
    """Test BankID grant with a personal number (personnummer)."""
    print("\n=== BankID Grant with PNR ===")
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Try various parameter names for personal number
        for pnr_field in ["personal_number", "pnr", "ssn", "subject", "login_hint"]:
            print(f"  Trying field '{pnr_field}'...")
            response = await client.post(
                _token_endpoint(),
                data={
                    "grant_type": "bankidqr",
                    "client_id": SVEA_CLIENT_ID,
                    "scope": SVEA_SCOPES,
                    pnr_field: personal_number,
                },
            )
            body = {}
            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text[:300]}
            print(f"    Status: {response.status_code} → {body}")
            if response.status_code != 400:
                return {"field": pnr_field, "status": response.status_code, "body": body}
    return {"status": "all_failed"}


async def probe_authorize_url() -> str:
    """Generate and display the OAuth authorize URL for manual testing."""
    print("\n=== OAuth Authorize URL ===")
    url, state, code_verifier = build_authorize_url()
    print(f"URL: {url}")
    print(f"State: {state}")
    print(f"Code verifier: {code_verifier}")
    print("\nOpen this URL in a browser, complete BankID, then extract the 'code'.")
    return url


async def probe_api_endpoints(bearer_token: str | None = None) -> list[dict[str, Any]]:
    """Probe candidate API paths on bankapi.svea.com.

    If a bearer_token is provided, uses it. Otherwise probes without auth
    to at least see which paths return 401 (exist) vs 404 (don't exist).
    """
    print("\n=== API Endpoint Probe ===")
    base_url = "https://bankapi.svea.com"
    results = []

    headers: dict[str, str] = {"Accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        for method, path in CANDIDATE_PATHS:
            try:
                resp = await client.request(method, path, headers=headers)
                status = resp.status_code
                # 401/403 = endpoint exists but needs auth
                # 404 = endpoint doesn't exist
                # 200 = endpoint works
                # 405 = wrong method but path exists
                indicator = {
                    200: "OK",
                    401: "EXISTS (needs auth)",
                    403: "EXISTS (forbidden)",
                    404: "NOT FOUND",
                    405: "EXISTS (wrong method)",
                    301: "REDIRECT",
                    302: "REDIRECT",
                }.get(status, f"HTTP {status}")

                if status != 404:
                    body_preview = ""
                    try:
                        body_preview = resp.text[:200]
                    except Exception:
                        pass
                    print(f"  {method:6} {path:40} → {status} {indicator}")
                    if body_preview and status in (200, 401, 403):
                        print(f"         Body: {body_preview}")

                results.append({
                    "method": method,
                    "path": path,
                    "status": status,
                    "indicator": indicator,
                })
            except Exception as e:
                results.append({
                    "method": method,
                    "path": path,
                    "error": str(e),
                })

    found = [r for r in results if r.get("status") != 404]
    print(f"\n  Found {len(found)} existing endpoints out of {len(CANDIDATE_PATHS)} probed")
    return results


async def run_discovery(
    probe_auth: bool = True,
    probe_api: bool = True,
    bearer_token: str | None = None,
    personal_number: str | None = None,
) -> dict[str, Any]:
    """Run the full discovery spike."""
    results: dict[str, Any] = {}

    if probe_auth:
        results["oidc"] = await probe_oidc_discovery()
        results["bankid_grant"] = await probe_bankid_grant()
        if personal_number:
            results["bankid_pnr"] = await probe_bankid_grant_with_pnr(personal_number)
        results["authorize_url"] = await probe_authorize_url()

    if probe_api:
        results["api_endpoints"] = await probe_api_endpoints(bearer_token)

    print("\n=== Discovery Summary ===")
    if "bankid_grant" in results:
        status = results["bankid_grant"].get("status_code", "unknown")
        if status == 200:
            print("  BankID QR grant: WORKS — direct API auth possible!")
        elif status == 400:
            body = results["bankid_grant"].get("body", {})
            error = body.get("error", "unknown")
            print(f"  BankID QR grant: needs refinement (error: {error})")
        else:
            print(f"  BankID QR grant: HTTP {status} — may need browser fallback")

    if "api_endpoints" in results:
        found = [r for r in results["api_endpoints"] if r.get("status") != 404]
        print(f"  API endpoints found: {len(found)}")
        for r in found:
            print(f"    {r['method']} {r['path']} → {r.get('indicator', r.get('error'))}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Svea Bank API discovery spike")
    parser.add_argument("--probe-auth", action="store_true", help="Probe auth endpoints")
    parser.add_argument("--probe-api", action="store_true", help="Probe API endpoints")
    parser.add_argument("--all", action="store_true", help="Probe everything")
    parser.add_argument("--token", default=None, help="Bearer token for API probing")
    parser.add_argument("--pnr", default=None, help="Personal number for BankID test")

    args = parser.parse_args()

    if args.all:
        args.probe_auth = True
        args.probe_api = True

    if not args.probe_auth and not args.probe_api:
        args.probe_auth = True
        args.probe_api = True

    asyncio.run(
        run_discovery(
            probe_auth=args.probe_auth,
            probe_api=args.probe_api,
            bearer_token=args.token,
            personal_number=args.pnr,
        )
    )
