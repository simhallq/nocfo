"""Tests for one-time URL tokens."""

import time
from unittest.mock import patch

from fortnox.browser.tokens import (
    cleanup_expired_tokens,
    generate_token,
    get_token_context,
    validate_token,
    validate_token_for_stream,
    _tokens,
    _tokens_lock,
)


def _clear_tokens():
    """Clear all tokens between tests."""
    with _tokens_lock:
        _tokens.clear()


class TestTokenGeneration:
    def setup_method(self):
        _clear_tokens()

    def test_generate_returns_string(self):
        token = generate_token("op_123")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_generate_unique(self):
        t1 = generate_token("op_1")
        t2 = generate_token("op_2")
        assert t1 != t2

    def test_generate_with_context(self):
        token = generate_token("op_1", context={"action": "login"})
        ctx = get_token_context(token)
        assert ctx == {"action": "login"}

    def test_context_empty_for_unknown_token(self):
        ctx = get_token_context("nonexistent")
        assert ctx == {}

    def test_generate_with_custom_ttl(self):
        token = generate_token("op_1", ttl=86400)
        with _tokens_lock:
            info = _tokens[token]
        # Token should expire ~24h from now, not the default 5min
        assert info["expires"] > time.time() + 80000

    def test_generate_with_short_ttl_expires_quickly(self):
        token = generate_token("op_1", ttl=1)
        assert validate_token_for_stream(token) == "op_1"
        time.sleep(1.1)
        assert validate_token_for_stream(token) is None


class TestTokenValidation:
    def setup_method(self):
        _clear_tokens()

    def test_validate_returns_operation_id(self):
        token = generate_token("op_123")
        result = validate_token(token)
        assert result == "op_123"

    def test_validate_consumes_token(self):
        token = generate_token("op_123")
        assert validate_token(token) == "op_123"
        assert validate_token(token) is None  # consumed

    def test_validate_invalid_token(self):
        assert validate_token("nonexistent") is None

    def test_validate_expired_token(self):
        token = generate_token("op_123")
        with _tokens_lock:
            _tokens[token]["expires"] = time.time() - 1
        assert validate_token(token) is None

    def test_validate_for_stream_does_not_consume(self):
        token = generate_token("op_123")
        assert validate_token_for_stream(token) == "op_123"
        assert validate_token_for_stream(token) == "op_123"  # still valid

    def test_validate_for_stream_invalid(self):
        assert validate_token_for_stream("nonexistent") is None

    def test_validate_for_stream_expired(self):
        token = generate_token("op_123")
        with _tokens_lock:
            _tokens[token]["expires"] = time.time() - 1
        assert validate_token_for_stream(token) is None


class TestTokenCleanup:
    def setup_method(self):
        _clear_tokens()

    def test_cleanup_removes_expired(self):
        t1 = generate_token("op_1")
        t2 = generate_token("op_2")
        with _tokens_lock:
            _tokens[t1]["expires"] = time.time() - 1
        cleanup_expired_tokens()
        assert validate_token_for_stream(t1) is None
        assert validate_token_for_stream(t2) is not None

    def test_cleanup_preserves_valid(self):
        token = generate_token("op_1")
        cleanup_expired_tokens()
        assert validate_token_for_stream(token) == "op_1"
