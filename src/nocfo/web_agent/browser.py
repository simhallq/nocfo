"""Browser lifecycle management with persistent sessions."""

from pathlib import Path

import structlog
from playwright.async_api import BrowserContext, Page, async_playwright

logger = structlog.get_logger()

DEFAULT_USER_DATA_DIR = Path("data/browser_session")


class BrowserManager:
    """Manages Chromium browser lifecycle with session persistence."""

    def __init__(
        self,
        headless: bool = True,
        user_data_dir: Path | None = None,
    ) -> None:
        self._headless = headless
        self._user_data_dir = user_data_dir or DEFAULT_USER_DATA_DIR
        self._playwright = None
        self._context: BrowserContext | None = None

    async def start(self) -> BrowserContext:
        """Launch browser with persistent context for cookie retention."""
        self._user_data_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self._user_data_dir),
            headless=self._headless,
            viewport={"width": 1280, "height": 720},
            locale="sv-SE",
            timezone_id="Europe/Stockholm",
            args=["--disable-blink-features=AutomationControlled"],
        )

        logger.info("browser_started", headless=self._headless)
        return self._context

    async def new_page(self) -> Page:
        """Create a new browser page."""
        if not self._context:
            await self.start()
        assert self._context is not None
        page = await self._context.new_page()
        return page

    async def stop(self) -> None:
        """Close browser and clean up."""
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = None
        self._playwright = None
        logger.info("browser_stopped")

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()
