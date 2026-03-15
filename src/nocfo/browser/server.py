"""Browser API HTTP server — entry point."""

import argparse
import logging
import os
import queue
import signal
import socket
import subprocess
import threading
from http.server import ThreadingHTTPServer

import structlog

from nocfo.browser import chrome
from nocfo.browser.handler import BrowserAPIHandler

# Import handlers to trigger @register_route decorators
import nocfo.fortnox.web.handlers  # noqa: F401

logger = structlog.get_logger()

DEFAULT_PORT = 8790
DEFAULT_CDP_PORT = 9222


class PlaywrightWorker:
    """Runs Playwright operations on a dedicated thread.

    Playwright's sync API is bound to the greenlet/thread where sync_playwright
    was started. HTTP requests arrive on different threads, so we marshal all
    Playwright work through a queue to a single worker thread.
    """

    def __init__(self, cdp_port: int) -> None:
        self._cdp_port = cdp_port
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="playwright-worker")
        self._pw = None
        self._browser = None
        self._ready = threading.Event()

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=15)
        if not self._ready.is_set():
            raise RuntimeError("Playwright worker failed to start")

    def stop(self) -> None:
        self._queue.put(None)  # sentinel
        self._thread.join(timeout=5)

    def submit(self, fn):
        """Submit a callable to run on the Playwright thread. Blocks until done."""
        result_queue: queue.Queue = queue.Queue()
        self._queue.put((fn, result_queue))
        ok, value = result_queue.get()
        if ok:
            return value
        raise value

    def _run(self) -> None:
        """Worker loop — runs on the dedicated Playwright thread."""
        self._pw, self._browser = chrome.connect(self._cdp_port)
        self._ready.set()
        logger.info("playwright_worker_started", cdp_port=self._cdp_port)

        while True:
            item = self._queue.get()
            if item is None:
                break
            fn, result_queue = item
            try:
                result = fn(self._browser)
                result_queue.put((True, result))
            except Exception as e:
                result_queue.put((False, e))

        # Cleanup
        try:
            self._pw.stop()
        except Exception:
            pass


def create_server(
    *,
    port: int = DEFAULT_PORT,
    cdp_port: int = DEFAULT_CDP_PORT,
    auth_token: str = "",
    funnel_base: str = "",
    sessions_dir: str = "data/sessions",
) -> ThreadingHTTPServer:
    """Create and configure the Browser API server.

    Uses ThreadingHTTPServer to support concurrent SSE connections.
    """
    worker = PlaywrightWorker(cdp_port)
    worker.start()

    # Configure handler class attributes
    BrowserAPIHandler.pw_worker = worker  # type: ignore[attr-defined]
    BrowserAPIHandler.auth_token = auth_token
    BrowserAPIHandler.cdp_port = cdp_port
    BrowserAPIHandler.funnel_base = funnel_base
    BrowserAPIHandler.sessions_dir = sessions_dir

    # Fail fast with actionable message if port is already in use
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            pid = "?"
            try:
                out = subprocess.check_output(
                    ["lsof", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
                    text=True, stderr=subprocess.DEVNULL,
                )
                pid = out.strip().split("\n")[0]
            except Exception:
                pass
            raise OSError(
                f"Port {port} already in use (PID {pid}). "
                f"A stale server may be running old code. Kill it first: kill {pid}"
            )

    server = ThreadingHTTPServer(("0.0.0.0", port), BrowserAPIHandler)
    server._pw_worker = worker  # type: ignore[attr-defined]

    logger.info(
        "server_created",
        port=port,
        cdp_port=cdp_port,
        auth=bool(auth_token),
        funnel_base=funnel_base or "(not set)",
    )
    return server


def run_server(
    *,
    port: int = DEFAULT_PORT,
    cdp_port: int = DEFAULT_CDP_PORT,
    auth_token: str = "",
    funnel_base: str = "",
    sessions_dir: str = "data/sessions",
) -> None:
    """Start the Browser API server (blocking)."""
    server = create_server(
        port=port,
        cdp_port=cdp_port,
        auth_token=auth_token,
        funnel_base=funnel_base,
        sessions_dir=sessions_dir,
    )

    def shutdown_handler(signum, frame):
        logger.info("server_shutdown", signal=signum)
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logger.info("server_start", port=port)
    print(f"Browser API server listening on http://localhost:{port}")
    print(f"Connected to Chrome CDP on port {cdp_port}")
    if funnel_base:
        print(f"Tailscale Funnel: {funnel_base}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    finally:
        logger.info("server_cleanup")
        server._pw_worker.stop()  # type: ignore[attr-defined]


def main() -> None:
    """CLI entry point for the Browser API server."""
    parser = argparse.ArgumentParser(description="NoCFO Browser API Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP server port")
    parser.add_argument("--cdp-port", type=int, default=DEFAULT_CDP_PORT, help="Chrome CDP port")
    parser.add_argument("--token", default="", help="Bearer token for API auth")
    parser.add_argument("--funnel-base", default="", help="Tailscale Funnel base URL")
    parser.add_argument("--sessions-dir", default="data/sessions", help="Session cookies directory")
    args = parser.parse_args()

    # Allow env var override
    token = args.token or os.environ.get("BROWSER_API_TOKEN", "")
    funnel_base = args.funnel_base or os.environ.get("FUNNEL_BASE", "")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    run_server(
        port=args.port,
        cdp_port=args.cdp_port,
        auth_token=token,
        funnel_base=funnel_base,
        sessions_dir=args.sessions_dir,
    )


if __name__ == "__main__":
    main()
