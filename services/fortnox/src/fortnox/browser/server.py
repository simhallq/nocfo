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

from fortnox.browser import chrome
from fortnox.browser.handler import BrowserAPIHandler

# Import handlers to trigger @register_route decorators
import fortnox.web.handlers  # noqa: F401

logger = structlog.get_logger()

DEFAULT_PORT = 8790
DEFAULT_CDP_PORT = 9222


class PlaywrightWorker:
    """Runs Playwright operations on a dedicated thread.

    Playwright's sync API is bound to the greenlet/thread where sync_playwright
    was started. HTTP requests arrive on different threads, so we marshal all
    Playwright work through a queue to a single worker thread.

    Features lazy CDP connection (connects on first submit) and automatic
    reconnect on TargetClosedError / connection errors.
    """

    # Counter for unique thread names when multiple workers exist
    _instance_counter = 0

    def __init__(self, cdp_port: int) -> None:
        self._cdp_port = cdp_port
        self._queue: queue.Queue = queue.Queue()
        PlaywrightWorker._instance_counter += 1
        name = f"playwright-worker-{PlaywrightWorker._instance_counter}"
        self._thread = threading.Thread(target=self._run, daemon=True, name=name)
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

    def submit(self, fn, timeout: float = 60):
        """Submit a callable to run on the Playwright thread. Blocks until done.

        Args:
            fn: Callable that receives the browser instance.
            timeout: Max seconds to wait for the result. Default 60s.

        Raises:
            TimeoutError: If the operation does not complete within timeout.
        """
        result_queue: queue.Queue = queue.Queue()
        self._queue.put((fn, result_queue))
        try:
            ok, value = result_queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(
                f"Playwright operation timed out after {timeout}s"
            )
        if ok:
            return value
        raise value

    def is_healthy(self) -> bool:
        """Check if the CDP connection is alive."""
        try:
            if self._browser:
                self._browser.version
                return True
        except Exception:
            pass
        return False

    def _connect(self) -> None:
        """Establish (or re-establish) the CDP connection.

        Called from the worker thread only.
        """
        # Tear down existing connection if any
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None
            self._browser = None

        chrome.ensure_chrome_running(self._cdp_port)
        self._pw, self._browser = chrome.connect(self._cdp_port)
        logger.info("cdp_connection_established", cdp_port=self._cdp_port,
                     thread=self._thread.name)

    def _run(self) -> None:
        """Worker loop — runs on the dedicated Playwright thread."""
        self._connect()
        self._ready.set()
        logger.info("playwright_worker_started", cdp_port=self._cdp_port,
                     thread=self._thread.name)

        while True:
            item = self._queue.get()
            if item is None:
                break
            fn, result_queue = item
            try:
                result = fn(self._browser)
                result_queue.put((True, result))
            except Exception as e:
                # Attempt reconnect on connection-related errors
                if self._is_connection_error(e):
                    logger.warning("cdp_connection_lost", error=str(e),
                                   thread=self._thread.name, action="reconnecting")
                    try:
                        self._connect()
                        # Retry once after reconnect
                        result = fn(self._browser)
                        result_queue.put((True, result))
                        continue
                    except Exception as retry_err:
                        result_queue.put((False, retry_err))
                        continue
                result_queue.put((False, e))

        # Cleanup
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    @staticmethod
    def _is_connection_error(exc: Exception) -> bool:
        """Check if an exception indicates a lost CDP connection."""
        err_name = type(exc).__name__
        if err_name in ("TargetClosedError", "ConnectionError"):
            return True
        msg = str(exc).lower()
        if "target closed" in msg or "connection" in msg or "browser has been closed" in msg:
            return True
        return False


class PlaywrightWorkerPool:
    """Pool of Playwright workers sharing the same Chrome CDP connection.

    Separates auth (long-running BankID flows) from ops (fast operations)
    so they don't block each other.
    """

    def __init__(self, cdp_port: int) -> None:
        self.auth_worker = PlaywrightWorker(cdp_port)
        self.ops_worker = PlaywrightWorker(cdp_port)

    def start(self) -> None:
        self.auth_worker.start()
        self.ops_worker.start()

    def stop(self) -> None:
        self.auth_worker.stop()
        self.ops_worker.stop()


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
    pool = PlaywrightWorkerPool(cdp_port)
    pool.start()

    # Configure handler class attributes
    BrowserAPIHandler.pw_worker_pool = pool  # type: ignore[attr-defined]
    BrowserAPIHandler.pw_worker = pool.ops_worker  # type: ignore[attr-defined]  # backward compat
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
    server._pw_worker_pool = pool  # type: ignore[attr-defined]

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
        server._pw_worker_pool.stop()  # type: ignore[attr-defined]


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
