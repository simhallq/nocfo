"""Tests for async operation state tracking."""

from fortnox.browser.operations_state import (
    add_qr_url,
    get_operation,
    get_operation_internal,
    mark_browser_work_started,
    new_operation,
    reset_for_retry,
    update_operation,
    _operations,
    _operations_lock,
)


def _clear_operations():
    """Clear all operations between tests."""
    with _operations_lock:
        _operations.clear()


class TestOperationLifecycle:
    def setup_method(self):
        _clear_operations()

    def test_new_operation_returns_id(self):
        op_id = new_operation("auth")
        assert isinstance(op_id, str)
        assert len(op_id) > 10

    def test_new_operation_with_customer(self):
        op_id = new_operation("auth", customer_id="acme-ab")
        op = get_operation(op_id)
        assert op["customer_id"] == "acme-ab"
        assert op["type"] == "auth"
        assert op["status"] == "pending"

    def test_get_operation_not_found(self):
        assert get_operation("nonexistent") is None

    def test_update_operation(self):
        op_id = new_operation("auth")
        update_operation(op_id, status="waiting_for_qr")
        op = get_operation(op_id)
        assert op["status"] == "waiting_for_qr"

    def test_update_nonexistent_operation(self):
        # Should not raise
        update_operation("nonexistent", status="failed")

    def test_add_qr_url(self):
        op_id = new_operation("auth")
        add_qr_url(op_id, "https://example.com/auth/live?token=abc")
        op = get_operation(op_id)
        assert len(op["qr_urls"]) == 1
        assert "abc" in op["qr_urls"][0]

    def test_add_multiple_qr_urls(self):
        op_id = new_operation("auth")
        add_qr_url(op_id, "url1")
        add_qr_url(op_id, "url2")
        op = get_operation(op_id)
        assert op["qr_urls"] == ["url1", "url2"]


class TestOperationSanitization:
    def setup_method(self):
        _clear_operations()

    def test_get_operation_strips_internal_keys(self):
        op_id = new_operation("auth")
        # Simulate worker writing internal data
        with _operations_lock:
            _operations[op_id]["_qr_data"] = "base64data"
            _operations[op_id]["_bankid_uri"] = "bankid:///..."

        op = get_operation(op_id)
        assert "_qr_data" not in op
        assert "_bankid_uri" not in op

    def test_get_operation_internal_includes_all(self):
        op_id = new_operation("auth")
        with _operations_lock:
            _operations[op_id]["_qr_data"] = "base64data"

        op = get_operation_internal(op_id)
        assert op["_qr_data"] == "base64data"
        assert "stop_event" in op

    def test_get_operation_internal_not_found(self):
        assert get_operation_internal("nonexistent") is None

    def test_complete_operation_has_result(self):
        op_id = new_operation("auth")
        update_operation(op_id, status="complete", result={"authenticated": True})
        op = get_operation(op_id)
        assert op["status"] == "complete"
        assert op["result"] == {"authenticated": True}

    def test_failed_operation_has_error(self):
        op_id = new_operation("auth")
        update_operation(op_id, status="failed", error="Timeout")
        op = get_operation(op_id)
        assert op["status"] == "failed"
        assert op["error"] == "Timeout"


class TestInitialStatus:
    def setup_method(self):
        _clear_operations()

    def test_default_initial_status_is_pending(self):
        op_id = new_operation("auth")
        op = get_operation(op_id)
        assert op["status"] == "pending"

    def test_custom_initial_status(self):
        op_id = new_operation("auth", initial_status="awaiting_user")
        op = get_operation(op_id)
        assert op["status"] == "awaiting_user"


class TestMarkBrowserWorkStarted:
    def setup_method(self):
        _clear_operations()

    def test_first_call_returns_true(self):
        op_id = new_operation("auth")
        assert mark_browser_work_started(op_id) is True

    def test_second_call_returns_false(self):
        op_id = new_operation("auth")
        assert mark_browser_work_started(op_id) is True
        assert mark_browser_work_started(op_id) is False

    def test_nonexistent_operation_returns_false(self):
        assert mark_browser_work_started("nonexistent") is False

    def test_reset_allows_new_start(self):
        """After resetting _browser_work_started, a new call should return True."""
        op_id = new_operation("auth")
        assert mark_browser_work_started(op_id) is True
        # Simulate reset (as done in SSE handler for retry)
        with _operations_lock:
            _operations[op_id]["_browser_work_started"] = False
        assert mark_browser_work_started(op_id) is True

    def test_concurrent_safety(self):
        """Only one of many concurrent calls should return True."""
        import threading
        op_id = new_operation("auth")
        results = []
        barrier = threading.Barrier(10)

        def attempt():
            barrier.wait()
            results.append(mark_browser_work_started(op_id))

        threads = [threading.Thread(target=attempt) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == 9


class TestResetForRetry:
    def setup_method(self):
        _clear_operations()

    def test_resets_status_and_error(self):
        op_id = new_operation("auth")
        update_operation(op_id, status="failed", error="Timeout")
        assert reset_for_retry(op_id) is True
        op = get_operation(op_id)
        assert op["status"] == "awaiting_user"
        assert op["error"] is None

    def test_resets_browser_work_started(self):
        op_id = new_operation("auth")
        mark_browser_work_started(op_id)
        assert mark_browser_work_started(op_id) is False  # Already started
        reset_for_retry(op_id)
        assert mark_browser_work_started(op_id) is True  # Re-enabled

    def test_signals_old_stop_event_and_creates_new(self):
        op_id = new_operation("auth")
        with _operations_lock:
            old_event = _operations[op_id]["stop_event"]
        assert not old_event.is_set()

        reset_for_retry(op_id)

        assert old_event.is_set()  # Old event signaled
        with _operations_lock:
            new_event = _operations[op_id]["stop_event"]
        assert new_event is not old_event
        assert not new_event.is_set()  # Fresh event

    def test_nonexistent_operation_returns_false(self):
        assert reset_for_retry("nonexistent") is False
