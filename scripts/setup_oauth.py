#!/usr/bin/env python3
"""Interactive OAuth setup wizard for Fortnox."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nocfo.config import get_settings
from nocfo.fortnox.auth import TokenManager, exchange_code_for_token, start_authorization


def main() -> None:
    print("=" * 60)
    print("  NoCFO - Fortnox OAuth Setup Wizard")
    print("=" * 60)
    print()

    settings = get_settings()

    if not settings.validate_fortnox_credentials():
        print("ERROR: Fortnox credentials not configured.")
        print()
        print("Please set the following in your .env file:")
        print("  FORTNOX_CLIENT_ID=<your client id>")
        print("  FORTNOX_CLIENT_SECRET=<your client secret>")
        print()
        print("To get credentials:")
        print("  1. Register at https://apps.fortnox.se/integration-developer/signup")
        print("  2. Create a 'Private Integration'")
        print("  3. Set Redirect URI to: http://localhost:8888/callback")
        print("  4. Enable scopes: bookkeeping, supplierinvoice, invoice, payment,")
        print("     settings, companyinformation")
        sys.exit(1)

    print("Starting OAuth authorization flow...")
    print("A browser window will open. Please:")
    print("  1. Log in to Fortnox (if not already)")
    print("  2. Authorize the NoCFO application")
    print()
    input("Press Enter to continue...")

    code = start_authorization()
    print(f"\nAuthorization code received!")

    async def exchange():
        token_data = await exchange_code_for_token(code)
        manager = TokenManager()
        await manager.store_tokens(token_data)
        return token_data

    token_data = asyncio.run(exchange())
    print(f"\nTokens exchanged and stored securely.")
    print(f"  Access token expires in: {token_data.get('expires_in', '?')} seconds")
    print(f"\nSetup complete! Run 'python scripts/verify_connection.py' to test.")


if __name__ == "__main__":
    main()
