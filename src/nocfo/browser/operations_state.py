"""In-memory async operation tracking."""

import secrets
import threading
import time
from typing import Any

import structlog

logger = structlog.get_logger()

_operations: dict[str, dict[str, Any]] = {}
_operations_lock = threading.Lock()

# Default TTL for operations (10 minutes)
_DEFAULT_TTL = 600


def new_operation(op_type: str, customer_id: str | None = None, initial_status: str = "pending") -> str:
    """Create a new operation and return its ID."""
    op_id = secrets.token_urlsafe(16)
    now = time.time()
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
            "created": now,
            "expires": now + _DEFAULT_TTL,
            "_last_heartbeat": now,
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
            _operations[op_id]["_last_heartbeat"] = time.time()


def heartbeat(op_id: str) -> None:
    """Update the heartbeat timestamp for an operation."""
    with _operations_lock:
        if op_id in _operations:
            _operations[op_id]["_last_heartbeat"] = time.time()


def add_qr_url(op_id: str, url: str) -> None:
    """Add a QR streaming URL to the operation."""
    with _operations_lock:
        if op_id in _operations:
            _operations[op_id]["qr_urls"].append(url)


def reset_for_retry(op_id: str) -> bool:
    """Atomically reset an operation for a new auth attempt.

    Sets status to "awaiting_user", clears error, resets _browser_work_started,
    signals the old stop_event, and creates a fresh stop_event.
    Returns True if the operation was found and reset.
    """
    with _operations_lock:
        op = _operations.get(op_id)
        if not op:
            return False
        op["status"] = "awaiting_user"
        op["error"] = None
        op["_browser_work_started"] = False
        op["_last_heartbeat"] = time.time()
        op["expires"] = time.time() + _DEFAULT_TTL
        op["stop_event"].set()  # Signal old threads to exit
        op["stop_event"] = threading.Event()  # Fresh event for next attempt
        return True


def cleanup_expired_operations() -> int:
    """Remove operations whose TTL has expired. Returns count of removed operations.

    Operations in 'awaiting_user' status are never cleaned up — the user
    may open the live_url hours later (async flow).
    """
    now = time.time()
    expired_ids = []
    with _operations_lock:
        for op_id, op in _operations.items():
            if op.get("status") == "awaiting_user":
                continue  # Never expire pending operations
            if now > op.get("expires", float("inf")):
                expired_ids.append(op_id)
        for op_id in expired_ids:
            # Signal stop_event so any polling threads exit
            _operations[op_id]["stop_event"].set()
            del _operations[op_id]
    if expired_ids:
        logger.info("operations_cleanup", removed=len(expired_ids), ids=expired_ids)
    return len(expired_ids)


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


# --- Background cleanup thread ---

def _cleanup_loop() -> None:
    """Background loop that periodically removes expired operations."""
    while True:
        try:
            time.sleep(60)
            cleanup_expired_operations()
        except Exception:
            pass  # Daemon thread — never crash


_cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True, name="op-cleanup")
_cleanup_thread.start()
