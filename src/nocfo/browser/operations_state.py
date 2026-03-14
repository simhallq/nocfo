"""In-memory async operation tracking."""

import secrets
import threading
import time
from typing import Any


_operations: dict[str, dict[str, Any]] = {}
_operations_lock = threading.Lock()


def new_operation(op_type: str, customer_id: str | None = None, initial_status: str = "pending") -> str:
    """Create a new operation and return its ID."""
    op_id = secrets.token_urlsafe(16)
    with _operations_lock:
        _operations[op_id] = {
            "id": op_id,
            "type": op_type,
            "status": initial_status,
            "customer_id": customer_id,
            "qr_urls": [],
            "result": None,
            "error": None,
            "stop_event": threading.Event(),
            "created": time.time(),
            "_browser_work_started": False,
        }
    return op_id


def mark_browser_work_started(op_id: str) -> bool:
    """Atomic compare-and-swap: returns True only if this call flipped the flag.

    Prevents duplicate browser submissions from concurrent SSE connections.
    """
    with _operations_lock:
        op = _operations.get(op_id)
        if not op:
            return False
        if op["_browser_work_started"]:
            return False
        op["_browser_work_started"] = True
        return True


def update_operation(op_id: str, **kwargs: Any) -> None:
    """Thread-safe operation update."""
    with _operations_lock:
        if op_id in _operations:
            _operations[op_id].update(kwargs)


def add_qr_url(op_id: str, url: str) -> None:
    """Add a QR streaming URL to the operation."""
    with _operations_lock:
        if op_id in _operations:
            _operations[op_id]["qr_urls"].append(url)


def get_operation(op_id: str) -> dict[str, Any] | None:
    """Get sanitized operation state (strips internal _ keys)."""
    with _operations_lock:
        op = _operations.get(op_id)
        if op:
            return {
                "id": op["id"],
                "type": op["type"],
                "status": op["status"],
                "customer_id": op.get("customer_id"),
                "qr_urls": list(op["qr_urls"]),
                "result": op["result"],
                "error": op["error"],
            }
    return None


def get_operation_internal(op_id: str) -> dict[str, Any] | None:
    """Get full operation dict including internal _ keys (for SSE handler)."""
    with _operations_lock:
        op = _operations.get(op_id)
        if op:
            return dict(op)
    return None
