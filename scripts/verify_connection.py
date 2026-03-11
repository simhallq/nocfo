#!/usr/bin/env python3
"""Verify Fortnox API connection."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nocfo.fortnox.auth import TokenManager
from nocfo.fortnox.client import FortnoxClient


async def main() -> None:
    print("Verifying Fortnox API connection...")

    manager = TokenManager()
    await manager.initialize()

    if not manager.is_authenticated:
        print("ERROR: Not authenticated. Run 'python scripts/setup_oauth.py' first.")
        sys.exit(1)

    async with FortnoxClient(token_manager=manager) as client:
        # Fetch company info
        try:
            data = await client.get("/companyinformation")
            info = data.get("CompanyInformation", {})
            print(f"\nConnection successful!")
            print(f"  Company: {info.get('CompanyName', 'N/A')}")
            print(f"  Org.nr:  {info.get('OrganizationNumber', 'N/A')}")
            print(f"  Address: {info.get('Address', 'N/A')}")
        except Exception as e:
            print(f"\nConnection failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
