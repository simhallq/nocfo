"""Svea Bank session management — token persistence for API access.

Unlike the Fortnox browser session (cookie-based), Svea uses OAuth tokens
for API access. This module handles the bridge between browser-based BankID
auth and token-based API access.
"""

import structlog

from fortnox.svea.api.auth import SveaTokenManager, exchange_code_for_token

logger = structlog.get_logger()


async def complete_auth_and_store_tokens(
    code: str,
    code_verifier: str,
    token_manager: SveaTokenManager | None = None,
) -> dict:
    """Exchange auth code for tokens and persist them.

    Called after the browser-based BankID flow captures the auth code.
    """
    if token_manager is None:
        token_manager = SveaTokenManager()
        await token_manager.initialize()

    token_data = await exchange_code_for_token(code, code_verifier)
    await token_manager.store_tokens(token_data)
    logger.info("svea_session_established")
    return token_data
