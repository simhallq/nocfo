"""HTTP request handler for the Browser API server."""

import json
import os
import time
import traceback
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import structlog

from nocfo.browser import chrome

logger = structlog.get_logger()


class BrowserAPIHandler(BaseHTTPRequestHandler):
    """Request handler for the Browser API HTTP server.

    Attributes set by the server:
        pw_worker: PlaywrightWorker for marshalling browser operations
        auth_token: Bearer token for API authentication
        cdp_port: Chrome CDP port
        funnel_base: Tailscale Funnel base URL for BankID QR
        sessions_dir: Per-customer session cookies directory
    """

    pw_worker: Any  # PlaywrightWorker (avoid circular import)
    auth_token: str
    cdp_port: int
    funnel_base: str = ""
    sessions_dir: str = "data/sessions"

    # Route registry
    _routes: dict[tuple[str, str], Callable] = {}

    def log_message(self, format: str, *args: Any) -> None:
        """Override default logging to use structlog."""
        logger.debug("http_request", message=format % args)

    def _authenticate(self) -> bool:
        """Check bearer token authentication."""
        if not self.auth_token:
            return True  # No token configured = no auth required

        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_json({"error": "Missing Authorization header"}, status=401)
            return False

        token = auth_header[7:]
        if token != self.auth_token:
            self._send_json({"error": "Invalid token"}, status=401)
            return False
        return True

    def _read_body(self) -> dict[str, Any]:
        """Read and parse JSON request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw)

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, data: bytes, content_type: str, filename: str) -> None:
        """Send a file download response."""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse_headers(self) -> None:
        """Send SSE response headers."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _serve_static(self, filepath: str) -> None:
        """Serve a static file."""
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            if filepath.endswith(".html"):
                self.send_header("Content-Type", "text/html; charset=utf-8")
            else:
                self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._send_json({"error": "file not found"}, status=500)

    def _with_page(self, fn: Callable) -> Any:
        """Run fn(page) on the Playwright thread.

        Reuses the first existing page (to keep Fortnox session/auth) or creates
        a new one. Does NOT close the page after use — Fortnox SPA state is
        preserved across operations.
        """
        def work(browser):
            contexts = browser.contexts
            if not contexts:
                ctx = browser.new_context()
            else:
                ctx = contexts[0]
            # Reuse existing page to preserve session state
            pages = ctx.pages
            if pages:
                return fn(pages[0])
            page = ctx.new_page()
            return fn(page)

        return self.pw_worker.submit(work)

    def _route(self, method: str, path: str) -> Callable | None:
        """Look up a route handler."""
        return self._routes.get((method, path))

    def _dispatch(self, method: str) -> None:
        """Dispatch a request to the appropriate route handler."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # Health endpoint doesn't require auth
        if path == "/health" and method == "GET":
            from nocfo.browser.tokens import cleanup_expired_tokens
            cleanup_expired_tokens()
            return self._handle_health()

        # Token-authenticated endpoints (no bearer auth)
        if path == "/auth/live" and method == "GET":
            from nocfo.browser.tokens import validate_token_for_stream
            token = params.get("token", [""])[0]
            op_id = validate_token_for_stream(token)
            if not op_id:
                self._send_json({"error": "invalid or expired token"}, status=403)
                return
            static_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "fortnox", "web", "static",
            )
            self._serve_static(os.path.join(static_dir, "auth.html"))
            return

        if path == "/auth/stream" and method == "GET":
            from nocfo.browser.tokens import validate_token_for_stream, get_token_context
            from nocfo.browser.operations_state import get_operation_internal
            token = params.get("token", [""])[0]
            op_id = validate_token_for_stream(token)
            if not op_id:
                self._send_json({"error": "invalid or expired token"}, status=403)
                return
            self._handle_sse_stream(op_id, token)
            return

        # Bearer-authenticated endpoints
        if not self._authenticate():
            return

        # Prefix-matched routes
        if path.startswith("/operation/") and method == "GET":
            from nocfo.browser.operations_state import get_operation
            parts = path.split("/")
            if len(parts) >= 3:
                op_id = parts[2]
                op = get_operation(op_id)
                if op:
                    self._send_json(op)
                else:
                    self._send_json({"error": "operation not found"}, status=404)
            else:
                self._send_json({"error": "missing operation id"}, status=400)
            return

        if path.startswith("/auth/session/") and method == "GET":
            parts = path.split("/")
            if len(parts) >= 4:
                customer_id = parts[3]
                from nocfo.fortnox.web.session import has_valid_session
                has_session = has_valid_session(customer_id, sessions_dir=self.sessions_dir)
                self._send_json({
                    "customer_id": customer_id,
                    "has_session": has_session,
                })
            else:
                self._send_json({"error": "missing customer_id"}, status=400)
            return

        # Registry-based routes
        handler = self._route(method, path)
        if handler:
            try:
                handler(self)
            except Exception as e:
                logger.error("handler_error", path=path, error=str(e))
                self._send_json(
                    {"error": str(e), "traceback": traceback.format_exc()},
                    status=500,
                )
        else:
            self._send_json({"error": f"Not found: {method} {path}"}, status=404)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    # --- Built-in routes ---

    def _handle_health(self) -> None:
        """GET /health — Lightweight check (no navigation, never blocks)."""
        cdp_ok = chrome.is_cdp_reachable(self.cdp_port)

        self._send_json({
            "status": "ok" if cdp_ok else "degraded",
            "chrome": {"cdp_reachable": cdp_ok, "port": self.cdp_port},
        })

    def _handle_sse_stream(self, op_id: str, token: str) -> None:
        """SSE stream for QR code data and auth status.

        Also serves as the trigger for lazy BankID flow:
        - If status is "awaiting_user", starts the BankID browser work
        - If status is "failed", resets for a new attempt on page refresh
        """
        from nocfo.browser.operations_state import (
            get_operation_internal,
            update_operation,
            _operations,
            _operations_lock,
        )
        from nocfo.browser.tokens import get_token_context

        op = get_operation_internal(op_id)
        if not op:
            self._send_sse_headers()
            self.wfile.write(b"event: error\ndata: operation_not_found\n\n")
            self.wfile.flush()
            return

        # Auto-retry: if operation failed, reset for new attempt on page refresh
        if op.get("status") == "failed":
            update_operation(op_id, status="awaiting_user", error=None)
            with _operations_lock:
                if op_id in _operations:
                    _operations[op_id]["_browser_work_started"] = False
            op = get_operation_internal(op_id)

        # Lazy start: trigger BankID flow when user opens the page
        if op.get("status") == "awaiting_user":
            from nocfo.fortnox.web.handlers import trigger_bankid_flow
            trigger_bankid_flow(op_id, self.pw_worker, self.sessions_dir)

        self._send_sse_headers()

        stop_event = op["stop_event"]

        # Send context event
        ctx = get_token_context(token)
        if ctx:
            self.wfile.write(
                f"event: context\ndata: {json.dumps(ctx)}\n\n".encode()
            )
            self.wfile.flush()

        last_qr = None
        last_uri = None
        try:
            while not stop_event.is_set():
                current_op = get_operation_internal(op_id) or {}
                status = current_op.get("status", "unknown")
                qr_data = current_op.get("_qr_data")
                bankid_uri = current_op.get("_bankid_uri")

                if status in ("authenticated", "complete"):
                    self.wfile.write(b"event: status\ndata: authenticated\n\n")
                    self.wfile.flush()
                    break
                elif status == "failed":
                    self.wfile.write(b"event: status\ndata: failed\n\n")
                    self.wfile.flush()
                    break
                elif status in ("waiting_for_qr", "pending", "awaiting_user", "starting"):
                    if qr_data and qr_data != last_qr:
                        self.wfile.write(
                            f"event: qr\ndata: {qr_data}\n\n".encode()
                        )
                        self.wfile.flush()
                        last_qr = qr_data
                    elif not qr_data:
                        self.wfile.write(
                            b"event: waiting\ndata: looking_for_qr\n\n"
                        )
                        self.wfile.flush()
                    if bankid_uri and bankid_uri != last_uri:
                        self.wfile.write(
                            f"event: bankid_uri\ndata: {bankid_uri}\n\n".encode()
                        )
                        self.wfile.flush()
                        last_uri = bankid_uri
                else:
                    self.wfile.write(b"event: status\ndata: authenticated\n\n")
                    self.wfile.flush()
                    break

                time.sleep(0.4)
        except (BrokenPipeError, ConnectionResetError):
            pass


def register_route(method: str, path: str) -> Callable:
    """Decorator to register a route handler."""
    def decorator(fn: Callable) -> Callable:
        BrowserAPIHandler._routes[(method, path)] = fn
        return fn
    return decorator
