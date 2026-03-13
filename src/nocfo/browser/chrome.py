"""Chrome launcher and CDP connection management."""

import shutil
import socket
import subprocess
import time
from pathlib import Path

import structlog
from playwright.sync_api import Browser, sync_playwright

logger = structlog.get_logger()

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]

DEFAULT_CDP_PORT = 9222
DEFAULT_PROFILE_DIR = Path("data/browser_profile")


def find_chrome() -> str:
    """Locate Chrome binary on the system."""
    for path in CHROME_PATHS:
        if path and Path(path).exists():
            return path
    raise FileNotFoundError(
        "Chrome not found. Install Google Chrome or set path manually."
    )


def is_cdp_reachable(port: int = DEFAULT_CDP_PORT, timeout: float = 2.0) -> bool:
    """Check if Chrome CDP port is reachable."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def launch_chrome(
    *,
    port: int = DEFAULT_CDP_PORT,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    headless: bool = False,
    wait: bool = True,
) -> subprocess.Popen:
    """Launch Chrome with remote debugging enabled.

    Returns the subprocess handle. Chrome persists independently of this process.
    """
    chrome_bin = find_chrome()
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=sv",
        "--window-size=1280,720",
    ]

    if headless:
        args.append("--headless=new")

    logger.info("chrome_launch", port=port, profile=str(profile_dir), headless=headless)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if wait:
        # Wait for CDP port to become reachable
        for _ in range(30):
            if is_cdp_reachable(port):
                logger.info("chrome_ready", port=port, pid=proc.pid)
                return proc
            time.sleep(0.5)
        proc.terminate()
        raise TimeoutError(f"Chrome did not start within 15 seconds (port {port})")

    return proc


def connect(port: int = DEFAULT_CDP_PORT) -> tuple:
    """Connect to Chrome via CDP and return (playwright, browser).

    Caller is responsible for calling playwright.stop() when done.
    """
    if not is_cdp_reachable(port):
        raise ConnectionError(f"Chrome CDP not reachable on port {port}")

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://localhost:{port}")
    logger.info("cdp_connected", port=port)
    return pw, browser
