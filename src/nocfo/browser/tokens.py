"""Thread-safe one-time tokens for securing QR streaming URLs."""

import secrets
import threading
import time


_tokens: dict[str, dict] = {}
_tokens_lock = threading.Lock()

TOKEN_TTL = 300  # 5 minutes


def generate_token(operation_id: str, context: dict | None = None, ttl: int = TOKEN_TTL) -> str:
    """Generate a one-time token linked to an operation."""
    token = secrets.token_urlsafe(32)
    with _tokens_lock:
        _tokens[token] = {
            "expires": time.time() + ttl,
            "used": False,
            "operation_id": operation_id,
            "context": context or {},
        }
    return token


def get_token_context(token: str) -> dict:
    """Get context metadata for a token."""
    with _tokens_lock:
        info = _tokens.get(token)
        return info["context"] if info else {}


def validate_token(token: str) -> str | None:
    """Validate and consume a one-time token. Returns operation_id or None."""
    with _tokens_lock:
        info = _tokens.get(token)
        if not info:
            return None
        if time.time() > info["expires"]:
            del _tokens[token]
            return None
        if info["used"]:
            return None
        info["used"] = True
        return info["operation_id"]


def validate_token_for_stream(token: str) -> str | None:
    """Validate token for SSE stream (don't consume). Returns operation_id or None."""
    with _tokens_lock:
        info = _tokens.get(token)
        if not info:
            return None
        if time.time() > info["expires"]:
            del _tokens[token]
            return None
        return info["operation_id"]


def cleanup_expired_tokens() -> None:
    """Remove expired tokens."""
    now = time.time()
    with _tokens_lock:
        expired = [t for t, info in _tokens.items() if now > info["expires"]]
        for t in expired:
            del _tokens[t]
